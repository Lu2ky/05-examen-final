# Asistente del Curso en Telegram con reconocimiento facial

Examen final de Fundamentos de IA. El documento de entrega está en [`ENTREGA.md`](ENTREGA.md).

## Estructura

```
asistente/            código de la aplicación (paquete)
  config.py           configuración y rutas
  llm/                cliente del LLM y prompts
  rag/                documentos, embeddings, almacén vectorial y RAG con filtro por nivel
  agente/             agente, router, orquestador, tools por rol y núcleo sin Telegram
  mcp_academico/      servidor MCP del sistema académico y su cliente
  seguridad/          política de acceso, sesiones y auditoría
  biometria/          detección y embeddings de rostro, prueba de vida y verificación 1:1
  canal/              adaptador de Telegram
data/                 documentos por nivel, usuarios, sistema académico y casos de ataque
tests/                tests del núcleo y de la prueba de vida
bot.py                arranca el bot
ingest.py             genera el índice del RAG
enroll.py             enrola el rostro de un usuario
umbral.py             calcula la tabla FAR/FRR
pruebas_seguridad.py  suite de ataques
```

## Uso

```
uv sync
cp .env.example .env              # completar LLM_API_KEY, LLM_MODEL y TELEGRAM_BOT_TOKEN
uv run python ingest.py           # índice del RAG
uv run python enroll.py --id integrante_1 --telegram-id <id>
uv run python bot.py
uv run pytest
uv run python pruebas_seguridad.py
uv run python umbral.py
```

Los modelos ONNX de rostro (YuNet y SFace) van en `modelos/`. Las carpetas `modelos/`, `rostros/`, `fotos/`,
`videos/` e `index/`, el `.env` y `auditoria*.jsonl` no se versionan.
