import json
import io
from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, BufferedInputFile

from bot.database import get_db
from bot.keyboards.admin import admin_back_kb
from bot.utils.helpers import is_any_admin

router = Router()


def _serialize(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, '__str__'):
        return str(obj)
    return obj


def _clean_doc(doc: dict) -> dict:
    result = {}
    for k, v in doc.items():
        if k == "session_data":
            result[k] = "<binary session data — not exported>"
        elif isinstance(v, bytes):
            result[k] = "<binary>"
        elif isinstance(v, dict):
            result[k] = _clean_doc(v)
        elif isinstance(v, list):
            result[k] = [_clean_doc(i) if isinstance(i, dict) else i for i in v]
        else:
            result[k] = _serialize(v)
    return result


@router.callback_query(F.data == "admin_backup")
async def cb_admin_backup(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return

    await callback.answer("⏳ Generating backup...", show_alert=False)
    processing_msg = await callback.message.answer(
        "⏳ *Generating full data backup...*\n\n"
        "Exporting: users, deposits, purchases, transactions, data logs...",
        parse_mode="Markdown"
    )

    db = get_db()

    backup_data = {
        "bot_name": "Legit Stocks Bot",
        "exported_at": datetime.utcnow().isoformat(),
        "exported_by": callback.from_user.id,
        "users": [],
        "deposits": [],
        "purchases": [],
        "transactions": [],
        "countries": [],
        "data_logs": [],
    }

    async for doc in db.users.find({}):
        backup_data["users"].append(_clean_doc(doc))

    async for doc in db.deposits.find({}):
        backup_data["deposits"].append(_clean_doc(doc))

    async for doc in db.purchases.find({}):
        backup_data["purchases"].append(_clean_doc(doc))

    async for doc in db.transactions.find({}).sort("created_at", -1).limit(5000):
        backup_data["transactions"].append(_clean_doc(doc))

    async for doc in db.countries.find({}):
        backup_data["countries"].append(_clean_doc(doc))

    async for doc in db.data_logs.find({}).sort("created_at", -1).limit(3000):
        backup_data["data_logs"].append(_clean_doc(doc))

    total_deposited = sum(
        d.get("amount", 0) for d in backup_data["deposits"]
        if d.get("status") == "approved"
    )
    total_wallet = sum(float(u.get("balance", 0)) for u in backup_data["users"])

    summary = {
        "total_users": len(backup_data["users"]),
        "total_deposits_records": len(backup_data["deposits"]),
        "total_purchases": len(backup_data["purchases"]),
        "total_transactions": len(backup_data["transactions"]),
        "total_revenue_approved": total_deposited,
        "total_wallet_balance": total_wallet,
        "total_countries": len(backup_data["countries"]),
    }
    backup_data["summary"] = summary

    json_bytes = json.dumps(backup_data, indent=2, default=str).encode("utf-8")
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"legit_stocks_backup_{timestamp}.json"

    try:
        await processing_msg.delete()
    except Exception:
        pass

    summary_text = (
        f"✅ *Data Backup Ready!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Users: `{summary['total_users']}`\n"
        f"💰 Deposit Records: `{summary['total_deposits_records']}`\n"
        f"🛒 Purchases: `{summary['total_purchases']}`\n"
        f"🌍 Countries: `{summary['total_countries']}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 Total Wallet Balances: `₹{total_wallet:.2f}`\n"
        f"📈 Total Revenue: `₹{total_deposited:.2f}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📁 `{filename}`\n\n"
        f"_Save this file securely.\n"
        f"If bot gets deleted, use this JSON to restore buyer balances in a new bot._"
    )

    await callback.bot.send_document(
        callback.from_user.id,
        document=BufferedInputFile(json_bytes, filename=filename),
        caption=summary_text,
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "admin_deposits_log")
async def cb_deposits_log(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return

    db = get_db()
    deposits = await db.deposits.find(
        {"status": "approved"}
    ).sort("created_at", -1).limit(30).to_list(30)

    if not deposits:
        await callback.message.edit_text(
            "💰 *Real-Time Deposit Log*\n\n_No approved deposits yet._",
            reply_markup=admin_back_kb(), parse_mode="Markdown"
        )
        await callback.answer()
        return

    total = sum(d.get("amount", 0) for d in deposits)
    lines = [
        f"📋 *Real-Time Deposit Log*",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"_Last 30 approved | Total: `₹{total:.2f}`_\n",
    ]
    for d in deposits:
        method = "📱 UPI" if d.get("method") == "upi" else "💎 USDT"
        uid = d.get("user_id", "?")
        amount = d.get("amount", 0)
        req_id = d.get("request_id", "N/A")
        dt = d.get("created_at")
        date_str = dt.strftime("%d/%m %H:%M") if dt else "N/A"
        lines.append(f"{method} | `{uid}` | `₹{amount:.0f}` | {req_id} | {date_str}")

    text = "\n".join(lines)
    if len(text) > 3800:
        text = text[:3800] + "\n\n_...truncated_"

    await callback.message.edit_text(text, reply_markup=admin_back_kb(), parse_mode="Markdown")
    await callback.answer()
