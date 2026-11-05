"""Calcula FAR y FRR para varios umbrales con fotos aportadas por los humanos.

    fotos/genuinos/<id_usuario>/*.jpg   fotos NUEVAS de cada integrante (no las de enrolamiento)
    fotos/impostores/*.jpg              p. ej. Labeled Faces in the Wild (dataset público)

FRR = genuinos rechazados / genuinos.  FAR = impostores aceptados / impostores.
Se exige un mínimo de 10 pares genuinos y 20 impostores; si faltan, avisa y no calcula.

Uso:
    uv run python umbral.py [--umbrales 0.25 0.30 0.363 0.45]
"""

import argparse
import sys

import cv2
import numpy as np

from asistente.config import FOTOS_DIR, ROSTROS_DIR
from asistente.biometria.faces import Rostros, mejor_similitud
from asistente.seguridad.sesiones import cargar_usuarios

MIN_GENUINOS, MIN_IMPOSTORES = 10, 20
EXTENSIONES = ("*.jpg", "*.jpeg", "*.png")


def listar(carpeta):
    return sorted(p for ext in EXTENSIONES for p in carpeta.glob(ext)) if carpeta.is_dir() else []


def embedding_unico(rostros: Rostros, ruta):
    imagen = cv2.imread(str(ruta))
    if imagen is None:
        return None
    detectados = rostros.detectar(imagen)
    return rostros.embedding(imagen, detectados[0]) if len(detectados) == 1 else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--umbrales", type=float, nargs="+", default=[0.25, 0.30, 0.363, 0.45, 0.55])
    args = ap.parse_args()
    if len(args.umbrales) < 3:
        print("[umbral] Se piden al menos 3 umbrales.")
        return 1

    carpeta_gen, carpeta_imp = FOTOS_DIR / "genuinos", FOTOS_DIR / "impostores"
    usuarios = [u for u in cargar_usuarios() if u.telegram_user_id is not None]
    if not usuarios:
        print("[umbral] Nadie está enrolado: ejecuta enroll.py primero.")
        return 1
    rostros = Rostros()

    genuinos: list[float] = []
    impostores: list[float] = []
    for u in usuarios:
        ruta_emb = ROSTROS_DIR / f"{u.telegram_user_id}.npy"
        if not ruta_emb.exists():
            print(f"[umbral] Falta {ruta_emb}: ejecuta enroll.py para {u.id}.")
            return 1
        enrolados = np.load(ruta_emb)
        for foto in listar(carpeta_gen / u.id):
            e = embedding_unico(rostros, foto)
            if e is not None:
                genuinos.append(mejor_similitud(e, enrolados))
        # Los impostores se comparan contra cada usuario enrolado (1:1 contra su cuenta).
        for foto in listar(carpeta_imp):
            e = embedding_unico(rostros, foto)
            if e is not None:
                impostores.append(mejor_similitud(e, enrolados))

    n_imp_fotos = len(listar(carpeta_imp))
    if len(genuinos) < MIN_GENUINOS or n_imp_fotos < MIN_IMPOSTORES:
        print(f"[umbral] No se calcula: se requieren ≥{MIN_GENUINOS} pares genuinos válidos "
              f"(hay {len(genuinos)} en {carpeta_gen}/<id_usuario>/) y ≥{MIN_IMPOSTORES} impostores "
              f"(hay {n_imp_fotos} fotos en {carpeta_imp}/).")
        return 1

    g, i = np.array(genuinos), np.array(impostores)
    print(f"Pares genuinos: {len(g)} · pares impostores: {len(i)}\n")
    print(f"{'umbral':>8} {'FRR':>8} {'FAR':>8}")
    filas = []
    for t in sorted(args.umbrales):
        frr, far = float((g < t).mean()), float((i >= t).mean())
        filas.append((t, far, frr))
        print(f"{t:>8.3f} {frr:>8.1%} {far:>8.1%}")

    # Propuesta: aquí aceptar a un impostor (FAR) es el error grave (se entregan notas ajenas).
    candidatos = [f for f in filas if f[1] == 0.0] or [min(filas, key=lambda f: f[1])]
    t, far, frr = min(candidatos, key=lambda f: f[2])
    print(f"\nPropuesta: {t:.3f} (FAR={far:.1%}, FRR={frr:.1%}): el menor FRR entre los umbrales con el FAR más bajo.")
    print("Justificación a revisar por el grupo: un falso positivo expone datos de otra persona; un falso rechazo "
          "solo obliga a reintentar. Con dinero en juego, el FAR debería ser aún más estricto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
