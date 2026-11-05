"""Prueba de vida: reto aleatorio de un solo uso + análisis de la video-nota.

El reto se elige al azar entre varias opciones, lleva hora de emisión, caduca y sirve una sola
vez. Un video pregrabado de OTRO reto, o reenviado, no lo cumple. Límites (ver informe): un
deepfake en tiempo real que obedezca el reto, o una máscara 3D, no se detienen con esto.
"""

import os
import secrets
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from faces import Rostros, mejor_similitud

RETOS = {
    "izquierda": "Gira la cabeza a tu IZQUIERDA",
    "derecha": "Gira la cabeza a tu DERECHA",
    "acercarse": "ACERCA tu rostro a la cámara",
}

MAX_FRAMES = 40  # frames analizados por video (muestreo uniforme)
MIN_FRACCION_CON_UN_ROSTRO = 0.8  # en giros fuertes el detector puede perder el rostro unos frames


@dataclass(eq=False)
class Reto:
    tipo: str
    emitido_en: float
    usado: bool = False
    id: str = field(default_factory=lambda: secrets.token_hex(4))

    @property
    def instruccion(self) -> str:
        return RETOS[self.tipo]


def nuevo_reto(ahora: float | None = None) -> Reto:
    # secrets, no random: el reto no debe ser predecible.
    return Reto(tipo=secrets.choice(list(RETOS)), emitido_en=time.time() if ahora is None else ahora)


@dataclass(frozen=True)
class Umbrales:
    giro_minimo: float = float(os.getenv("LIVENESS_MIN_TURN", "0.12"))  # cambio de desplazamiento de la nariz
    zoom_minimo: float = float(os.getenv("LIVENESS_MIN_ZOOM", "1.25"))  # crecimiento del ancho del rostro
    consistencia: float = float(os.getenv("FACE_CONSISTENCY_THRESHOLD", "0.25"))  # mismo rostro entre frames
    espejo: bool = os.getenv("LIVENESS_MIRROR", "0").strip() in {"1", "true", "yes"}  # cámara frontal en espejo


def evaluar_movimiento(tipo: str, desplazamientos: list[float], anchos: list[float], u: Umbrales) -> tuple[bool, str]:
    """¿Ocurrió el movimiento pedido? Funciona sobre series de landmarks (probable sin cámara)."""
    if len(desplazamientos) < 5:
        return False, "pocos_frames"
    base = max(1, len(desplazamientos) // 5)
    if tipo == "acercarse":
        crecimiento = max(anchos) / max(float(np.median(anchos[:base])), 1.0)
        return (crecimiento >= u.zoom_minimo, f"zoom={crecimiento:.2f}")
    desde = float(np.median(desplazamientos[:base]))
    # Sin espejo: al girar a TU izquierda la nariz se desplaza hacia la derecha de la imagen (+).
    signo = 1.0 if (tipo == "izquierda") != u.espejo else -1.0
    hacia_mas, hacia_menos = max(desplazamientos) - desde, desde - min(desplazamientos)
    delta, opuesto = (hacia_mas, hacia_menos) if signo > 0 else (hacia_menos, hacia_mas)
    # "opuesto" solo sirve para diagnosticar si la cámara graba en espejo (LIVENESS_MIRROR).
    return (delta >= u.giro_minimo, f"giro={delta:.2f},opuesto={opuesto:.2f}")


def analizar_video(
    ruta_video: str, tipo: str, rostros: Rostros, enrolados: np.ndarray, umbral: float, u: Umbrales | None = None
) -> tuple[bool, float, str]:
    """Aplica i, ii y iii del PDF. Devuelve (ok, similitud del frame frontal, motivo)."""
    u = u or Umbrales()
    cap = cv2.VideoCapture(ruta_video)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    if not cap.isOpened() or total <= 0:
        return False, 0.0, "video_ilegible"
    paso = max(1, total // MAX_FRAMES)

    observaciones = []  # (rostro, embedding, frame)
    analizados = 0
    for indice in range(0, total, paso):
        cap.set(cv2.CAP_PROP_POS_FRAMES, indice)
        ok, frame = cap.read()
        if not ok:
            continue
        analizados += 1
        detectados = rostros.detectar(frame)
        if len(detectados) > 1:
            cap.release()
            return False, 0.0, "mas_de_un_rostro"
        if len(detectados) == 1:
            observaciones.append((detectados[0], rostros.embedding(frame, detectados[0])))
    cap.release()

    if analizados == 0 or len(observaciones) / analizados < MIN_FRACCION_CON_UN_ROSTRO:
        return False, 0.0, "rostro_no_constante"

    # (iii) frame más frontal = nariz más centrada entre los ojos
    desplazamientos = [r.desplazamiento_nariz() for r, _ in observaciones]
    frontal = min(range(len(observaciones)), key=lambda i: abs(desplazamientos[i]))
    emb_frontal = observaciones[frontal][1]

    # (i) es el MISMO rostro a lo largo del video
    if min(mejor_similitud(e, emb_frontal[None, :]) for _, e in observaciones) < u.consistencia:
        return False, 0.0, "rostro_distinto_en_el_video"

    # (ii) el movimiento pedido ocurrió
    ok_mov, detalle = evaluar_movimiento(tipo, desplazamientos, [r.ancho for r, _ in observaciones], u)
    sim = mejor_similitud(emb_frontal, enrolados)
    if not ok_mov:
        return False, sim, f"sin_movimiento:{tipo}:{detalle}"
    if sim < umbral:
        return False, sim, "similitud_baja"
    return True, sim, f"ok:{detalle}"
