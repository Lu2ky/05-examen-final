"""Pruebas del núcleo sin Telegram, sin API key y sin depender de qué "quiera" hacer el LLM."""

import functools
import inspect
import json
import shutil
import tempfile
from contextlib import AsyncExitStack
from pathlib import Path

import numpy as np
import pytest

from asistente.seguridad import auditoria
from asistente.seguridad.acceso import niveles_permitidos, tools_permitidas
from asistente.agente.agent import Agent
from asistente.config import DATA_DIR, load_rag_settings
from asistente.rag.embeddings import Embedder
from asistente.llm.llm_client import LLMResponse, ToolCall
from asistente.mcp_academico.mcp_client import load_mcp_tools, open_client
from asistente.agente.orchestrator import Orchestrator, denegar_acciones
from asistente.rag.rag import CourseRAG
from asistente.seguridad.sesiones import Sesion, SesionStore, Usuario
from asistente.rag.vector_store import VectorStore

EST = Sesion(1, "estudiante", "Estudiante Prueba", "2026001", 9e12)
DOC = Sesion(2, "docente", "Docente Prueba", None, 9e12)


class LLMGuionado:
    """LLM falso: pide las tools del guion en orden y luego responde. Registra qué tools recibió."""

    def __init__(self, llamadas: list[tuple[str, dict]]):
        self.guion = list(llamadas)
        self.tools_recibidas: list[str] = []

    def chat(self, messages, *, tools=None, allow_tools=True, **kw):
        self.tools_recibidas = [t["name"] for t in tools or []]
        if self.guion and allow_tools:
            nombre, args = self.guion.pop(0)
            call = ToolCall("c1", nombre, json.dumps(args))
            return LLMResponse("", "fake", "tool_calls", 0, 0, [call])
        return LLMResponse("listo", "fake", "stop", 0, 0)


ACADEMICO_TMP: Path | None = None  # copia de academico.json de la prueba en curso


def con_orq(fn):
    """Abre y cierra el servidor MCP dentro de la MISMA tarea que la prueba (requisito de anyio).

    El servidor trabaja sobre una COPIA de academico.json: registrar_nota escribe en disco y las
    pruebas no deben tocar el archivo real.
    """

    @functools.wraps(fn)
    async def envoltura():
        global ACADEMICO_TMP
        with tempfile.TemporaryDirectory() as tmp:
            ACADEMICO_TMP = Path(tmp) / "academico.json"
            shutil.copy(DATA_DIR / "academico.json", ACADEMICO_TMP)
            async with AsyncExitStack() as stack:
                client = await open_client(stack, ACADEMICO_TMP)
                s = load_rag_settings()
                store = VectorStore.load(s.index_dir)
                rag = CourseRAG(None, Embedder(store.embedding_model), store, s.top_k, s.min_score)
                await fn(Orchestrator(None, rag, client, await load_mcp_tools(client)))

    envoltura.__signature__ = inspect.Signature()
    return envoltura


def test_acceso_por_rol():
    assert niveles_permitidos("publico") == {"publico"}
    assert niveles_permitidos("estudiante") == {"publico", "estudiante"}
    assert "docente" in niveles_permitidos("docente")
    assert niveles_permitidos("admin") == {"publico"}  # rol desconocido: falla cerrado
    assert "consultar_notas" not in tools_permitidas("estudiante")
    assert "registrar_nota" not in tools_permitidas("estudiante")
    assert "consultar_mis_notas" not in tools_permitidas("docente")


def test_sesion_expira_y_logout():
    t = [0.0]
    store = SesionStore(session_minutes=1, clock=lambda: t[0])
    u = Usuario("i1", "Ana", "estudiante", "2026001", 7)
    store.crear(u, 7)
    assert store.obtener(7) is not None
    t[0] = 61
    assert store.obtener(7) is None
    store.crear(u, 7)
    assert store.cerrar(7) and store.obtener(7) is None


def test_bloqueo_tras_intentos():
    t = [0.0]
    store = SesionStore(max_attempts=3, block_seconds=100, clock=lambda: t[0])
    assert [store.registrar_fallo(5) for _ in range(3)] == [False, False, True]
    assert store.segundos_bloqueado(5) > 0
    t[0] = 101
    assert store.segundos_bloqueado(5) == 0


def test_auditoria_rechaza_embeddings_e_imagenes(tmp_path):
    f = tmp_path / "a.jsonl"
    auditoria.registrar("login_rechazado", 1, archivo=f, similitud=0.2, motivo="sin_movimiento")
    with pytest.raises(TypeError):
        auditoria.registrar("x", 1, archivo=f, embedding=np.zeros(128))
    with pytest.raises(TypeError):
        auditoria.registrar("x", 1, archivo=f, imagen=b"\xff\xd8")
    assert len(f.read_text().splitlines()) == 1


@con_orq
async def test_tools_por_rol(orq):
    pub = {t.name for t in orq.tools_for(None)}
    est = {t.name for t in orq.tools_for(EST)}
    doc = {t.name for t in orq.tools_for(DOC)}
    assert pub == tools_permitidas("publico")
    assert est == tools_permitidas("estudiante")
    assert doc == tools_permitidas("docente")


@con_orq
async def test_estudiante_sin_parametro_codigo(orq):
    for t in orq.tools_for(EST):
        assert "codigo" not in t.parameters.get("properties", {}), t.name


@con_orq
async def test_mis_notas_usa_la_sesion_y_oculta_observaciones(orq):
    tool = {t.name: t for t in orq.tools_for(EST)}["consultar_mis_notas"]
    # aunque el modelo intente pasar otro código, se ignora: no es un parámetro
    r = json.loads(await tool.run({"codigo": "2026002"}))
    assert r["codigo"] == "2026001" and "observaciones_docente" not in r


@con_orq
async def test_estudiante_no_puede_pedir_tools_de_docente(orq):
    llm = LLMGuionado([("consultar_notas", {"codigo": "2026002"}), ("registrar_nota", {"codigo": "2026001", "evaluacion": "parcial_1", "valor": 5.0})])
    orq.llm = llm
    ans = await orq.answer("dame notas de 2026002 y pon un 5", [], "agente", EST)
    assert "consultar_notas" not in llm.tools_recibidas and "registrar_nota" not in llm.tools_recibidas
    runs = [r for s in ans.steps for r in s.tool_runs]
    assert runs and all(r.status == "error" and "no existe la tool" in r.result for r in runs)


@con_orq
async def test_publico_no_recibe_tools_de_notas(orq):
    llm = LLMGuionado([("consultar_mis_notas", {})])
    orq.llm = llm
    ans = await orq.answer("mis notas", [], "agente", None)
    assert set(llm.tools_recibidas) == tools_permitidas("publico")
    assert ans.steps[0].tool_runs[0].status == "error"


@con_orq
async def test_docente_escritura_requiere_confirmacion(orq):
    args = {"codigo": "2026002", "evaluacion": "parcial_1", "valor": 4.5}
    orq.llm = LLMGuionado([("registrar_nota", args)])
    ans = await orq.answer("registra", [], "agente", DOC)  # confirmación por defecto: deniega
    assert ans.steps[0].tool_runs[0].status == "rechazada"

    async def si(tool, arguments):
        return True

    orq.llm = LLMGuionado([("registrar_nota", args)])
    ans = await orq.answer("registra", [], "agente", DOC, si)
    assert ans.steps[0].tool_runs[0].status == "ok"


@con_orq
async def test_registrar_nota_se_guarda_en_academico_json(orq):
    """La nota confirmada queda en el archivo; una rechazada no lo toca. Se usa la copia temporal, no data/."""
    real = (DATA_DIR / "academico.json").read_text(encoding="utf-8")

    def nota_guardada() -> float | None:
        return json.loads(ACADEMICO_TMP.read_text(encoding="utf-8"))["estudiantes"]["2026001"]["notas"]["parcial_2"]

    inicial = nota_guardada()
    nueva = 4.5 if inicial != 4.5 else 3.5  # un valor distinto del actual, sea cual sea el estado de los datos
    args = {"codigo": "2026001", "evaluacion": "parcial_2", "valor": nueva}

    orq.llm = LLMGuionado([("registrar_nota", args)])
    await orq.answer("registra", [], "agente", DOC)  # sin confirmación: deniega
    assert nota_guardada() == inicial

    async def si(tool, arguments):
        return True

    orq.llm = LLMGuionado([("registrar_nota", args)])
    await orq.answer("registra", [], "agente", DOC, si)
    assert nota_guardada() == nueva
    assert (DATA_DIR / "academico.json").read_text(encoding="utf-8") == real  # el archivo real no se tocó


@con_orq
async def test_verificacion_al_ejecutar_aunque_la_tool_estuviera_en_la_lista(orq):
    """Defensa en profundidad: una tool de docente envuelta para un estudiante se niega al ejecutarse."""
    from asistente.agente.herramientas import con_verificacion

    crudo = {t.name: t for t in orq.mcp_tools}["consultar_notas"]
    tool = con_verificacion(crudo, EST, "estudiante")
    with pytest.raises(Exception, match="no permitida"):
        await tool.run({"codigo": "2026002"})


@con_orq
async def test_rag_publico_no_recibe_fragmentos_restringidos(orq):
    res, oculto = orq.rag.retrieve("¿Cuándo es el simulacro del segundo parcial?", niveles_permitidos("publico"))
    assert {r.chunk.nivel for r in res} <= {"publico"} and oculto


@con_orq
async def test_codigo_con_espacios_no_duplica_ni_oculta_solicitudes(orq):
    por = {t.name: t for t in orq.mcp_tools}
    args = {"parcial": 1, "causa": "incapacidad médica"}
    await por["solicitar_supletorio"].run({"codigo": " 2026001", **args})
    with pytest.raises(Exception, match="Ya existe"):  # el duplicado con otro formato se detecta
        await por["solicitar_supletorio"].run({"codigo": "2026001", **args})
    texto = await por["consultar_solicitudes"].run({"codigo": "2026001"})
    assert '"codigo": "2026001"' in texto and "SUP-2026-001" in texto  # se guardó con el código normalizado
