"""Sesiones autenticadas, expiración y bloqueo por intentos fallidos.

Rol, nombre y código salen de usuarios.json (cargar_usuarios), NUNCA del texto del chat.
El reloj es inyectable para poder probar la expiración sin esperar.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from asistente.config import DATA_DIR


@dataclass(frozen=True)
class Usuario:
    id: str
    nombre: str
    rol: str
    codigo: str | None
    telegram_user_id: int | None


def cargar_usuarios(path: Path = DATA_DIR / "usuarios.json") -> list[Usuario]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        Usuario(
            id=u["id"],
            nombre=u["nombre"],
            rol=u["rol"],
            codigo=u.get("codigo_estudiante"),
            telegram_user_id=u.get("telegram_user_id"),
        )
        for u in data["usuarios"]
    ]


def usuario_de_telegram(telegram_user_id: int, usuarios: list[Usuario] | None = None) -> Usuario | None:
    """El dueño de la cuenta de Telegram, o None si nadie está enrolado con ese id."""
    for usuario in usuarios if usuarios is not None else cargar_usuarios():
        if usuario.telegram_user_id is not None and usuario.telegram_user_id == telegram_user_id:
            return usuario
    return None


@dataclass(frozen=True)
class Sesion:
    telegram_user_id: int
    rol: str
    nombre: str
    codigo: str | None
    expira_en: float  # instante del reloj del store


class SesionStore:
    def __init__(
        self,
        session_minutes: int = 10,
        max_attempts: int = 3,
        block_seconds: int = 300,
        clock: Callable[[], float] = time.time,
    ):
        self._ttl = session_minutes * 60
        self._max_attempts = max_attempts
        self._block_seconds = block_seconds
        self._clock = clock
        self._sesiones: dict[int, Sesion] = {}
        self._fallos: dict[int, int] = {}
        self._bloqueado_hasta: dict[int, float] = {}

    def crear(self, usuario: Usuario, telegram_user_id: int) -> Sesion:
        sesion = Sesion(telegram_user_id, usuario.rol, usuario.nombre, usuario.codigo, self._clock() + self._ttl)
        self._sesiones[telegram_user_id] = sesion
        self._fallos.pop(telegram_user_id, None)
        return sesion

    def obtener(self, telegram_user_id: int) -> Sesion | None:
        sesion = self._sesiones.get(telegram_user_id)
        if sesion is None:
            return None
        if self._clock() >= sesion.expira_en:
            del self._sesiones[telegram_user_id]
            return None
        return sesion

    def cerrar(self, telegram_user_id: int) -> bool:
        return self._sesiones.pop(telegram_user_id, None) is not None

    # --- bloqueo ---
    def segundos_bloqueado(self, telegram_user_id: int) -> int:
        hasta = self._bloqueado_hasta.get(telegram_user_id)
        if hasta is None:
            return 0
        restante = hasta - self._clock()
        if restante <= 0:
            del self._bloqueado_hasta[telegram_user_id]
            self._fallos.pop(telegram_user_id, None)
            return 0
        return int(restante) + 1

    def registrar_fallo(self, telegram_user_id: int) -> bool:
        """Cuenta un intento fallido. Devuelve True si esta cuenta queda bloqueada."""
        self._fallos[telegram_user_id] = self._fallos.get(telegram_user_id, 0) + 1
        if self._fallos[telegram_user_id] >= self._max_attempts:
            self._bloqueado_hasta[telegram_user_id] = self._clock() + self._block_seconds
            return True
        return False
