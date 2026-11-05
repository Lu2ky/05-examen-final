"""Adaptador de Telegram (long polling). SOLO traduce: no contiene lógica de negocio.

Toda decisión (rol, niveles, tools, verificación de identidad) vive en el núcleo y en identidad.py.

Uso:
    uv run python bot.py
"""

import asyncio
import logging
import os
import secrets
import shutil
import tempfile
import time
from pathlib import Path
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters,
)

import auditoria
import identidad
import liveness
from config import load_access_settings
from llm_client import LLMError, Message
from nucleo import responder
from orchestrator import Orchestrator, create_orchestrator
from prompts import nombre_desarrollador
from sesiones import Sesion, SesionStore, usuario_de_telegram
from tools import Tool

log = logging.getLogger("bot")

MAX_MENSAJES_HISTORIAL = 20
LIMITE_TELEGRAM = 4000
TIEMPO_CONFIRMACION = 60
FALLO_LOGIN = "No pude verificar tu identidad. Inténtalo de nuevo con /login."


@dataclass
class Historial:
    rol: str = "publico"  # rol con el que se generó: si cambia, el historial se descarta
    mensajes: list[Message] = field(default_factory=list)


class AsistenteTelegram:
    def __init__(self, orquestador: Orchestrator):
        self.ajustes = load_access_settings(require_token=True)
        self.orq = orquestador
        self.sesiones = SesionStore(
            self.ajustes.session_minutes, self.ajustes.login_max_attempts, self.ajustes.login_block_seconds
        )
        self.retos: dict[int, liveness.Reto] = {}
        self.historiales: dict[int, Historial] = {}
        self.con_sesion: set[int] = set()
        self.confirmaciones: dict[str, tuple[int, asyncio.Future[bool]]] = {}  # token → (dueño, resultado)

    # --- comandos ---
    async def start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            f"Hola, soy el Asistente del Curso de IA, desarrollado por {nombre_desarrollador()}.\n"
            "Puedo responder preguntas públicas del curso. Para información restringida (notas, "
            "material de tu rol) inicia sesión con /login. Usa /ayuda para ver los comandos."
        )

    async def ayuda(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "/start — presentación\n/quiensoy — tu id de Telegram y el estado de tu sesión\n"
            "/login — iniciar sesión (reconocimiento facial + video-nota)\n/logout — cerrar sesión\n"
            "/ayuda — esta ayuda\nO escribe tu pregunta."
        )

    async def quiensoy(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id
        sesion = self._sesion(uid)
        estado = (
            f"sesión activa como {sesion.rol} ({sesion.nombre}), expira en {max(0, int(sesion.expira_en - self._ahora()))} s"
            if sesion
            else "sin sesión (acceso público)"
        )
        await update.message.reply_text(f"Tu telegram_user_id: {uid}\nEstado: {estado}")

    async def logout(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id
        if self.sesiones.cerrar(uid):
            self.con_sesion.discard(uid)
            self.historiales.pop(update.effective_chat.id, None)
            auditoria.registrar("logout", uid)
            await update.message.reply_text("Sesión cerrada.")
        else:
            await update.message.reply_text("No tenías una sesión iniciada.")

    # --- login con prueba de vida ---
    async def login(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id
        espera = self.sesiones.segundos_bloqueado(uid)
        if espera:
            auditoria.registrar("login_rechazado", uid, motivo="bloqueado")
            await update.message.reply_text(f"Demasiados intentos fallidos. Espera {espera} s antes de reintentar.")
            return
        if usuario_de_telegram(uid) is None or identidad.cargar_enrolados(uid) is None:
            await self._fallo(update, uid, 0.0, "cuenta_no_enrolada")
            return
        reto = liveness.nuevo_reto()
        self.retos[uid] = reto
        await update.message.reply_text(
            f"{reto.instruccion}. Grábate con una VIDEO-NOTA (el círculo) y envíala en "
            f"{self.ajustes.liveness_timeout_seconds} s. Una foto no sirve."
        )

    async def video_nota(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        uid, mensaje = update.effective_user.id, update.message
        espera = self.sesiones.segundos_bloqueado(uid)
        if espera:
            auditoria.registrar("login_rechazado", uid, motivo="bloqueado")
            await mensaje.reply_text(f"Demasiados intentos fallidos. Espera {espera} s antes de reintentar.")
            return
        reto = self.retos.pop(uid, None)  # se saca siempre: un reto sirve una sola vez
        if reto is None:
            await mensaje.reply_text("Primero escribe /login para recibir un reto.")
            return
        if mensaje.forward_origin is not None:
            await self._fallo(update, uid, 0.0, "reenviado")
            return

        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "nota.mp4")
            archivo = await mensaje.video_note.get_file()
            await archivo.download_to_drive(ruta)
            # El análisis es CPU: fuera del bucle de eventos para no congelar el bot.
            ok, sim, motivo = await asyncio.to_thread(identidad.verificar_vida, uid, ruta, reto)
            if not ok and os.getenv("LIVENESS_DEBUG") == "1" and motivo.startswith("sin_movimiento"):
                # Solo para calibrar: copia local (carpeta ignorada por git) del video rechazado.
                destino = Path("videos") / f"rechazado_{reto.tipo}_{int(time.time())}.mp4"
                destino.parent.mkdir(exist_ok=True)
                shutil.copy(ruta, destino)
        if not ok:
            await self._fallo(update, uid, sim, motivo)
            return

        usuario = usuario_de_telegram(uid)
        if usuario is None:  # no debería pasar tras /login, pero no se asume
            await self._fallo(update, uid, sim, "usuario_no_encontrado")
            return
        sesion = self.sesiones.crear(usuario, uid)
        self.con_sesion.add(uid)
        self.historiales.pop(update.effective_chat.id, None)
        auditoria.registrar("login_aceptado", uid, similitud=round(sim, 4), rol=sesion.rol)
        await mensaje.reply_text(f"Hola, {sesion.nombre} ({sesion.rol}). Sesión iniciada por {self.ajustes.session_minutes} min.")

    async def foto(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text("Una foto no sirve para iniciar sesión. Usa /login y envía una video-nota.")

    async def _fallo(self, update: Update, uid: int, sim: float, motivo: str) -> None:
        """El motivo real va solo a la auditoría; al usuario, un mensaje genérico."""
        auditoria.registrar("login_rechazado", uid, similitud=round(sim, 4), motivo=motivo)
        if self.sesiones.registrar_fallo(uid):
            auditoria.registrar("login_bloqueado", uid, intentos=self.ajustes.login_max_attempts)
            await update.message.reply_text(
                f"Demasiados intentos fallidos. Cuenta bloqueada {self.ajustes.login_block_seconds} s."
            )
        else:
            await update.message.reply_text(FALLO_LOGIN)

    # --- preguntas ---
    async def texto(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        uid, chat_id = update.effective_user.id, update.effective_chat.id
        sesion = self._sesion(uid)  # la identidad sale de la sesión, nunca del texto
        rol = sesion.rol if sesion else "publico"
        historial = self.historiales.setdefault(chat_id, Historial(rol=rol))
        if historial.rol != rol:  # login, logout o expiración: lo dicho con otro rol no se reutiliza
            historial = self.historiales[chat_id] = Historial(rol=rol)

        pregunta = update.message.text
        await update.effective_chat.send_action("typing")
        try:
            respuesta = await responder(
                self.orq, pregunta, historial.mensajes, sesion, self._confirmar(update, uid)
            )
        except LLMError:
            log.exception("error del LLM")
            respuesta = "El servicio de IA no está disponible en este momento. Inténtalo de nuevo en un rato."
        except Exception:
            log.exception("error al responder")
            respuesta = "Ocurrió un error al procesar tu pregunta. Inténtalo de nuevo."

        historial.mensajes += [{"role": "user", "content": pregunta}, {"role": "assistant", "content": respuesta}]
        del historial.mensajes[:-MAX_MENSAJES_HISTORIAL]
        await update.message.reply_text(respuesta[:LIMITE_TELEGRAM] or "(sin respuesta)")

    def _confirmar(self, update: Update, uid: int):
        """ConfirmFn del Lab 04, implementada con botones en lugar de la consola."""

        async def confirmar(tool: Tool, argumentos: dict[str, Any]) -> bool:
            token = secrets.token_hex(6)
            futuro: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
            self.confirmaciones[token] = (uid, futuro)
            teclado = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Sí", callback_data=f"si:{token}"), InlineKeyboardButton("No", callback_data=f"no:{token}")]]
            )
            detalle = ", ".join(f"{k}={v}" for k, v in argumentos.items())
            mensaje = await update.effective_chat.send_message(
                f"El asistente quiere ejecutar una ACCIÓN: {tool.name}({detalle})\n¿La autorizas?", reply_markup=teclado
            )
            try:
                return await asyncio.wait_for(futuro, TIEMPO_CONFIRMACION)
            except TimeoutError:
                return False
            finally:
                self.confirmaciones.pop(token, None)
                try:
                    await mensaje.edit_reply_markup(None)
                except Exception:  # quitar los botones es cosmético: no debe perder la decisión del usuario
                    log.warning("no se pudieron quitar los botones de confirmación", exc_info=True)

        return confirmar

    async def boton(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        consulta = update.callback_query
        decision, _, token = (consulta.data or "").partition(":")
        pendiente = self.confirmaciones.get(token)
        # Solo quien originó la acción puede autorizarla.
        if pendiente is None or pendiente[0] != consulta.from_user.id:
            await consulta.answer("Esta confirmación no es válida.", show_alert=True)
            return
        if not pendiente[1].done():
            pendiente[1].set_result(decision == "si")
        await consulta.answer("Autorizada." if decision == "si" else "Cancelada.")

    # --- utilidades ---
    def _ahora(self) -> float:
        return self.sesiones._clock()

    def _sesion(self, uid: int) -> Sesion | None:
        sesion = self.sesiones.obtener(uid)
        if sesion is None and uid in self.con_sesion:
            self.con_sesion.discard(uid)
            auditoria.registrar("sesion_expirada", uid)
        return sesion


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("error no controlado", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Ocurrió un error. Inténtalo de nuevo.")


def construir(asistente: AsistenteTelegram) -> Application:
    app = ApplicationBuilder().token(asistente.ajustes.telegram_token).concurrent_updates(True).build()
    privado = filters.ChatType.PRIVATE  # en grupos el historial mezclaría usuarios con roles distintos
    for nombre, manejador in [("start", asistente.start), ("ayuda", asistente.ayuda), ("quiensoy", asistente.quiensoy),
                              ("login", asistente.login), ("logout", asistente.logout)]:
        app.add_handler(CommandHandler(nombre, manejador, filters=privado))
    app.add_handler(MessageHandler(privado & filters.VIDEO_NOTE, asistente.video_nota))
    app.add_handler(MessageHandler(privado & filters.PHOTO, asistente.foto))
    app.add_handler(MessageHandler(privado & filters.TEXT & ~filters.COMMAND, asistente.texto))
    app.add_handler(CallbackQueryHandler(asistente.boton))
    app.add_error_handler(error_handler)
    return app


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    # httpx registra la URL de cada petición y esa URL contiene el token del bot.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    async with AsyncExitStack() as stack:  # el servidor MCP se abre y cierra en esta misma tarea
        try:
            orquestador = await create_orchestrator(stack)
            app = construir(AsistenteTelegram(orquestador))
        except (ValueError, FileNotFoundError) as exc:
            print(f"[configuración] {exc}")
            return
        async with app:
            await app.start()
            await app.updater.start_polling()
            log.info("Bot en marcha (long polling). Ctrl+C para salir.")
            try:
                await asyncio.Event().wait()
            finally:
                await app.updater.stop()
                await app.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
