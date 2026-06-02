import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import BOT_TOKEN, BOT_NAME
from bot.database import connect_db, close_db
from bot.middlewares.user_middleware import UserMiddleware
from bot.server import run_server, self_ping_task

from bot.handlers.user.start import router as start_router
from bot.handlers.user.buy import router as buy_router
from bot.handlers.user.deposit import router as deposit_router
from bot.handlers.user.profile import router as profile_router
from bot.handlers.user.history import router as history_router
from bot.handlers.user.referral import router as referral_router
from bot.handlers.user.support import router as support_router
from bot.handlers.user.sessions_handler import router as sessions_router
from bot.handlers.user.bulk_sessions import router as bulk_sessions_router
from bot.handlers.user.load_session import router as load_session_router

from bot.handlers.admin.panel import router as admin_panel_router
from bot.handlers.admin.sessions_mgmt import router as sessions_mgmt_router
from bot.handlers.admin.deposits import router as deposits_admin_router
from bot.handlers.admin.users import router as users_admin_router
from bot.handlers.admin.backup import router as backup_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def run_bot():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set!")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )

    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    dp.message.middleware(UserMiddleware())
    dp.callback_query.middleware(UserMiddleware())

    dp.include_router(start_router)
    dp.include_router(buy_router)
    dp.include_router(deposit_router)
    dp.include_router(profile_router)
    dp.include_router(history_router)
    dp.include_router(referral_router)
    dp.include_router(support_router)
    dp.include_router(sessions_router)
    dp.include_router(bulk_sessions_router)
    dp.include_router(load_session_router)

    dp.include_router(admin_panel_router)
    dp.include_router(sessions_mgmt_router)
    dp.include_router(deposits_admin_router)
    dp.include_router(users_admin_router)
    dp.include_router(backup_router)

    logger.info(f"🤖 {BOT_NAME} starting...")

    # ── Load all sessions into pool on startup ──────────────────
    # All available session files are connected via Telethon and kept
    # in memory so OTP delivery is instant and reliable.
    try:
        from bot.services.session_service import session_pool
        logger.info("[Pool] Connecting all sessions from DB...")
        await session_pool.load_all_from_db()
        stats = session_pool.get_stats()
        total_live = session_pool.total
        logger.info(f"[Pool] ✅ {total_live} sessions live. Stats: {stats}")
    except Exception as e:
        logger.error(f"[Pool] Startup load error: {e}")
    # ────────────────────────────────────────────────────────────

    logger.info(f"🤖 {BOT_NAME} ready — polling...")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await close_db()
        await bot.session.close()
        logger.info("Bot stopped.")


async def main():
    await connect_db()
    await asyncio.gather(
        run_bot(),
        run_server(),
        self_ping_task(),
    )


if __name__ == "__main__":
    asyncio.run(main())
