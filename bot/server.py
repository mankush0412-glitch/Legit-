import asyncio
import logging
import aiohttp
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

from bot.config import PORT, RENDER_EXTERNAL_URL, SELF_PING_URL

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
    ping_url = SELF_PING_URL or f"{RENDER_EXTERNAL_URL}/health"
    if not ping_url or ping_url == "/health":
        logger.info("[Keep-Alive] No RENDER_EXTERNAL_URL set, self-ping disabled.")
        return

    logger.info(f"[Keep-Alive] Starting self-ping to: {ping_url}")
    while True:
        try:
            await asyncio.sleep(840)
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
