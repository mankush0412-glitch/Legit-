from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from bot.database import get_db
from bot.keyboards.main_menu import back_to_main_kb
from bot.keyboards.buy import otp_received_kb

router = Router()

STATUS_LABEL = {
    "waiting_otp": "⏳ Waiting OTP",
    "otp_received": "✅ OTP Received",
    "completed": "✅ Completed",
    "cancelled": "❌ Cancelled",
    "failed_timeout": "⏱️ Timed Out (Refunded)",
    "failed_expired": "🔴 Session Expired (Refunded)",
    "failed_error": "❌ Error (Refunded)",
}


@router.callback_query(F.data == "my_sessions")
async def cb_my_sessions(callback: CallbackQuery):
    user_id = callback.from_user.id
    db = get_db()

    purchases = await db.purchases.find(
        {"user_id": user_id}
    ).sort("created_at", -1).limit(8).to_list(8)

    if not purchases:
        text = (
            "📋 *My Orders*\n\n"
            "_No orders yet._\n\n"
            "🛒 Purchase an account to get started."
        )
        await callback.message.edit_text(text, reply_markup=back_to_main_kb(), parse_mode="Markdown")
        await callback.answer()
        return

    lines = ["📋 *My Orders — Last 8*\n"]

    for i, p in enumerate(purchases, 1):
        status = p.get("status", "")
        label = STATUS_LABEL.get(status, status.replace("_", " ").title())
        otp = p.get("otp")
        password = p.get("two_fa_password", "")

        block = (
            f"*{i}.* {p.get('country_flag', '')} *{p.get('country', 'N/A')}*  |  {label}\n"
            f"📱 Number: `{p.get('phone_number', 'N/A')}`\n"
            f"💰 Paid: `₹{p.get('amount', 0):.2f}`"
        )
        if otp:
            block += f"\n💬 OTP: `{otp}`"
        if password:
            block += f"\n🔐 2FA: `{password}`"

        lines.append(block)

    text = "\n\n".join(lines)

    # If latest purchase is still waiting for OTP, show Get OTP button too
    latest = purchases[0] if purchases else None
    if latest and latest.get("status") in ("waiting_otp", "otp_received"):
        purchase_id = str(latest["_id"])
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬  Get Latest OTP  ", callback_data=f"get_otp_again:{purchase_id}")],
            [InlineKeyboardButton(text="🏠  Main Menu  ", callback_data="main_menu")],
        ])
    else:
        kb = back_to_main_kb()

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()
