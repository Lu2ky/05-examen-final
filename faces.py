"""Rostros con OpenCV: detección (YuNet, con 5 landmarks) y embedding (SFace, 128 dimensiones).

Es el único módulo que conoce a cv2. Los embeddings son vectores de 128 floats: se comparan
con similitud coseno. NUNCA se registran en la auditoría ni se suben al repositorio.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from config import MODELOS_DIR

YUNET = "face_detection_yunet_2023mar.onnx"
SFACE = "face_recognition_sface_2021dec.onnx"


class ModelosFaltantes(FileNotFoundError):
    pass


@dataclass(frozen=True)
class Rostro:
    fila: np.ndarray  # fila YuNet: x, y, w, h, 5 landmarks (x, y), score

    @property
    def caja(self) -> tuple[float, float, float, float]:
        return tuple(float(v) for v in self.fila[:4])  # type: ignore[return-value]

    @property
    def ancho(self) -> float:
        return float(self.fila[2])

    @property
    def ojo_der(self) -> np.ndarray:  # el ojo derecho del sujeto aparece a la izquierda de la imagen
        return self.fila[4:6]

    @property
    def ojo_izq(self) -> np.ndarray:
        return self.fila[6:8]

    @property
    def nariz(self) -> np.ndarray:
        return self.fila[8:10]

    def desplazamiento_nariz(self) -> float:
        """Nariz respecto al punto medio de los ojos, normalizado por el ancho del rostro.

        ~0 = de frente. Cambia de signo al girar la cabeza (sirve para el reto de giro).
        """
        medio = (self.ojo_der[0] + self.ojo_izq[0]) / 2.0
        return float((self.nariz[0] - medio) / max(self.ancho, 1.0))


class Rostros:
    def __init__(self, modelos_dir: Path = MODELOS_DIR, score_threshold: float = 0.8):
        yunet, sface = modelos_dir / YUNET, modelos_dir / SFACE
        faltan = [p.name for p in (yunet, sface) if not p.exists()]
        if faltan:
            raise ModelosFaltantes(
                f"Faltan modelos en {modelos_dir}: {', '.join(faltan)}. "
                "Descárgalos de github.com/opencv/opencv_zoo (face_detection_yunet y face_recognition_sface)."
            )
        self._detector = cv2.FaceDetectorYN.create(str(yunet), "", (320, 320), score_threshold, 0.3, 5000)
        self._reconocedor = cv2.FaceRecognizerSF.create(str(sface), "")

    def detectar(self, imagen: np.ndarray) -> list[Rostro]:
        alto, ancho = imagen.shape[:2]
        self._detector.setInputSize((ancho, alto))
        _, filas = self._detector.detect(imagen)
        return [Rostro(f) for f in filas] if filas is not None else []

    def embedding(self, imagen: np.ndarray, rostro: Rostro) -> np.ndarray:
        alineado = self._reconocedor.alignCrop(imagen, rostro.fila)
        return self._reconocedor.feature(alineado).flatten().astype(np.float32)


def similitud(a: np.ndarray, b: np.ndarray) -> float:
    """Similitud coseno entre dos embeddings (-1 a 1). Es la misma métrica de SFace."""
    return float(np.dot(a, b) / max(np.linalg.norm(a) * np.linalg.norm(b), 1e-12))


def mejor_similitud(embedding: np.ndarray, enrolados: np.ndarray) -> float:
    """Similitud con el más parecido de los embeddings enrolados de UNA persona."""
    return max(similitud(embedding, e) for e in enrolados)
