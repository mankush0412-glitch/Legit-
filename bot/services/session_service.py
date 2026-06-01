import asyncio
import os
import tempfile
import zipfile
import io
from datetime import datetime
from typing import Optional, Dict, Any
from bson import ObjectId

from telethon import TelegramClient, events
from telethon.tl.functions.auth import LogOutRequest
from telethon.sessions import StringSession
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.database import get_db
from bot.config import TELEGRAM_API_ID, TELEGRAM_API_HASH
from bot.utils.helpers import extract_otp_from_message

active_monitors: Dict[str, Dict] = {}


async def get_available_countries() -> list:
    db = get_db()
    pipeline = [
        {"$match": {"is_available": True}},
        {"$group": {
            "_id": "$country_code",
            "count": {"$sum": 1},
            "country": {"$first": "$country"},
            "flag": {"$first": "$country_flag"},
        }}
    ]
    sessions_count = {doc["_id"]: doc["count"] async for doc in db.sessions.aggregate(pipeline)}

    countries = []
    async for c in db.countries.find({"is_active": True}):
        code = c["code"]
        stock = sessions_count.get(code, 0)
        countries.append({
            "code": code,
            "name": c["name"],
            "flag": c["flag"],
            "price": c["price"],
            "stock": stock,
        })
    return countries


async def get_country_info(country_code: str) -> Optional[Dict]:
    db = get_db()
    country = await db.countries.find_one({"code": country_code, "is_active": True})
    if not country:
        return None
    stock = await db.sessions.count_documents({"country_code": country_code, "is_available": True})
    country["stock"] = stock
    return country


async def pick_session(country_code: str) -> Optional[Dict]:
    db = get_db()
    session = await db.sessions.find_one({"country_code": country_code, "is_available": True})
    return session


async def reserve_session(session_id: ObjectId, user_id: int) -> bool:
    db = get_db()
    result = await db.sessions.update_one(
        {"_id": session_id, "is_available": True},
        {"$set": {
            "is_available": False,
            "sold_to": user_id,
            "sold_at": datetime.utcnow()
        }}
    )
    return result.modified_count > 0


async def create_purchase(user_id: int, session: Dict, country: Dict) -> str:
    db = get_db()
    purchase = {
        "user_id": user_id,
        "session_id": session["_id"],
        "country": country["name"],
        "country_code": country["code"],
        "country_flag": country.get("flag", ""),
        "phone_number": session["phone_number"],
        "amount": country["price"],
        "status": "waiting_otp",
        "otp": None,
        "two_fa_password": session.get("two_fa_password", ""),
        "otp_requested_count": 0,
        "created_at": datetime.utcnow(),
        "completed_at": None,
    }
    result = await db.purchases.insert_one(purchase)
    return str(result.inserted_id)


async def start_otp_monitor(purchase_id: str, bot) -> bool:
    db = get_db()
    purchase = await db.purchases.find_one({"_id": ObjectId(purchase_id)})
    if not purchase:
        return False

    session_doc = await db.sessions.find_one({"_id": purchase["session_id"]})
    if not session_doc:
        return False

    session_bytes = session_doc.get("session_data")
    if not session_bytes:
        return False

    task = asyncio.create_task(
        _monitor_otp(purchase_id, session_bytes, purchase["user_id"], purchase["phone_number"], bot)
    )
    active_monitors[purchase_id] = {"task": task, "client": None}
    return True


async def _monitor_otp(purchase_id: str, session_bytes: bytes, user_id: int, phone: str, bot):
    db = get_db()
    tmp_dir = tempfile.mkdtemp()
    session_path = os.path.join(tmp_dir, f"session_{purchase_id}")

    try:
        with open(session_path + ".session", "wb") as f:
            f.write(session_bytes)

        client = TelegramClient(session_path, TELEGRAM_API_ID, TELEGRAM_API_HASH)
        if purchase_id in active_monitors:
            active_monitors[purchase_id]["client"] = client

        await client.connect()

        if not await client.is_user_authorized():
            await _cleanup_monitor(purchase_id, client, tmp_dir, session_path)
            # Session expired — auto refund user
            purchase = await db.purchases.find_one({"_id": ObjectId(purchase_id)})
            if purchase:
                from bot.services.wallet_service import add_balance
                await add_balance(user_id, purchase["amount"], reason="session_expired_refund")
                await db.sessions.update_one(
                    {"_id": purchase["session_id"]},
                    {"$set": {"is_available": False, "is_expired": True}}
                )
                await db.purchases.update_one(
                    {"_id": ObjectId(purchase_id)},
                    {"$set": {"status": "failed_expired"}}
                )
            try:
                await bot.send_message(
                    user_id,
                    "❌ *Session Expired*\n\n"
                    "This number's session is no longer active.\n"
                    "✅ Your balance has been *automatically refunded*.\n\n"
                    "Please try buying another number.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="🛒  Buy Again  ", callback_data="buy_account")
                    ]])
                )
            except Exception:
                pass
            return

        otp_found = asyncio.Event()

        @client.on(events.NewMessage(incoming=True))
        async def handler(event):
            sender = await event.get_sender()
            sender_id = getattr(sender, 'id', None)
            text = event.message.message or ""

            is_service = (
                (hasattr(sender, 'phone') and sender.phone in ["42777", "4433", "22000"]) or
                "login" in text.lower() or
                "verification code" in text.lower() or
                "Login code" in text or
                (len(text) < 200 and any(c.isdigit() for c in text) and "telegram" in text.lower())
            )

            if is_service:
                otp = extract_otp_from_message(text)
                if otp:
                    await db.purchases.update_one(
                        {"_id": ObjectId(purchase_id)},
                        {
                            "$set": {"otp": otp, "status": "otp_received"},
                            "$inc": {"otp_requested_count": 1}
                        }
                    )
                    from bot.keyboards.buy import otp_received_kb
                    purchase = await db.purchases.find_one({"_id": ObjectId(purchase_id)})
                    password = purchase.get("two_fa_password", "")

                    msg = (
                        f"✅ *Number Acquired!*\n\n"
                        f"🌎 *Country:* {purchase.get('country_flag', '')} {purchase.get('country', '')}\n"
                        f"📱 *Number:* `{phone}`\n"
                        f"💬 *OTP:* `{otp}`\n"
                    )
                    if password:
                        msg += f"🔐 Password: `{password}`\n"
                    msg += "✅ Thank you for purchasing!"

                    try:
                        await bot.send_message(
                            user_id,
                            msg,
                            reply_markup=otp_received_kb(purchase_id),
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass
                    otp_found.set()

        try:
            await asyncio.wait_for(otp_found.wait(), timeout=300)
        except asyncio.TimeoutError:
            # Refund user on timeout — session stays sold (was connected, may be compromised)
            purchase = await db.purchases.find_one({"_id": ObjectId(purchase_id)})
            if purchase and purchase.get("status") == "waiting_otp":
                from bot.services.wallet_service import add_balance
                await add_balance(user_id, purchase["amount"], reason="otp_timeout_refund")
                await db.purchases.update_one(
                    {"_id": ObjectId(purchase_id)},
                    {"$set": {"status": "failed_timeout"}}
                )
            try:
                await bot.send_message(
                    user_id,
                    "⏱️ *OTP Timeout*\n\n"
                    "No login code was received in 5 minutes.\n"
                    "✅ Your balance has been *automatically refunded*.\n\n"
                    "Please try buying another number.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="🛒  Buy Again  ", callback_data="buy_account")
                    ]])
                )
            except Exception:
                pass

    except Exception as e:
        db = get_db()
        purchase = await db.purchases.find_one({"_id": ObjectId(purchase_id)})
        if purchase and purchase.get("status") == "waiting_otp":
            from bot.services.wallet_service import add_balance
            await add_balance(user_id, purchase["amount"], reason="session_error_refund")
            await db.purchases.update_one(
                {"_id": ObjectId(purchase_id)},
                {"$set": {"status": "failed_error"}}
            )
        try:
            await bot.send_message(
                user_id,
                "❌ *Session Error*\n\n"
                "Something went wrong loading your session.\n"
                "✅ Your balance has been *automatically refunded*.\n\n"
                "Please try buying another number.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🛒  Buy Again  ", callback_data="buy_account")
                ]])
            )
        except Exception:
            pass
    finally:
        await _cleanup_monitor(purchase_id, active_monitors.get(purchase_id, {}).get("client"), tmp_dir, session_path)


async def _cleanup_monitor(purchase_id: str, client, tmp_dir: str, session_path: str):
    try:
        if client and client.is_connected():
            await client.disconnect()
    except Exception:
        pass
    try:
        if os.path.exists(session_path + ".session"):
            os.remove(session_path + ".session")
        if os.path.exists(tmp_dir):
            os.rmdir(tmp_dir)
    except Exception:
        pass
    active_monitors.pop(purchase_id, None)


async def get_fresh_otp(purchase_id: str) -> Optional[str]:
    db = get_db()
    purchase = await db.purchases.find_one({"_id": ObjectId(purchase_id)})
    return purchase.get("otp") if purchase else None


async def logout_device(purchase_id: str) -> bool:
    db = get_db()
    purchase = await db.purchases.find_one({"_id": ObjectId(purchase_id)})
    if not purchase:
        return False

    session_doc = await db.sessions.find_one({"_id": purchase["session_id"]})
    if not session_doc:
        return False

    session_bytes = session_doc.get("session_data")
    if not session_bytes:
        return False

    tmp_dir = tempfile.mkdtemp()
    session_path = os.path.join(tmp_dir, f"logout_{purchase_id}")

    try:
        with open(session_path + ".session", "wb") as f:
            f.write(session_bytes)

        client = TelegramClient(session_path, TELEGRAM_API_ID, TELEGRAM_API_HASH)
        await client.connect()

        if await client.is_user_authorized():
            from telethon.tl.functions.account import GetAuthorizationsRequest, ResetAuthorizationRequest
            sessions_result = await client(GetAuthorizationsRequest())
            for auth in sessions_result.authorizations:
                if not auth.current:
                    try:
                        await client(ResetAuthorizationRequest(hash=auth.hash))
                    except Exception:
                        pass

        await client.disconnect()
        await db.purchases.update_one(
            {"_id": ObjectId(purchase_id)},
            {"$set": {"status": "completed", "completed_at": datetime.utcnow()}}
        )
        return True

    except Exception as e:
        print(f"[Logout Device Error] {e}")
        return False
    finally:
        try:
            if os.path.exists(session_path + ".session"):
                os.remove(session_path + ".session")
            if os.path.exists(tmp_dir):
                os.rmdir(tmp_dir)
        except Exception:
            pass


