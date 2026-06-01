from bot.database import get_db
from bot.utils.helpers import log_event
from datetime import datetime


async def get_balance(user_id: int) -> float:
    db = get_db()
    user = await db.users.find_one({"telegram_id": user_id})
    if not user:
        return 0.0
    return float(user.get("balance", 0.0))


async def add_balance(user_id: int, amount: float, reason: str = "") -> float:
    db = get_db()
    result = await db.users.find_one_and_update(
        {"telegram_id": user_id},
        {"$inc": {"balance": amount}},
        return_document=True
    )
    await db.transactions.insert_one({
        "user_id": user_id,
        "type": "credit",
        "amount": amount,
        "reason": reason,
        "created_at": datetime.utcnow()
    })
    await log_event(user_id, "balance_credit", {"amount": amount, "reason": reason})
    return float(result.get("balance", 0.0)) if result else 0.0


async def deduct_balance(user_id: int, amount: float) -> bool:
    db = get_db()
    user = await db.users.find_one({"telegram_id": user_id})
    if not user or float(user.get("balance", 0.0)) < amount:
        return False
    await db.users.update_one(
        {"telegram_id": user_id},
        {"$inc": {"balance": -amount}}
    )
    await db.transactions.insert_one({
        "user_id": user_id,
        "type": "debit",
        "amount": amount,
        "reason": "account_purchase",
        "created_at": datetime.utcnow()
    })
    await log_event(user_id, "balance_debit", {"amount": amount})
    return True


async def get_or_create_user(telegram_id: int, username: str = None, first_name: str = None) -> dict:
    from bot.utils.helpers import generate_referral_code
    db = get_db()
    user = await db.users.find_one({"telegram_id": telegram_id})
    if user:
        await db.users.update_one(
            {"telegram_id": telegram_id},
            {"$set": {
                "username": username,
                "first_name": first_name,
                "last_seen": datetime.utcnow()
            }}
        )
        return user

    while True:
        code = generate_referral_code()
        exists = await db.users.find_one({"referral_code": code})
        if not exists:
            break

    new_user = {
        "telegram_id": telegram_id,
        "username": username,
        "first_name": first_name,
        "balance": 0.0,
        "referral_code": code,
        "referred_by": None,
        "referral_earnings": 0.0,
        "total_spent": 0.0,
        "total_purchases": 0,
        "joined_at": datetime.utcnow(),
        "last_seen": datetime.utcnow(),
        "is_banned": False,
    }
    await db.users.insert_one(new_user)
    await log_event(telegram_id, "user_joined", {"username": username, "first_name": first_name})
    return new_user


async def apply_referral(new_user_id: int, referral_code: str) -> bool:
    from bot.services.settings_service import get_setting
    db = get_db()
    referrer = await db.users.find_one({"referral_code": referral_code})
    if not referrer or referrer["telegram_id"] == new_user_id:
        return False
    user = await db.users.find_one({"telegram_id": new_user_id})
    if user and user.get("referred_by"):
        return False

    referral_bonus = await get_setting("referral_bonus", 10.0)

    await db.users.update_one(
        {"telegram_id": new_user_id},
        {"$set": {"referred_by": referrer["telegram_id"]}}
    )
    await add_balance(referrer["telegram_id"], referral_bonus, reason=f"referral_join_bonus_{new_user_id}")
    await db.users.update_one(
        {"telegram_id": referrer["telegram_id"]},
        {"$inc": {"referral_earnings": referral_bonus}}
    )
    await log_event(referrer["telegram_id"], "referral_bonus", {"new_user": new_user_id, "bonus": referral_bonus})
    return True


async def apply_referral_deposit_bonus(user_id: int, deposit_amount: float):
    """Pay referrer a % of the depositor's deposit amount."""
    from bot.services.settings_service import get_setting
    db = get_db()
    user = await db.users.find_one({"telegram_id": user_id})
    if not user or not user.get("referred_by"):
        return

    referral_percent = await get_setting("referral_percent", 3.0)
    referrer_id = user["referred_by"]
    bonus = deposit_amount * (referral_percent / 100.0)
    if bonus < 0.01:
        return

    await add_balance(referrer_id, bonus, reason=f"referral_deposit_bonus_{user_id}_{deposit_amount:.0f}")
    await db.users.update_one(
        {"telegram_id": referrer_id},
        {"$inc": {"referral_earnings": bonus}}
    )
    await log_event(referrer_id, "referral_deposit_bonus", {
        "from_user": user_id,
        "deposit_amount": deposit_amount,
        "bonus": bonus,
        "percent": referral_percent,
    })
