"""Tools por rol. El software arma las tools de cada sesión; el LLM solo recibe las de su rol.

- Estudiante: las tools "mis_*" NO tienen parámetro de código. El código sale de la sesión
  (usuarios.json) y se inyecta aquí, antes de llamar al servidor MCP.
- Docente: consultar_notas / consultar_solicitudes / registrar_nota con código explícito.
- Defensa en profundidad: cada tool vuelve a verificar el rol al EJECUTARSE.
"""

import json
from dataclasses import replace
from typing import Any

from mcp import Client

from asistente.seguridad import auditoria
from asistente.seguridad.acceso import ROL_DOCENTE, ROL_ESTUDIANTE, tools_permitidas
from asistente.mcp_academico.mcp_client import read_resource_text
from asistente.seguridad.sesiones import Sesion
from asistente.agente.tools import LOCAL_TOOLS, Tool, ToolExecutionError

SIN_PARAMETROS = {"type": "object", "properties": {}, "required": []}


def con_verificacion(tool: Tool, sesion: Sesion | None, rol_exigido: str | None) -> Tool:
    """Envuelve una tool: al ejecutarla, comprueba otra vez rol y permiso, y audita el uso restringido."""
    rol = sesion.rol if sesion else "publico"
    user_id = sesion.telegram_user_id if sesion else None

    async def run(arguments: dict[str, Any]) -> str:
        if tool.name not in tools_permitidas(rol) or (rol_exigido is not None and rol != rol_exigido):
            auditoria.registrar("acceso_denegado", user_id, tool=tool.name, rol=rol)
            raise ToolExecutionError("Acción no permitida para tu rol.")
        if rol_exigido is not None:
            auditoria.registrar("tool_restringida", user_id, tool=tool.name, rol=rol)
        return await tool.run(arguments)

    return replace(tool, run=run)


def _sin_observaciones(texto: str) -> str:
    datos = json.loads(texto)
    datos.pop("observaciones_docente", None)
    return json.dumps(datos, ensure_ascii=False)


def _tools_estudiante(mcp_tools: dict[str, Tool], sesion: Sesion) -> list[Tool]:
    codigo = sesion.codigo
    if not codigo:
        return []

    async def mis_notas(_: dict[str, Any]) -> str:
        return _sin_observaciones(await mcp_tools["consultar_notas"].run({"codigo": codigo}))

    async def mis_solicitudes(_: dict[str, Any]) -> str:
        return await mcp_tools["consultar_solicitudes"].run({"codigo": codigo})

    async def supletorio(arguments: dict[str, Any]) -> str:
        # Solo se reenvían parcial y causa: cualquier "codigo" que el modelo añada se ignora.
        return await mcp_tools["solicitar_supletorio"].run(
            {"codigo": codigo, "parcial": arguments.get("parcial"), "causa": arguments.get("causa")}
        )

    parametros_supletorio = {
        k: v
        for k, v in mcp_tools["solicitar_supletorio"].parameters.get("properties", {}).items()
        if k != "codigo"
    }
    return [
        Tool("consultar_mis_notas", "Consulta TUS notas del curso (sin observaciones del docente). No recibe código: "
             "el sistema usa el de tu sesión.", SIN_PARAMETROS, mis_notas, True, "servicios-academicos"),
        Tool("consultar_mis_solicitudes", "Lista TUS solicitudes de supletorio. No recibe código.",
             SIN_PARAMETROS, mis_solicitudes, True, "servicios-academicos"),
        Tool("solicitar_supletorio", "Registra una solicitud de supletorio para TI. ACCIÓN: requiere confirmación.",
             {"type": "object", "properties": parametros_supletorio, "required": ["parcial", "causa"]},
             supletorio, False, "servicios-academicos"),
    ]


def _tool_calendario(client: Client) -> Tool:
    async def run(_: dict[str, Any]) -> str:
        return await read_resource_text(client, "academico://calendario")

    return Tool("consultar_calendario", "Fechas clave del curso (parciales y proyecto final).",
                SIN_PARAMETROS, run, True, "servicios-academicos")


def herramientas_para(sesion: Sesion | None, mcp_client: Client, mcp_tools: list[Tool], rag_tool: Tool) -> list[Tool]:
    """Las tools de este usuario: rol → tools_permitidas, cada una con verificación al ejecutar."""
    por_nombre = {t.name: t for t in mcp_tools}
    rol = sesion.rol if sesion else "publico"
    candidatas: list[tuple[Tool, str | None]] = [(rag_tool, None), (_tool_calendario(mcp_client), None)]
    candidatas += [(t, None) for t in LOCAL_TOOLS]
    if sesion and rol == ROL_ESTUDIANTE:
        candidatas += [(t, ROL_ESTUDIANTE) for t in _tools_estudiante(por_nombre, sesion)]
    if sesion and rol == ROL_DOCENTE:
        candidatas += [(por_nombre[n], ROL_DOCENTE) for n in ("consultar_notas", "consultar_solicitudes", "registrar_nota")]
    permitidas = tools_permitidas(rol)
    return [con_verificacion(t, sesion, exigido) for t, exigido in candidatas if t.name in permitidas]
