import os
from typing import List
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: List[int] = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME: str = os.getenv("DB_NAME", "legit_stocks_bot")
TELEGRAM_API_ID: int = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH: str = os.getenv("TELEGRAM_API_HASH", "")

BOT_NAME: str = os.getenv("BOT_NAME", "Legit Stocks Bot")
SUPPORT_USERNAME: str = os.getenv("SUPPORT_USERNAME", "")

REFERRAL_PERCENT: float = float(os.getenv("REFERRAL_PERCENT", "3.0"))
REFERRAL_BONUS: float = float(os.getenv("REFERRAL_BONUS", "10.0"))

UPI_ID: str = os.getenv("UPI_ID", "")
UPI_NAME: str = os.getenv("UPI_NAME", "")
USDT_ADDRESS: str = os.getenv("USDT_ADDRESS", "")
USDT_NETWORK: str = os.getenv("USDT_NETWORK", "TRC20")

AUTO_APPROVE_UPI: bool = os.getenv("AUTO_APPROVE_UPI", "true").lower() == "true"
AUTO_APPROVE_CRYPTO: bool = os.getenv("AUTO_APPROVE_CRYPTO", "true").lower() == "true"

PORT: int = int(os.getenv("PORT", "8080"))
RENDER_EXTERNAL_URL: str = os.getenv("RENDER_EXTERNAL_URL", "")
SELF_PING_URL: str = os.getenv("SELF_PING_URL", "")

SESSION_TIMEOUT: int = 300
CRYPTO_EXCHANGE_RATE: float = float(os.getenv("CRYPTO_EXCHANGE_RATE", "83.0"))

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
