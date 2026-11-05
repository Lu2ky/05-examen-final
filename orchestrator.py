"""Orquestador: compone LLM, RAG, tools locales y MCP en un solo asistente, POR SESIÓN.

Novedad del examen: cada petición recibe la sesión (o None = público). El software decide
los niveles del RAG y las tools; el LLM solo ve lo permitido. No importa nada de Telegram.

  modo "agente": un agente con las tools del rol (incluida buscar_documentos filtrada por nivel)
  modo "router": una clasificación elige directa / documentos / acciones
"""

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Literal

from mcp import Client

from acceso import niveles_permitidos
from agent import MAX_STEPS, Agent, AgentAnswer, AgentStep, ConfirmFn
from capabilities import rag_tool
from config import load_rag_settings, load_settings
from embeddings import Embedder
from herramientas import herramientas_para
from llm_client import LLMClient, LLMResponse, Message
from mcp_client import load_mcp_tools, open_client
from prompts import build_direct_messages
from rag import CourseRAG
from router import RouterResult, route
from sesiones import Sesion
from tools import Tool
from vector_store import VectorStore

Mode = Literal["router", "agente"]


async def denegar_acciones(tool: Tool, arguments: dict) -> bool:
    """Confirmación por defecto: sin canal que pregunte, ninguna acción con efectos se ejecuta."""
    return False


@dataclass
class OrchestratorAnswer:
    text: str
    mode: Mode
    routing: RouterResult | None = None
    steps: list[AgentStep] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    responses: list[LLMResponse] = field(default_factory=list)
    stopped_by_limit: bool = False
    tools_offered: list[str] = field(default_factory=list)  # las tools que recibió el modelo

    def tools_used(self) -> list[str]:
        return [run.call.name for step in self.steps for run in step.tool_runs]


class Orchestrator:
    def __init__(self, llm: LLMClient, rag: CourseRAG, mcp_client: Client, mcp_tools: list[Tool], max_steps: int = MAX_STEPS):
        self.llm = llm
        self.rag = rag
        self.mcp_client = mcp_client
        self.mcp_tools = mcp_tools
        self.max_steps = max_steps

    def tools_for(self, sesion: Sesion | None) -> list[Tool]:
        niveles = niveles_permitidos(sesion.rol if sesion else "publico")
        return herramientas_para(sesion, self.mcp_client, self.mcp_tools, rag_tool(self.rag, niveles))

    def _agent(self, sesion: Sesion | None, confirm: ConfirmFn, tools: list[Tool]) -> Agent:
        rol = sesion.rol if sesion else "publico"
        return Agent(self.llm, tools, confirm, self.max_steps, rol, sesion.nombre if sesion else None)

    async def answer(
        self,
        question: str,
        history: list[Message],
        mode: Mode = "agente",
        sesion: Sesion | None = None,
        confirm: ConfirmFn = denegar_acciones,
    ) -> OrchestratorAnswer:
        tools = self.tools_for(sesion)
        offered = [t.name for t in tools]
        if mode == "agente":
            result = await self._agent(sesion, confirm, tools).run(question, history)
            return self._from_agent(result, mode, offered)

        niveles = niveles_permitidos(sesion.rol if sesion else "publico")
        routing = await asyncio.to_thread(route, self.llm, question)
        ruta = routing.decision.ruta
        if ruta == "directa":
            response = await asyncio.to_thread(self.llm.chat, build_direct_messages(history, question))
            answer = OrchestratorAnswer(response.text, mode, responses=[response], tools_offered=offered)
        elif ruta == "documentos":
            rag_answer = await asyncio.to_thread(self.rag.answer, question, history, niveles)
            sources = sorted({r.chunk.source for r in rag_answer.sources})
            answer = OrchestratorAnswer(
                rag_answer.text, mode, sources=sources, responses=[rag_answer.response], tools_offered=offered
            )
        else:
            acciones = [t for t in tools if t.name != "buscar_documentos"]
            result = await self._agent(sesion, confirm, acciones).run(question, history)
            answer = self._from_agent(result, mode, [t.name for t in acciones])
        answer.routing = routing
        answer.responses.insert(0, routing.response)
        return answer

    @staticmethod
    def _from_agent(result: AgentAnswer, mode: Mode, offered: list[str]) -> OrchestratorAnswer:
        return OrchestratorAnswer(
            result.text,
            mode,
            steps=result.steps,
            responses=[step.response for step in result.steps],
            stopped_by_limit=result.stopped_by_limit,
            tools_offered=offered,
        )


async def create_orchestrator(stack: AsyncExitStack) -> Orchestrator:
    """Arma el sistema: configuración, LLM, índice, RAG y servidor MCP (abierto hasta cerrar `stack`)."""
    settings = load_settings()
    rag_settings = load_rag_settings()
    store = VectorStore.load(rag_settings.index_dir)
    llm = LLMClient(settings)
    rag = CourseRAG(
        llm=llm,
        embedder=Embedder(store.embedding_model),
        store=store,
        top_k=rag_settings.top_k,
        min_score=rag_settings.min_score,
    )
    mcp_client = await open_client(stack)
    return Orchestrator(llm, rag, mcp_client, await load_mcp_tools(mcp_client))
