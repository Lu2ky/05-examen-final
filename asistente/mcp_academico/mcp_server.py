"""Servidor MCP "Servicios académicos" (ficticio).

Expone, con el protocolo estándar MCP, datos y acciones del sistema académico:
  - tools (el MODELO decide pedirlas): consultar_notas, consultar_solicitudes, solicitar_supletorio
  - resources (la APLICACIÓN decide leerlos): academico://calendario

Es un programa independiente del asistente: no conoce al LLM, ni al proveedor, ni el
prompt. Cualquier cliente MCP (este asistente, un IDE, n8n, otro agente) puede usarlo.

El SDK genera el JSON Schema de cada tool a partir de los tipos y las descripciones
de la función (compáralo con las definiciones escritas a mano en tools.py).

Normalmente no se ejecuta a mano: mcp_client.py lo lanza como subproceso y le habla
por stdin/stdout (transporte stdio). Para exponerlo por HTTP (Streamable HTTP):
    uv run python labs/04-agent-orchestration/mcp_server.py --http
"""

import json
import os
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

def _archivo_de_datos() -> Path:
    """data/academico.json, o el archivo indicado con --datos <ruta> (los tests usan una copia temporal)."""
    if "--datos" in sys.argv:
        return Path(sys.argv[sys.argv.index("--datos") + 1]).resolve()
    return Path(__file__).resolve().parents[2] / "data" / "academico.json"


DATA_FILE = _archivo_de_datos()
DATA = json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _guardar() -> None:
    """Escribe el sistema académico en disco. Escritura atómica: nunca deja el JSON a medias."""
    temporal = DATA_FILE.with_suffix(".json.tmp")
    temporal.write_text(json.dumps(DATA, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporal, DATA_FILE)
ESTUDIANTES: dict[str, Any] = DATA["estudiantes"]

# Solicitudes creadas en esta ejecución (en memoria: se pierden al cerrar el servidor).
SOLICITUDES: list[dict[str, Any]] = []

CodigoEstudiante = Annotated[str, Field(description="Código del estudiante, p. ej. 2026001")]

# IMPORTANTE: con el transporte stdio, stdout es el canal del protocolo. Un print() normal
# corrompería los mensajes; para depurar usa print(..., file=sys.stderr).
mcp = MCPServer(
    "servicios-academicos",
    instructions="Servicios académicos (ficticios) del curso de Inteligencia Artificial.",
    log_level="WARNING",  # los errores previstos (ToolError) no se imprimen en la consola del chat
)


def buscar_estudiante(codigo: str) -> dict[str, Any]:
    estudiante = ESTUDIANTES.get(codigo.strip())
    if estudiante is None:
        # ToolError = error previsto: el mensaje le llega al cliente (y al LLM) para que pueda corregir.
        raise ToolError(f"No existe un estudiante con código {codigo!r}.")
    return estudiante


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def consultar_notas(codigo: CodigoEstudiante) -> dict[str, Any]:
    """Consulta las notas registradas de un estudiante del curso.

    Una nota null significa que aún no está registrada. Incluye el promedio de los laboratorios.
    """
    codigo = codigo.strip()
    estudiante = buscar_estudiante(codigo)
    notas = estudiante["notas"]
    laboratorios = notas["laboratorios"]
    return {
        "codigo": codigo,
        "nombre": estudiante["nombre"],
        "notas": notas,
        "promedio_laboratorios": round(sum(laboratorios) / len(laboratorios), 2) if laboratorios else None,
        "observaciones_docente": estudiante.get("observaciones_docente"),  # el asistente solo la entrega al docente
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def consultar_solicitudes(codigo: CodigoEstudiante) -> list[dict[str, Any]]:
    """Lista las solicitudes de supletorio registradas por un estudiante."""
    codigo = codigo.strip()
    buscar_estudiante(codigo)
    return [solicitud for solicitud in SOLICITUDES if solicitud["codigo"] == codigo]


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
def solicitar_supletorio(
    codigo: CodigoEstudiante,
    parcial: Annotated[Literal[1, 2], Field(description="Número del parcial: 1 o 2")],
    causa: Annotated[
        Literal["incapacidad médica", "calamidad doméstica", "representación institucional"],
        Field(description="Causa justificada de la inasistencia"),
    ],
) -> dict[str, Any]:
    """Registra una solicitud de supletorio para un parcial al que el estudiante no asistió.

    Es una ACCIÓN: crea un registro en el sistema académico.
    """
    codigo = codigo.strip()
    estudiante = buscar_estudiante(codigo)
    if any(s["codigo"] == codigo and s["parcial"] == parcial for s in SOLICITUDES):
        raise ToolError(f"Ya existe una solicitud de supletorio del parcial {parcial} para {codigo}.")
    solicitud = {
        "radicado": f"SUP-2026-{len(SOLICITUDES) + 1:03d}",
        "codigo": codigo,
        "nombre": estudiante["nombre"],
        "parcial": parcial,
        "causa": causa,
        "estado": "pendiente: adjuntar el soporte por Teams dentro de los tres días hábiles siguientes al parcial",
    }
    SOLICITUDES.append(solicitud)
    return solicitud


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
def registrar_nota(
    codigo: CodigoEstudiante,
    evaluacion: Annotated[Literal["parcial_1", "parcial_2", "proyecto"], Field(description="Evaluación a registrar")],
    valor: Annotated[float, Field(ge=0.0, le=5.0, description="Nota entre 0.0 y 5.0")],
) -> dict[str, Any]:
    """Registra la nota de una evaluación de un estudiante. Es una ACCIÓN: modifica el sistema académico.

    El control de quién puede llamarla lo hace el asistente (solo el rol docente la recibe).
    """
    codigo = codigo.strip()
    estudiante = buscar_estudiante(codigo)
    anterior = estudiante["notas"][evaluacion]
    estudiante["notas"][evaluacion] = valor
    _guardar()  # persiste en academico.json: la nota sigue ahí tras reiniciar el servidor
    return {"codigo": codigo, "evaluacion": evaluacion, "anterior": anterior, "nueva": valor}


@mcp.resource("academico://calendario", description="Fechas clave del curso (parciales y proyecto final)")
def calendario() -> str:
    return "\n".join(f"{item['fecha']}: {item['evento']}" for item in DATA["calendario"])


if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.run("streamable-http")  # http://127.0.0.1:8000/mcp
    else:
        mcp.run()  # stdio: lo lanza el cliente
