import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
OWNER_ID: int = int(os.getenv("OWNER_ID", "0"))
MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME: str = os.getenv("DB_NAME", "legit_stocks_bot")
TELEGRAM_API_ID: int = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH: str = os.getenv("TELEGRAM_API_HASH", "")
PORT: int = int(os.getenv("PORT", "8080"))

# Owner is always treated as the primary admin
ADMIN_IDS = [OWNER_ID] if OWNER_ID else []

SESSION_TIMEOUT: int = 300

DEFAULT_COUNTRIES = [
    {"code": "IN", "name": "India", "flag": "🇮🇳", "price": 30.0},
    {"code": "BD", "name": "Bangladesh", "flag": "🇧🇩", "price": 28.0},
    {"code": "PK", "name": "Pakistan", "flag": "🇵🇰", "price": 25.0},
    {"code": "NG", "name": "Nigeria", "flag": "🇳🇬", "price": 20.0},
    {"code": "ID", "name": "Indonesia", "flag": "🇮🇩", "price": 28.0},
    {"code": "US", "name": "USA", "flag": "🇺🇸", "price": 50.0},
    {"code": "VN", "name": "Vietnam", "flag": "🇻🇳", "price": 22.0},
    {"code": "MY", "name": "Myanmar", "flag": "🇲🇲", "price": 20.0},
    {"code": "KE", "name": "Kenya", "flag": "🇰🇪", "price": 22.0},
    {"code": "CO", "name": "Colombia", "flag": "🇨🇴", "price": 25.0},
    {"code": "ZW", "name": "Zimbabwe", "flag": "🇿🇼", "price": 18.0},
]
