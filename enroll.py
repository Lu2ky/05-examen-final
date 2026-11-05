"""Enrolamiento LOCAL (no desde el chat): fotos → embeddings en rostros/.

Uso:
    uv run python enroll.py --id integrante_1 --telegram-id 123456789

Lee fotos/enrolamiento/<id>/*.jpg (de 3 a 5, un solo rostro cada una), guarda SOLO los
embeddings en rostros/<telegram_user_id>.npy y vincula el telegram_user_id en usuarios.json.
Por qué no desde Telegram: quien controle la cuenta podría enrolar el rostro de cualquiera.
"""

import argparse
import json
import sys

import cv2
import numpy as np

from config import DATA_DIR, FOTOS_DIR, ROSTROS_DIR
from faces import ModelosFaltantes, Rostros

MIN_FOTOS, MAX_FOTOS = 3, 5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="id en usuarios.json, p. ej. integrante_1")
    ap.add_argument("--telegram-id", required=True, type=int)
    args = ap.parse_args()

    usuarios_path = DATA_DIR / "usuarios.json"
    datos = json.loads(usuarios_path.read_text(encoding="utf-8"))
    usuario = next((u for u in datos["usuarios"] if u["id"] == args.id), None)
    if usuario is None:
        print(f"[enroll] No existe el id {args.id!r} en usuarios.json.")
        return 1
    otro = next((u for u in datos["usuarios"] if u["telegram_user_id"] == args.telegram_id and u["id"] != args.id), None)
    if otro:
        print(f"[enroll] El telegram_user_id {args.telegram_id} ya pertenece a {otro['id']}.")
        return 1

    carpeta = FOTOS_DIR / "enrolamiento" / args.id
    fotos = sorted([*carpeta.glob("*.jpg"), *carpeta.glob("*.jpeg"), *carpeta.glob("*.png")]) if carpeta.is_dir() else []
    if not MIN_FOTOS <= len(fotos) <= MAX_FOTOS:
        print(f"[enroll] Se esperan de {MIN_FOTOS} a {MAX_FOTOS} fotos en {carpeta}/ (hay {len(fotos)}"
              f"{'; la carpeta no existe' if not carpeta.is_dir() else ''}).")
        return 1

    try:
        rostros = Rostros()
    except ModelosFaltantes as exc:
        print(f"[enroll] {exc}")
        return 1

    embeddings = []
    for foto in fotos:
        imagen = cv2.imread(str(foto))
        if imagen is None:
            print(f"[enroll] No se pudo leer {foto.name}.")
            return 1
        detectados = rostros.detectar(imagen)
        if len(detectados) != 1:
            print(f"[enroll] {foto.name}: se esperaba exactamente 1 rostro y hay {len(detectados)}. Nada se guardó.")
            return 1
        embeddings.append(rostros.embedding(imagen, detectados[0]))

    ROSTROS_DIR.mkdir(exist_ok=True)
    np.save(ROSTROS_DIR / f"{args.telegram_id}.npy", np.stack(embeddings))
    usuario["telegram_user_id"] = args.telegram_id
    usuarios_path.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[enroll] {args.id}: {len(embeddings)} embeddings guardados en rostros/{args.telegram_id}.npy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
