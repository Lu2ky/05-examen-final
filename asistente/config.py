"""Configuración de la aplicación a partir de variables de entorno (.env).

Responsabilidad: reunir en un solo lugar todo lo que depende del entorno
(proveedor, credenciales, modelo y parámetros). Ningún otro módulo lee
variables de entorno directamente.

Novedad del Lab 02: RAGSettings. Indexar y buscar no usan el LLM, por eso
tienen su propia configuración y no exigen LLM_API_KEY.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

# Todos estos proveedores exponen la misma API (Chat Completions, compatible con OpenAI).
# Cambiar de proveedor = cambiar URL base + API key + nombre del modelo.
# Groq y OpenRouter tienen planes gratuitos; OpenAI y DeepSeek son de pago.
PROVIDER_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
}

LAB_DIR = Path(__file__).resolve().parents[1]  # raíz del proyecto (config.py está en asistente/)
DATA_DIR = LAB_DIR / "data"  # publico/ y restringido/{estudiante,docente}/, usuarios.json, academico.json
MODELOS_DIR = LAB_DIR / "modelos"  # modelos ONNX de rostro; no se versionan
ROSTROS_DIR = LAB_DIR / "rostros"  # solo embeddings; no se versionan
FOTOS_DIR = LAB_DIR / "fotos"  # las aportan los humanos; no se versionan
AUDITORIA_FILE = LAB_DIR / "auditoria.jsonl"  # no se versiona
INDEX_DIR = LAB_DIR / "index"  # generado por ingest.py; no se versiona


@dataclass(frozen=True)
class Settings:
    provider: str
    base_url: str
    api_key: str
    model: str
    temperature: float
    max_tokens: int


@dataclass(frozen=True)
class RAGSettings:
    data_dir: Path
    index_dir: Path
    embedding_model: str
    chunk_size: int  # palabras por fragmento
    chunk_overlap: int  # palabras compartidas por fragmentos consecutivos
    top_k: int  # cuántos fragmentos recuperar por pregunta
    min_score: float  # similitud mínima para considerar relevante un fragmento


def load_settings() -> Settings:
    # Busca el archivo .env desde el directorio actual hacia arriba.
    load_dotenv(find_dotenv(usecwd=True))

    provider = os.getenv("LLM_PROVIDER", "groq").strip().lower()
    if provider not in PROVIDER_BASE_URLS:
        options = ", ".join(PROVIDER_BASE_URLS)
        raise ValueError(f"LLM_PROVIDER desconocido: {provider!r}. Opciones: {options}")

    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        raise ValueError("Falta LLM_API_KEY. Copia .env.example como .env y agrega tu clave.")

    model = os.getenv("LLM_MODEL", "").strip()
    if not model:
        raise ValueError("Falta LLM_MODEL en el archivo .env.")

    return Settings(
        provider=provider,
        base_url=PROVIDER_BASE_URLS[provider],
        api_key=api_key,
        model=model,
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "512")),
    )


def load_rag_settings() -> RAGSettings:
    load_dotenv(find_dotenv(usecwd=True))

    chunk_size = int(os.getenv("RAG_CHUNK_SIZE", "80"))
    chunk_overlap = int(os.getenv("RAG_CHUNK_OVERLAP", "20"))
    if not 0 <= chunk_overlap < chunk_size:
        raise ValueError("RAG_CHUNK_OVERLAP debe ser mayor o igual a 0 y menor que RAG_CHUNK_SIZE.")

    return RAGSettings(
        data_dir=DATA_DIR,
        index_dir=INDEX_DIR,
        embedding_model=os.getenv(
            "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        ).strip(),
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        top_k=int(os.getenv("RAG_TOP_K", "4")),
        min_score=float(os.getenv("RAG_MIN_SCORE", "0.35")),
    )


@dataclass(frozen=True)
class AccessSettings:
    """Parámetros de identidad, sesión y canal. Ningún secreto va en el código."""

    telegram_token: str
    face_match_threshold: float
    session_minutes: int
    login_max_attempts: int
    login_block_seconds: int
    liveness_timeout_seconds: int


def load_access_settings(require_token: bool = False) -> AccessSettings:
    load_dotenv(find_dotenv(usecwd=True))
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if require_token and not token:
        raise ValueError("Falta TELEGRAM_BOT_TOKEN en el archivo .env (se obtiene con @BotFather).")
    return AccessSettings(
        telegram_token=token,
        face_match_threshold=float(os.getenv("FACE_MATCH_THRESHOLD", "0.363")),
        session_minutes=int(os.getenv("SESSION_MINUTES", "10")),
        login_max_attempts=int(os.getenv("LOGIN_MAX_ATTEMPTS", "3")),
        login_block_seconds=int(os.getenv("LOGIN_BLOCK_SECONDS", "300")),
        liveness_timeout_seconds=int(os.getenv("LIVENESS_TIMEOUT_SECONDS", "60")),
    )
