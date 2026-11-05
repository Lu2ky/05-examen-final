"""Núcleo del asistente: se prueba sin Telegram. No importa nada de Telegram.

    responder(pregunta, historial, sesion) -> str

La identidad (rol, nombre, código) viene SIEMPRE de la sesión; el texto de la pregunta nunca
cambia quién es el usuario ni qué puede ver.
"""

from agent import ConfirmFn
from llm_client import Message
from orchestrator import Mode, Orchestrator, OrchestratorAnswer, denegar_acciones
from sesiones import Sesion


async def responder_con_traza(
    orquestador: Orchestrator,
    pregunta: str,
    historial: list[Message],
    sesion: Sesion | None,
    confirmar: ConfirmFn = denegar_acciones,
    modo: Mode = "agente",
) -> OrchestratorAnswer:
    return await orquestador.answer(pregunta, historial, modo, sesion, confirmar)


async def responder(
    orquestador: Orchestrator,
    pregunta: str,
    historial: list[Message],
    sesion: Sesion | None,
    confirmar: ConfirmFn = denegar_acciones,
    modo: Mode = "agente",
) -> str:
    return (await responder_con_traza(orquestador, pregunta, historial, sesion, confirmar, modo)).text
