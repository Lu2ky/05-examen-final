"""Lanzador del bot de Telegram: uv run python bot.py"""

import asyncio

from asistente.canal.bot import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
