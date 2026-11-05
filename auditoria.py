"""Auditoría en JSONL. Sin imágenes ni embeddings: solo valores escalares.

Eventos usados: login_aceptado, login_rechazado, login_bloqueado, acceso_denegado,
tool_restringida, logout, sesion_expirada.
"""

import json
import time
from pathlib import Path
from typing import Any

from config import AUDITORIA_FILE

_ESCALARES = (str, int, float, bool, type(None))


def registrar(evento: str, telegram_user_id: int | None, *, archivo: Path | None = None, **datos: Any) -> None:
    for clave, valor in datos.items():
        if not isinstance(valor, _ESCALARES):
            # Impide por construcción que se cuele una imagen, un embedding o un objeto grande.
            raise TypeError(f"auditoría: {clave!r} debe ser un valor simple, no {type(valor).__name__}")
    entrada = {
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "evento": evento,
        "telegram_user_id": telegram_user_id,
        **datos,
    }
    destino = archivo or AUDITORIA_FILE
    with destino.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entrada, ensure_ascii=False) + "\n")
