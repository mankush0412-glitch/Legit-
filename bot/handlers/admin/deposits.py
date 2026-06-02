from aiogram import Router, F
from aiogram.types import CallbackQuery
from bson import ObjectId
from datetime import datetime

from bot.database import get_db
from bot.keyboards.admin import admin_back_kb, deposit_approve_kb
from bot.services.wallet_service import add_balance, apply_referral_deposit_bonus
from bot.utils.helpers import is_any_admin, format_datetime
from bot.utils.helpers import log_event

router = Router()


@router.callback_query(F.data == "admin_pending_deposits")
async def cb_pending_deposits(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return

    db = get_db()
    deposits = await db.deposits.find({"status": "pending"}).sort("created_at", 1).to_list(20)

    if not deposits:
        await callback.message.edit_text(
            "✅ *No Pending Deposits!*\n\n_All deposits have been processed._",
            reply_markup=admin_back_kb(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        f"💳 *Pending Deposits: {len(deposits)}*\nReviewing below...",
        reply_markup=admin_back_kb(),
        parse_mode="Markdown"
    )

    for dep in deposits:
        user = await db.users.find_one({"telegram_id": dep["user_id"]})
        username = f"@{user['username']}" if user and user.get("username") else f"ID: {dep['user_id']}"
        method = "📱 UPI" if dep.get("method") == "upi" else "💎 USDT"
        utr = dep.get("utr", "N/A")
        text = (
            f"💳 *Deposit Request*\n\n"
            f"👤 *User:* {username} (`{dep['user_id']}`)\n"
            f"💰 *Amount:* `₹{dep['amount']:.2f}`\n"
            f"💳 *Method:* {method}\n"
            f"🆔 *Request ID:* `{dep.get('request_id', 'N/A')}`\n"
            f"📄 *UTR/TxHash:* `{utr}`\n"
            f"⏰ *Time:* {format_datetime(dep.get('created_at'))}"
        )
        try:
            await callback.message.answer(
                text,
                reply_markup=deposit_approve_kb(str(dep["_id"]), dep["user_id"]),
                parse_mode="Markdown"
            )
        except Exception:
            pass

    await callback.answer()


@router.callback_query(F.data.startswith("approve_deposit:"))
async def cb_approve_deposit(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return

    deposit_id = callback.data.split(":")[1]
    db = get_db()

    deposit = await db.deposits.find_one_and_update(
        {"_id": ObjectId(deposit_id), "status": "pending"},
        {"$set": {
            "status": "approved",
            "verified_at": datetime.utcnow(),
            "verified_by": callback.from_user.id
        }},
        return_document=True
    )

    if not deposit:
        await callback.answer("❌ Already processed.", show_alert=True)
        return

    user_id = deposit["user_id"]
    amount = deposit["amount"]
    new_balance = await add_balance(user_id, amount, reason=f"manual_deposit_{deposit.get('request_id', '')}")
    await apply_referral_deposit_bonus(user_id, amount)
    await log_event(user_id, "deposit_approved_manual", {"amount": amount, "by": callback.from_user.id})

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.edit_text(
            callback.message.text + f"\n\n✅ *APPROVED* by admin",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    try:
        await callback.bot.send_message(
            user_id,
            f"✅ *Deposit Approved!*\n\n"
            f"💰 `₹{amount:.2f}` added to your wallet!\n"
            f"💎 New Balance: `₹{new_balance:.2f}`\n"
            f"🆔 Request ID: `{deposit.get('request_id', 'N/A')}`",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    await callback.answer(f"✅ Approved ₹{amount:.2f} for {user_id}")


@router.callback_query(F.data.startswith("reject_deposit:"))
async def cb_reject_deposit(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return

    deposit_id = callback.data.split(":")[1]
    db = get_db()

    deposit = await db.deposits.find_one_and_update(
        {"_id": ObjectId(deposit_id), "status": "pending"},
        {"$set": {
            "status": "rejected",
            "verified_at": datetime.utcnow(),
            "verified_by": callback.from_user.id
        }},
        return_document=True
    )

    if not deposit:
        await callback.answer("❌ Already processed.", show_alert=True)
        return

    await log_event(deposit["user_id"], "deposit_rejected", {"amount": deposit.get("amount"), "by": callback.from_user.id})

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.edit_text(
            callback.message.text + f"\n\n❌ *REJECTED* by admin",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    try:
        await callback.bot.send_message(
            deposit["user_id"],
            f"❌ *Deposit Rejected*\n\n"
            f"Your deposit of `₹{deposit['amount']:.2f}` was rejected.\n"
            f"🆔 Request ID: `{deposit.get('request_id', 'N/A')}`\n\n"
            f"Contact support if you think this is wrong.",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    await callback.answer("❌ Deposit rejected.")
