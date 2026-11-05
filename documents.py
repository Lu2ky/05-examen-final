"""Carga de documentos y chunking, con NIVEL de acceso por fragmento.

El nivel sale de la carpeta de origen, nunca del contenido del documento:
    data/publico/*.md                  → "publico"
    data/restringido/estudiante/*.md   → "estudiante"
    data/restringido/docente/*.md      → "docente"
"""

from dataclasses import dataclass
from pathlib import Path

NIVELES = ("publico", "estudiante", "docente")

# (subcarpeta relativa a data_dir, nivel)
CARPETAS_POR_NIVEL = (
    ("publico", "publico"),
    ("restringido/estudiante", "estudiante"),
    ("restringido/docente", "docente"),
)


@dataclass(frozen=True)
class Document:
    source: str  # nombre del archivo, p. ej. "evaluacion.md"
    text: str
    nivel: str = "publico"


@dataclass(frozen=True)
class Chunk:
    id: str  # nivel + documento + posición, p. ej. "docente/casos-especiales.md#2"
    source: str
    text: str
    nivel: str = "publico"


def load_documents(data_dir: Path) -> list[Document]:
    documents: list[Document] = []
    for carpeta, nivel in CARPETAS_POR_NIVEL:
        for path in sorted((data_dir / carpeta).glob("*.md")):
            documents.append(Document(source=path.name, text=path.read_text(encoding="utf-8"), nivel=nivel))
    return documents


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Ventanas de `chunk_size` palabras; consecutivas comparten `overlap` palabras."""
    words = text.split()
    step = chunk_size - overlap
    chunks = []
    for start in range(0, len(words), step):
        chunks.append(" ".join(words[start : start + chunk_size]))
        if start + chunk_size >= len(words):
            break
    return chunks


def chunk_documents(documents: list[Document], chunk_size: int, overlap: int) -> list[Chunk]:
    return [
        Chunk(id=f"{doc.nivel}/{doc.source}#{i}", source=doc.source, text=text, nivel=doc.nivel)
        for doc in documents
        for i, text in enumerate(chunk_text(doc.text, chunk_size, overlap))
    ]


if __name__ == "__main__":
    sample = "uno dos tres cuatro cinco seis siete ocho nueve diez"
    for chunk in chunk_text(sample, chunk_size=4, overlap=1):
        print(chunk)
