"""Capacidades del asistente expresadas como tools.

El RAG del Lab 02 se convierte aquí en una tool más (buscar_documentos). Solo hace la
RECUPERACIÓN: devuelve los fragmentos numerados con su fuente, y el LLM que la pidió
redacta la respuesta. Para el agente no hay diferencia entre buscar en documentos,
consultar un servidor MCP o ejecutar una función local: todas son `Tool`.

Uso (sin LLM ni API key; requiere el índice de ingest.py):
    uv run python labs/04-agent-orchestration/capabilities.py "¿Cuándo es el primer parcial?"
"""

import asyncio
import sys
from typing import Any

from asistente.rag.rag import CourseRAG, format_context
from asistente.agente.tools import Tool


def rag_tool(rag: CourseRAG, niveles: set[str]) -> Tool:
    """buscar_documentos: solo RECUPERA, y solo en los `niveles` del rol (fijados por el programa).

    No llama a rag.answer: la redacción la hace el LLM que pidió la tool. El LLM no puede elegir
    el nivel: no es un parámetro de la tool.
    """

    async def run(arguments: dict[str, Any]) -> str:
        consulta = str(arguments.get("consulta", "")).strip()
        if not consulta:
            raise ValueError("falta la consulta")
        # El embedding de la consulta es CPU: en un hilo para no bloquear el bucle.
        resultados, oculto = await asyncio.to_thread(rag.retrieve, consulta, niveles)
        return format_context(resultados, oculto)

    return Tool(
        name="buscar_documentos",
        description="Busca en los documentos del curso a los que el usuario tiene acceso (programa, docente, "
        "horarios, evaluación, fechas de parciales, políticas, anuncios, preguntas frecuentes de los labs). "
        "Devuelve fragmentos numerados con su fuente.",
        parameters={
            "type": "object",
            "properties": {
                "consulta": {"type": "string", "description": "Pregunta autocontenida, p. ej. 'fecha del primer parcial'"}
            },
            "required": ["consulta"],
        },
        run=run,
        read_only=True,
        origin="rag",
    )


async def _demo(question: str) -> None:
    from asistente.config import load_rag_settings
    from asistente.rag.embeddings import Embedder
    from asistente.rag.vector_store import VectorStore

    settings = load_rag_settings()
    store = VectorStore.load(settings.index_dir)
    # llm=None: la tool solo usa rag.retrieve(), que no llama al LLM (rag.answer() sí lo haría).
    rag = CourseRAG(None, Embedder(store.embedding_model), store, settings.top_k, settings.min_score)
    tool = rag_tool(rag, {"publico"})
    print(f"{tool.name}({{'consulta': {question!r}}}) →\n")
    print(await tool.run({"consulta": question}))


if __name__ == "__main__":
    asyncio.run(_demo(" ".join(sys.argv[1:]) or "¿Cuándo es el primer parcial?"))
