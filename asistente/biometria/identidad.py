"""Identidad: rostro 1:1 y prueba de vida. El `motivo` va SOLO a la auditoría, nunca al usuario.

Verificación 1:1: el rostro se compara contra los embeddings del dueño de ESA cuenta de Telegram
(rostros/<telegram_user_id>.npy), no contra todos los enrolados.
"""

import time

import numpy as np

from asistente.biometria import liveness
from asistente.config import ROSTROS_DIR, load_access_settings
from asistente.biometria.faces import Rostros, mejor_similitud

_rostros: Rostros | None = None


def _modelos() -> Rostros:
    global _rostros
    if _rostros is None:
        _rostros = Rostros()
    return _rostros


def cargar_enrolados(telegram_user_id: int) -> np.ndarray | None:
    ruta = ROSTROS_DIR / f"{telegram_user_id}.npy"
    return np.load(ruta) if ruta.exists() else None


def verificar_rostro(telegram_user_id: int, imagen: np.ndarray) -> tuple[bool, float]:
    """Una imagen BGR con exactamente un rostro, comparada con el dueño de la cuenta."""
    enrolados = cargar_enrolados(telegram_user_id)
    if enrolados is None:
        return False, 0.0
    rostros = _modelos()
    detectados = rostros.detectar(imagen)
    if len(detectados) != 1:  # 0 o más de 1: se rechaza
        return False, 0.0
    sim = mejor_similitud(rostros.embedding(imagen, detectados[0]), enrolados)
    return sim >= load_access_settings().face_match_threshold, sim


def verificar_vida(
    telegram_user_id: int, video: str, reto: liveness.Reto, ahora: float | None = None
) -> tuple[bool, float, str]:
    """Reto vigente y sin usar + video-nota válida + frame frontal contra el dueño de la cuenta."""
    ajustes = load_access_settings()
    if reto.usado:
        return False, 0.0, "reto_usado"
    reto.usado = True  # un reto sirve una sola vez, pase lo que pase
    if (time.time() if ahora is None else ahora) - reto.emitido_en > ajustes.liveness_timeout_seconds:
        return False, 0.0, "reto_vencido"
    enrolados = cargar_enrolados(telegram_user_id)
    if enrolados is None:
        return False, 0.0, "sin_enrolamiento"
    return liveness.analizar_video(video, reto.tipo, _modelos(), enrolados, ajustes.face_match_threshold)
