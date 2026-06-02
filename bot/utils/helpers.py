import random
import string
import io
import qrcode
from datetime import datetime
from typing import Optional, Dict, Any
import pytz


def generate_referral_code(length: int = 8) -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


def generate_request_id() -> str:
    return f"#{random.randint(10000, 99999)}"


def format_balance(amount: float) -> str:
    return f"₹{amount:.2f}"


def format_datetime(dt: datetime) -> str:
    if dt is None:
        return "N/A"
    ist = pytz.timezone("Asia/Kolkata")
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    local_dt = dt.astimezone(ist)
    return local_dt.strftime("%d %b %Y, %I:%M %p IST")


def generate_upi_qr(upi_id: str, name: str, amount: float, txn_note: str = "Deposit") -> bytes:
    upi_url = f"upi://pay?pa={upi_id}&pn={name}&am={amount:.2f}&tn={txn_note}&cu=INR"
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(upi_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def extract_otp_from_message(text: str) -> Optional[str]:
    import re
    patterns = [
        r'Login code[:\s]+(\d{5})',
        r'verification code[:\s]+(\d{5})',
        r'code[:\s]+(\d{5})',
        r'(\d{5})\s*-\s*telegram',
        r'\b(\d{5})\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    all_nums = re.findall(r'\b\d{5}\b', text)
    if all_nums:
        return all_nums[0]
    return None


def is_owner(user_id: int) -> bool:
    """Owner = first admin in ADMIN_IDS env var (hardcoded, highest privilege)"""
    from bot.config import ADMIN_IDS
    return len(ADMIN_IDS) > 0 and user_id == ADMIN_IDS[0]


def is_admin(user_id: int) -> bool:
    """Sync check: config-level admins only (owners). Use is_any_admin() for DB admins too."""
    from bot.config import ADMIN_IDS
    return user_id in ADMIN_IDS


async def is_any_admin(user_id: int) -> bool:
    """Async check: config admins OR DB-added admins"""
    from bot.config import ADMIN_IDS
    if user_id in ADMIN_IDS:
        return True
    try:
        from bot.database import get_db
        db = get_db()
        if db is None:
            return False
        admin_doc = await db.bot_admins.find_one({"telegram_id": user_id, "is_active": True})
        return admin_doc is not None
    except Exception:
        return False


async def log_event(user_id: int, event_type: str, data: Dict[str, Any] = None):
    try:
        from bot.database import get_db
        db = get_db()
        if db is None:
            return
        await db.data_logs.insert_one({
            "user_id": user_id,
            "event_type": event_type,
            "data": data or {},
            "created_at": datetime.utcnow(),
        })
    except Exception:
        pass
