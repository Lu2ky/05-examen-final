"""RAG: recuperar fragmentos relevantes y usarlos como contexto para el LLM.

Pipeline de consulta (online), en cada pregunta:
    pregunta → embedding → búsqueda en el vector store → contexto → prompt → LLM → respuesta

CourseRAG no sabe nada de la consola: recibe una pregunta (y el historial) y devuelve
la respuesta junto con sus fuentes. Por eso otro programa puede reutilizarlo como una
capacidad más.
"""

from dataclasses import dataclass

from asistente.rag.embeddings import Embedder
from asistente.llm.llm_client import LLMClient, LLMResponse, Message
from asistente.llm.prompts import build_rag_messages
from asistente.rag.vector_store import SearchResult, VectorStore

NO_CONTEXT = "(No se encontraron fragmentos relevantes en los documentos del curso.)"
# Solo un hecho booleano: existe información restringida relacionada. Nunca su contenido.
AVISO_RESTRINGIDO = (
    "[Aviso del sistema] Hay además información relacionada que requiere iniciar sesión con un rol "
    "autorizado. Responde con los fragmentos anteriores lo que puedas. Si lo que se pregunta NO está "
    "en ellos, di que esa información requiere iniciar sesión (/login) o que su rol no tiene acceso, "
    "sin inventar ni insinuar su contenido."
)


@dataclass
class RAGAnswer:
    text: str
    sources: list[SearchResult]  # fragmentos recuperados y enviados al LLM
    messages: list[Message]  # lo que realmente recibió el LLM
    response: LLMResponse


def format_context(results: list[SearchResult], restringido_oculto: bool = False) -> str:
    """Numera los fragmentos para que el LLM pueda citarlos: "[1] (evaluacion.md) texto"."""
    texto = (
        "\n\n".join(f"[{i}] ({result.chunk.source}) {result.chunk.text}" for i, result in enumerate(results, 1))
        if results
        else NO_CONTEXT
    )
    return f"{texto}\n\n{AVISO_RESTRINGIDO}" if restringido_oculto else texto


class CourseRAG:
    def __init__(
        self,
        llm: LLMClient,
        embedder: Embedder,
        store: VectorStore,
        top_k: int,
        min_score: float,
    ):
        self.llm = llm
        self.embedder = embedder
        self.store = store
        self.top_k = top_k
        self.min_score = min_score

    def retrieve(self, question: str, niveles: set[str]) -> tuple[list[SearchResult], bool]:
        """Recupera SOLO fragmentos de `niveles` (el filtro ocurre antes del top-k).

        Devuelve (fragmentos permitidos, ¿había algo restringido relacionado?). El segundo valor
        es un booleano calculado por el programa; el contenido restringido nunca sale de aquí.
        """
        query_vector = self.embedder.embed_query(question)
        permitidos = [r for r in self.store.search(query_vector, self.top_k, niveles) if r.score >= self.min_score]
        todos = self.store.search(query_vector, self.top_k)
        oculto = any(r.score >= self.min_score and r.chunk.nivel not in niveles for r in todos)
        return permitidos, oculto

    def answer(self, question: str, history: list[Message] | None, niveles: set[str]) -> RAGAnswer:
        sources, oculto = self.retrieve(question, niveles)
        messages = build_rag_messages(history or [], question, format_context(sources, oculto))
        response = self.llm.chat(messages)
        return RAGAnswer(text=response.text, sources=sources, messages=messages, response=response)
