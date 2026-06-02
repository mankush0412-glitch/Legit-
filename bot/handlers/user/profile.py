from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from bot.database import get_db
from bot.utils.helpers import format_datetime
from bot.config import REFERRAL_PERCENT

router = Router()


@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery, db_user: dict = None):
    if not db_user:
        await callback.answer("User not found.", show_alert=True)
        return

    user_id = callback.from_user.id
    db = get_db()

    balance = float(db_user.get("balance", 0.0))
    total_spent = float(db_user.get("total_spent", 0.0))
    referral_code = db_user.get("referral_code", "N/A")
    referred_count = await db.users.count_documents({"referred_by": user_id})

    total_deposited_result = await db.deposits.aggregate([
        {"$match": {"user_id": user_id, "status": "approved"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]).to_list(1)
    total_deposited = total_deposited_result[0]["total"] if total_deposited_result else 0.0

    bot_info = await callback.bot.get_me()
    bot_username = bot_info.username
    ref_link = f"https://t.me/{bot_username}?start=ref_{referral_code}"

    name = callback.from_user.first_name or "User"

    text = (
        f"👤 *User Profile*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 ID: `{user_id}`\n"
        f"👤 Name: *{name}*\n"
        f"💎 Balance: `₹{balance:.2f}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Statistics*\n"
        f"💰 Total Deposited: `₹{total_deposited:.2f}`\n"
        f"🛒 Total Spent: `₹{total_spent:.2f}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 *Referral Link*\n"
        f"`{ref_link}`\n\n"
        f"🎁 Earn *{REFERRAL_PERCENT:.1f}%* bonus on every deposit your referrals make!\n"
        f"👥 Total Referred: *{referred_count}*"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Add Funds", callback_data="deposit"),
            InlineKeyboardButton(text="🛒 Buy Account", callback_data="buy_account"),
        ],
        [
            InlineKeyboardButton(text="📦 Buy Sessions", callback_data="get_sessions"),
            InlineKeyboardButton(text="🆘 Support", callback_data="support"),
        ],
        [InlineKeyboardButton(text="◀️ Back to Menu", callback_data="main_menu")],
    ])

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()
