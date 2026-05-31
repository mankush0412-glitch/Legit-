import asyncio
import logging
import aiohttp
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

from bot.config import PORT

logger = logging.getLogger(__name__)

app = FastAPI(title="Legit Stocks Bot", docs_url=None, redoc_url=None)


@app.get("/")
async def root():
    return {"status": "alive", "bot": "Legit Stocks Bot", "version": "2.0"}


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "alive": True})


@app.get("/ping")
async def ping():
    return {"pong": True}


async def self_ping_task():
    while True:
        try:
            await asyncio.sleep(840)
            from bot.services.settings_service import get_setting
            ping_url = await get_setting("self_ping_url", "")
            if not ping_url:
                continue
            async with aiohttp.ClientSession() as session:
                async with session.get(ping_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    logger.info(f"[Keep-Alive] Ping → {resp.status}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[Keep-Alive] Ping failed: {e}")


async def run_server():
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=PORT,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()
