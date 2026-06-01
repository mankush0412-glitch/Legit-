from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.database import get_db
from bot.keyboards.main_menu import back_to_main_kb
from bot.keyboards.buy import otp_received_kb

router = Router()


@router.callback_query(F.data == "my_sessions")
async def cb_my_sessions(callback: CallbackQuery):
    user_id = callback.from_user.id
    db = get_db()

    purchases = await db.purchases.find(
        {"user_id": user_id, "status": {"$in": ["otp_received", "completed"]}}
    ).sort("created_at", -1).limit(5).to_list(5)

    if not purchases:
        text = (
            "📋 *My Sessions*\n\n"
            "_No active session OTPs yet._\n\n"
            "🛒 Purchase an account to access session details."
        )
        await callback.message.edit_text(text, reply_markup=back_to_main_kb(), parse_mode="Markdown")
        await callback.answer()
        return

    lines = ["📋 *My Sessions — Recent OTPs*"]
    for i, p in enumerate(purchases, 1):
        otp = p.get("otp", "N/A")
        password = p.get("two_fa_password", "")
        lines.append(
            f"\n*{i}.* {p.get('country_flag', '')} *{p.get('country', 'N/A')}*\n"
            f"📱 Number: `{p.get('phone_number', 'N/A')}`\n"
            f"💬 OTP: `{otp}`"
        )
        if password:
            lines.append(f"🔐 2FA: `{password}`")

    text = "\n".join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=back_to_main_kb(), parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text, reply_markup=back_to_main_kb(), parse_mode="Markdown")
    await callback.answer()
