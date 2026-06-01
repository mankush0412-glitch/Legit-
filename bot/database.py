from motor.motor_asyncio import AsyncIOMotorClient
from bot.config import MONGO_URI, DB_NAME, DEFAULT_COUNTRIES

client: AsyncIOMotorClient = None
db = None

DEFAULT_SETTINGS = {
    "bot_name": "Legit Stocks Bot",
    "support_username": "",
    "upi_id": "",
    "upi_name": "",
    "usdt_address": "",
    "usdt_network": "TRC20",
    "auto_approve_upi": True,
    "auto_approve_crypto": True,
    "crypto_exchange_rate": 83.0,
    "referral_bonus": 10.0,
    "referral_percent": 3.0,
    "self_ping_url": "",
}


async def connect_db():
    global client, db
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    await init_indexes()
    await init_default_countries()
    await init_default_settings()
    print(f"[DB] Connected to MongoDB: {DB_NAME}")


async def close_db():
    global client
    if client:
        client.close()


async def init_indexes():
    await db.users.create_index("telegram_id", unique=True)
    await db.users.create_index("referral_code", unique=True)
    await db.sessions.create_index([("country_code", 1), ("is_available", 1)])
    await db.deposits.create_index("user_id")
    await db.purchases.create_index("user_id")
    await db.countries.create_index("code", unique=True)
    await db.settings.create_index("key", unique=True)
    await db.data_logs.create_index("user_id")
    await db.data_logs.create_index("event_type")
    await db.data_logs.create_index("created_at")


async def init_default_countries():
    for country in DEFAULT_COUNTRIES:
        existing = await db.countries.find_one({"code": country["code"]})
        if not existing:
            await db.countries.insert_one({
                "code": country["code"],
                "name": country["name"],
                "flag": country["flag"],
                "price": country["price"],
                "is_active": True,
            })


async def init_default_settings():
    for key, value in DEFAULT_SETTINGS.items():
        existing = await db.settings.find_one({"key": key})
        if not existing:
            await db.settings.insert_one({"key": key, "value": value})


def get_db():
    return db
