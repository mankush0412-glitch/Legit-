from motor.motor_asyncio import AsyncIOMotorClient
from bot.config import MONGO_URI, DB_NAME, DEFAULT_COUNTRIES

client: AsyncIOMotorClient = None
db = None


async def connect_db():
    global client, db
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    await init_indexes()
    await init_default_countries()
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


def get_db():
    return db
