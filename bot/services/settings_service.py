from datetime import datetime, timedelta
from typing import Any, Optional

_settings_cache: dict = {}
_cache_expiry: Optional[datetime] = None
_CACHE_TTL = 60  # seconds


async def _load_settings() -> dict:
    global _settings_cache, _cache_expiry
    now = datetime.utcnow()
    if _cache_expiry and now < _cache_expiry and _settings_cache:
        return _settings_cache

    from bot.database import get_db
    db = get_db()
    if db is None:
        return _settings_cache

    settings = {}
    async for doc in db.settings.find({}):
        settings[doc["key"]] = doc["value"]

    _settings_cache = settings
    _cache_expiry = now + timedelta(seconds=_CACHE_TTL)
    return settings


def _invalidate_cache():
    global _settings_cache, _cache_expiry
    _settings_cache = {}
    _cache_expiry = None


async def get_setting(key: str, default: Any = None) -> Any:
    settings = await _load_settings()
    return settings.get(key, default)


async def set_setting(key: str, value: Any) -> None:
    from bot.database import get_db
    from datetime import datetime
    db = get_db()
    await db.settings.update_one(
        {"key": key},
        {"$set": {"key": key, "value": value, "updated_at": datetime.utcnow()}},
        upsert=True,
    )
    _invalidate_cache()


async def get_all_admin_ids() -> list:
    """Returns owner ID + all active DB admins."""
    from bot.config import OWNER_ID
    from bot.database import get_db
    ids = [OWNER_ID] if OWNER_ID else []
    try:
        db = get_db()
        if db:
            async for a in db.bot_admins.find({"is_active": True}):
                if a["telegram_id"] not in ids:
                    ids.append(a["telegram_id"])
    except Exception:
        pass
    return ids
