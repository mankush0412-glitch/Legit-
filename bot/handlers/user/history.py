from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.database import get_db
from bot.keyboards.main_menu import back_to_main_kb
from bot.utils.helpers import format_datetime

router = Router()

STATUS_EMOJI = {
    "waiting_otp": "⏳",
    "otp_received": "✅",
    "completed": "✅",
    "cancelled": "❌",
}

DEPOSIT_EMOJI = {
    "pending": "⏳",
    "approved": "✅",
    "rejected": "❌",
}


@router.callback_query(F.data == "history")
async def cb_history(callback: CallbackQuery):
    user_id = callback.from_user.id
    db = get_db()

    purchases = await db.purchases.find(
        {"user_id": user_id}
    ).sort("created_at", -1).limit(8).to_list(8)

    deposits = await db.deposits.find(
        {"user_id": user_id}
    ).sort("created_at", -1).limit(5).to_list(5)

    total_spent = sum(p.get("amount", 0) for p in purchases if p.get("status") != "cancelled")
    total_deposited = sum(d.get("amount", 0) for d in deposits if d.get("status") == "approved")

    lines = [
        "📋 *History & Stats*",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💸 Total Spent: `₹{total_spent:.2f}`",
        f"💰 Total Deposited: `₹{total_deposited:.2f}`",
    ]

    if purchases:
        lines.append("\n🛒 *Recent Purchases:*")
        for p in purchases:
            emoji = STATUS_EMOJI.get(p.get("status", ""), "•")
            status_label = p.get("status", "").replace("_", " ").title()
            lines.append(
                f"{emoji} {p.get('country_flag', '')} *{p.get('country', 'N/A')}* — `₹{p.get('amount', 0):.2f}`\n"
                f"   📱 `{p.get('phone_number', 'N/A')}`  •  {status_label}"
            )
    else:
        lines.append("\n🛒 _No purchases yet._")

    if deposits:
        lines.append("\n💰 *Recent Deposits:*")
        for d in deposits:
            emoji = DEPOSIT_EMOJI.get(d.get("status", ""), "•")
            method = "UPI" if d.get("method") == "upi" else "Crypto"
            lines.append(
                f"{emoji} {method}: `₹{d.get('amount', 0):.2f}` — {d.get('status', '').title()}\n"
                f"   🆔 {d.get('request_id', 'N/A')}"
            )
    else:
        lines.append("\n💰 _No deposits yet._")

    text = "\n".join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=back_to_main_kb(), parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text, reply_markup=back_to_main_kb(), parse_mode="Markdown")
    await callback.answer()
