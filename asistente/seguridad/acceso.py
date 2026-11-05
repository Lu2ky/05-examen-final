"""Política de acceso: la ÚNICA fuente de verdad de qué puede ver y hacer cada rol.

Lo decide el código, no el LLM. Un rol desconocido se trata como "publico" (falla cerrado).
"""

ROL_PUBLICO = "publico"
ROL_ESTUDIANTE = "estudiante"
ROL_DOCENTE = "docente"

_NIVELES = {
    ROL_PUBLICO: {"publico"},
    ROL_ESTUDIANTE: {"publico", "estudiante"},
    ROL_DOCENTE: {"publico", "estudiante", "docente"},
}

_TOOLS_PUBLICAS = {"buscar_documentos", "fecha_actual", "dias_hasta", "calcular_nota_final", "consultar_calendario"}
_TOOLS = {
    ROL_PUBLICO: _TOOLS_PUBLICAS,
    ROL_ESTUDIANTE: _TOOLS_PUBLICAS | {"consultar_mis_notas", "consultar_mis_solicitudes", "solicitar_supletorio"},
    ROL_DOCENTE: _TOOLS_PUBLICAS | {"consultar_notas", "consultar_solicitudes", "registrar_nota"},
}


def niveles_permitidos(rol: str) -> set[str]:
    return set(_NIVELES.get(rol, _NIVELES[ROL_PUBLICO]))


def tools_permitidas(rol: str) -> set[str]:
    return set(_TOOLS.get(rol, _TOOLS[ROL_PUBLICO]))
