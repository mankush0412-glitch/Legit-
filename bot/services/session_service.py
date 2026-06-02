"""
Session Pool Architecture:
- On bot startup / session upload → all sessions IMMEDIATELY connect via Telethon and stay connected
- Pool keeps Dict[phone → {client, status, country, ...}] in memory
- On buy → pick an ALREADY-CONNECTED client → add OTP event handler → wait for OTP
- On OTP received → send to buyer → remove handler → session marked sold
- On bot restart → reload all available sessions from DB → reconnect

This eliminates "Session Error" completely because there's no on-demand connect during purchase.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any

from bson import ObjectId
from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError, AuthKeyUnregisteredError, UserDeactivatedError,
    SessionRevokedError, AuthKeyDuplicatedError, PhoneNumberBannedError
)

from bot.database import get_db
from bot.config import TELEGRAM_API_ID, TELEGRAM_API_HASH
from bot.utils.helpers import extract_otp_from_message

logger = logging.getLogger(__name__)

# Semaphore: max 15 concurrent connections at once (during initial load)
_connect_semaphore = asyncio.Semaphore(15)

# Active OTP monitors: purchase_id → {"task": Task}
active_monitors: Dict[str, Dict] = {}

SESSION_TMP_DIR = "/tmp/tg_sessions"


# ═══════════════════════════════════════════════════════
#  SESSION POOL — Keeps all sessions connected & ready
# ═══════════════════════════════════════════════════════

class SessionPool:
    """
    In-memory pool of always-connected Telethon clients.

    States per slot:
      "available"  — connected, waiting to be sold
      "occupied"   — picked for a purchase, OTP listener active
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        # phone → {client, session_id, country_code, country_name, country_flag,
        #           two_fa, status, session_path}
        self._pool: Dict[str, Dict] = {}

    # ── Stats ──────────────────────────────────────────

    @property
    def total(self) -> int:
        return len(self._pool)

    def available_count(self, country_code: str = None) -> int:
        return sum(
            1 for info in self._pool.values()
            if info["status"] == "available"
            and (country_code is None or info["country_code"] == country_code)
        )

    def get_stats(self) -> Dict[str, Dict]:
        """Returns {country_code: {available, occupied, total}}"""
        stats: Dict[str, Dict] = {}
        for info in self._pool.values():
            code = info["country_code"]
            s = stats.setdefault(code, {"available": 0, "occupied": 0, "total": 0})
            s["total"] += 1
            if info["status"] == "available":
                s["available"] += 1
            else:
                s["occupied"] += 1
        return stats

    # ── Connect one session ────────────────────────────

    async def _connect_one(self, session_doc: Dict) -> bool:
        """Write bytes → connect TelegramClient → add to pool if authorized."""
        phone = session_doc.get("phone_number")
        session_bytes = session_doc.get("session_data")

        if not phone or not session_bytes:
            return False

        # Already in pool?
        async with self._lock:
            if phone in self._pool:
                return True

        os.makedirs(SESSION_TMP_DIR, exist_ok=True)
        sid = str(session_doc["_id"])
        session_path = os.path.join(SESSION_TMP_DIR, sid)

        async with _connect_semaphore:
            client = None
            try:
                # Write session file
                with open(session_path + ".session", "wb") as f:
                    f.write(session_bytes)

                client = TelegramClient(
                    session_path,
                    TELEGRAM_API_ID,
                    TELEGRAM_API_HASH,
                    connection_retries=3,
                    retry_delay=1,
                    timeout=25,
                )
                await client.connect()

                if not await client.is_user_authorized():
                    logger.warning(f"[Pool] Session {phone} not authorized — skipping.")
                    await client.disconnect()
                    try:
                        os.remove(session_path + ".session")
                    except Exception:
                        pass
                    return False

                async with self._lock:
                    self._pool[phone] = {
                        "client": client,
                        "session_id": session_doc["_id"],
                        "country_code": session_doc.get("country_code", ""),
                        "country_name": session_doc.get("country", ""),
                        "country_flag": session_doc.get("country_flag", ""),
                        "two_fa": session_doc.get("two_fa_password", ""),
                        "status": "available",
                        "session_path": session_path,
                    }
                logger.info(f"[Pool] ✅ Connected: {phone} ({session_doc.get('country', '')})")
                return True

            except (AuthKeyUnregisteredError, SessionRevokedError, AuthKeyDuplicatedError):
                logger.warning(f"[Pool] Session revoked: {phone}")
            except UserDeactivatedError:
                logger.warning(f"[Pool] Account deactivated: {phone}")
            except PhoneNumberBannedError:
                logger.warning(f"[Pool] Number banned: {phone}")
            except FloodWaitError as e:
                logger.warning(f"[Pool] FloodWait {e.seconds}s for {phone}")
            except Exception as e:
                logger.warning(f"[Pool] Error connecting {phone}: {e}")

            # Cleanup on failure
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    pass
            try:
                sp = session_path + ".session"
                if os.path.exists(sp):
                    os.remove(sp)
            except Exception:
                pass
            return False

    # ── Public API ─────────────────────────────────────

    async def load_all_from_db(self):
        """
        Called once at bot startup.
        Connects all available sessions from DB.
        """
        db = get_db()
        sessions = await db.sessions.find({"is_available": True}).to_list(10000)
        logger.info(f"[Pool] Loading {len(sessions)} sessions from DB...")

        tasks = [self._connect_one(s) for s in sessions]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if r is True)
        logger.info(f"[Pool] Startup complete: {ok}/{len(sessions)} sessions live.")

    async def add_session(self, session_doc: Dict) -> bool:
        """
        Called after admin uploads a new session.
        Immediately connects and adds to pool.
        """
        return await self._connect_one(session_doc)

    async def pick(self, country_code: str) -> Optional[Dict]:
        """
        Atomically pick an available connected client.
        Returns pool slot info (including the client) or None.
        """
        async with self._lock:
            for phone, info in self._pool.items():
                if info["country_code"] == country_code and info["status"] == "available":
                    info["status"] = "occupied"
                    return {**info, "phone": phone}
        return None

    async def release(self, phone: str):
        """Return a slot back to 'available' (e.g. on cancel)."""
        async with self._lock:
            if phone in self._pool:
                self._pool[phone]["status"] = "available"

    async def remove(self, phone: str):
        """
        Remove from pool + disconnect + delete temp file.
        Called when session is sold (OTP delivered) or errored.
        """
        async with self._lock:
            info = self._pool.pop(phone, None)
        if not info:
            return
        try:
            client: TelegramClient = info["client"]
            if client.is_connected():
                await client.disconnect()
        except Exception:
            pass
        try:
            sp = info["session_path"] + ".session"
            if os.path.exists(sp):
                os.remove(sp)
        except Exception:
            pass

    async def clear_country(self, country_code: str):
        """Remove all available sessions for a country from pool."""
        phones_to_remove = []
        async with self._lock:
            for phone, info in list(self._pool.items()):
                if info["country_code"] == country_code and info["status"] == "available":
                    phones_to_remove.append(phone)
        for phone in phones_to_remove:
            await self.remove(phone)

    async def clear_all(self):
        """Remove all available sessions from pool."""
        phones_to_remove = []
        async with self._lock:
            phones_to_remove = [p for p, i in self._pool.items() if i["status"] == "available"]
        for phone in phones_to_remove:
            await self.remove(phone)


# ── Global pool instance ───────────────────────────────
session_pool = SessionPool()


# ═══════════════════════════════════════════════════════
#  Public helpers for buy flow
# ═══════════════════════════════════════════════════════

async def get_available_countries() -> list:
    """Returns countries with live pool stock counts."""
    db = get_db()
    pool_stats = session_pool.get_stats()

    countries = []
    async for c in db.countries.find({"is_active": True}):
        code = c["code"]
        st = pool_stats.get(code, {})
        stock = st.get("available", 0)
        countries.append({
            "code": code,
            "name": c["name"],
            "flag": c.get("flag", ""),
            "price": c["price"],
            "stock": stock,
        })
    return countries


async def get_country_info(country_code: str) -> Optional[Dict]:
    db = get_db()
    country = await db.countries.find_one({"code": country_code, "is_active": True})
    if not country:
        return None
    country["stock"] = session_pool.available_count(country_code)
    return country


async def create_purchase(user_id: int, phone: str, pool_info: Dict, country: Dict) -> str:
    db = get_db()
    result = await db.purchases.insert_one({
        "user_id": user_id,
        "session_id": pool_info["session_id"],
        "country": country["name"],
        "country_code": country["code"],
        "country_flag": country.get("flag", ""),
        "phone_number": phone,
        "amount": country["price"],
        "status": "waiting_otp",
        "otp": None,
        "two_fa_password": pool_info.get("two_fa", ""),
        "otp_requested_count": 0,
        "created_at": datetime.utcnow(),
        "completed_at": None,
    })
    return str(result.inserted_id)


# ═══════════════════════════════════════════════════════
#  OTP Monitor — uses already-connected pool client
# ═══════════════════════════════════════════════════════

async def start_otp_monitor(purchase_id: str, phone: str, pool_info: Dict, bot) -> bool:
    """
    Starts background OTP listener on the ALREADY-CONNECTED client.
    No new connection is created — the client is from the pool.
    """
    client: TelegramClient = pool_info["client"]
    if not client.is_connected():
        logger.error(f"[OTP] Client {phone} not connected!")
        return False

    db = get_db()
    purchase = await db.purchases.find_one({"_id": ObjectId(purchase_id)})
    if not purchase:
        return False

    task = asyncio.create_task(
        _monitor_otp(purchase_id, phone, pool_info, purchase, bot)
    )
    active_monitors[purchase_id] = {"task": task, "phone": phone}
    return True


async def _monitor_otp(purchase_id: str, phone: str, pool_info: Dict, purchase: Dict, bot):
    """
    Listen on already-connected Telethon client for incoming OTP message.
    Auto-refund + notify user on any failure.
    """
    db = get_db()
    user_id = purchase["user_id"]
    amount = purchase["amount"]
    client: TelegramClient = pool_info["client"]
    two_fa = pool_info.get("two_fa", "")

    otp_found = asyncio.Event()
    otp_handler = None

    async def _handle_new_msg(event):
        try:
            text = event.message.message or ""
            sender = await event.get_sender()
            sender_phone = getattr(sender, 'phone', '') or ''

            is_telegram_service = (
                sender_phone in ["42777", "4433", "22000", "777000"] or
                "login code" in text.lower() or
                "verification code" in text.lower() or
                "login code:" in text.lower() or
                ("telegram" in text.lower() and any(c.isdigit() for c in text))
            )
            if not is_telegram_service:
                return

            otp = extract_otp_from_message(text)
            if not otp:
                return

            updated = await db.purchases.find_one_and_update(
                {"_id": ObjectId(purchase_id)},
                {"$set": {"otp": otp, "status": "otp_received"},
                 "$inc": {"otp_requested_count": 1}},
                return_document=True
            )

            msg = (
                f"✅ *Number Acquired!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🌎 Country: {purchase.get('country_flag', '')} *{purchase.get('country', '')}*\n"
                f"📱 Number: `{phone}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💬 OTP: `{otp}`\n"
            )
            if two_fa:
                msg += f"🔐 2FA Password: `{two_fa}`\n"
            msg += (
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ *Thank you for purchasing!*\n"
                f"🔄 Tap _Get OTP Again_ to refresh."
            )

            from bot.keyboards.buy import otp_received_kb
            try:
                await bot.send_message(
                    user_id, msg,
                    reply_markup=otp_received_kb(purchase_id),
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            otp_found.set()

        except Exception as e:
            logger.error(f"[OTP handler error] {e}")

    try:
        client.add_event_handler(_handle_new_msg, events.NewMessage(incoming=True))
        otp_handler = _handle_new_msg

        # Wait max 5 minutes for OTP
        try:
            await asyncio.wait_for(otp_found.wait(), timeout=300)
            # OTP received — session is sold, remove from pool
            await session_pool.remove(phone)
            await db.sessions.update_one(
                {"_id": pool_info["session_id"]},
                {"$set": {"is_available": False, "sold_at": datetime.utcnow(),
                           "sold_to": user_id}}
            )

        except asyncio.TimeoutError:
            # Timeout — refund + restore
            await _refund_and_restore(user_id, amount, phone, pool_info, purchase_id, bot,
                                      "⏱️ OTP not received in 5 minutes.\n"
                                      "_The number did not get any login code._")

    except asyncio.CancelledError:
        # Cancelled by user (cancel order) — buy.py handles refund
        pass

    except Exception as e:
        await _refund_and_restore(user_id, amount, phone, pool_info, purchase_id, bot,
                                  f"Something went wrong.\n_Error: {str(e)[:80]}_")
    finally:
        # Always remove our event handler
        try:
            if otp_handler:
                client.remove_event_handler(otp_handler)
        except Exception:
            pass
        active_monitors.pop(purchase_id, None)


async def _refund_and_restore(user_id, amount, phone, pool_info, purchase_id, bot, reason_msg):
    """Refund balance, release session slot, notify user."""
    from bot.services.wallet_service import add_balance
    new_bal = await add_balance(user_id, amount, reason="session_error_refund")
    await session_pool.release(phone)  # Put back to available

    db = get_db()
    await db.purchases.update_one(
        {"_id": ObjectId(purchase_id)},
        {"$set": {"status": "error", "error_reason": reason_msg}}
    )
    await db.sessions.update_one(
        {"_id": pool_info["session_id"]},
        {"$set": {"is_available": True}}
    )

    from bot.keyboards.buy import buy_again_kb
    try:
        await bot.send_message(
            user_id,
            f"❌ *Session Error*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{reason_msg}\n\n"
            f"✅ Balance *automatically refunded*.\n"
            f"💎 New Balance: `₹{new_bal:.2f}`\n\n"
            f"Please try buying another number.",
            reply_markup=buy_again_kb(),
            parse_mode="Markdown"
        )
    except Exception:
        pass


async def cancel_monitor(purchase_id: str):
    """Cancel OTP monitor task. Caller handles refund."""
    monitor = active_monitors.get(purchase_id)
    if monitor:
        task = monitor.get("task")
        if task and not task.done():
            task.cancel()
        active_monitors.pop(purchase_id, None)


async def get_fresh_otp(purchase_id: str) -> Optional[str]:
    db = get_db()
    purchase = await db.purchases.find_one({"_id": ObjectId(purchase_id)})
    return purchase.get("otp") if purchase else None


# ═══════════════════════════════════════════════════════
#  Logout device (after OTP use)
# ═══════════════════════════════════════════════════════

async def logout_device(purchase_id: str) -> bool:
    """Terminate other active sessions on the sold account."""
    import tempfile
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
    session_path = os.path.join(tmp_dir, f"lo_{purchase_id}")
    client = None

    try:
        with open(session_path + ".session", "wb") as f:
            f.write(session_bytes)

        client = TelegramClient(session_path, TELEGRAM_API_ID, TELEGRAM_API_HASH)
        await client.connect()

        if await client.is_user_authorized():
            from telethon.tl.functions.account import (
                GetAuthorizationsRequest, ResetAuthorizationRequest
            )
            auths = await client(GetAuthorizationsRequest())
            for auth in auths.authorizations:
                if not auth.current:
                    try:
                        await client(ResetAuthorizationRequest(hash=auth.hash))
                    except Exception:
                        pass

        await db.purchases.update_one(
            {"_id": ObjectId(purchase_id)},
            {"$set": {"status": "completed", "completed_at": datetime.utcnow()}}
        )
        return True

    except Exception as e:
        logger.error(f"[Logout] {e}")
        return False
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
        try:
            sf = session_path + ".session"
            if os.path.exists(sf):
                os.remove(sf)
            if os.path.exists(tmp_dir):
                os.rmdir(tmp_dir)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════
#  Admin ZIP upload — verify + save to DB + add to pool
# ═══════════════════════════════════════════════════════

async def process_zip_and_connect(
    zip_bytes: bytes,
    country_code: str,
    two_fa_password: str,
    added_by: int,
    progress_callback=None
) -> Dict:
    """
    1. Extract all .session files from ZIP
    2. For each: connect → verify authorized → save to DB → add to pool
    """
    import zipfile
    import io

    db = get_db()
    country = await db.countries.find_one({"code": country_code})
    if not country:
        return {"success": False, "error": "Country not found in DB"}

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = [n for n in zf.namelist() if n.endswith(".session")]
            session_data_map = {n: zf.read(n) for n in names}
    except Exception as e:
        return {"success": False, "error": f"Cannot read ZIP: {e}"}

    if not names:
        return {"success": False, "error": "No .session files found in ZIP"}

    added = 0
    failed = 0
    errors = []

    async def _process_one(name: str, session_bytes: bytes):
        nonlocal added, failed

        os.makedirs(SESSION_TMP_DIR, exist_ok=True)
        tmp_path = os.path.join(SESSION_TMP_DIR, f"upload_{name.replace('/', '_')}")
        client = None

        async with _connect_semaphore:
            try:
                with open(tmp_path + ".session", "wb") as f:
                    f.write(session_bytes)

                client = TelegramClient(
                    tmp_path, TELEGRAM_API_ID, TELEGRAM_API_HASH,
                    timeout=20, connection_retries=2
                )
                await client.connect()

                if not await client.is_user_authorized():
                    failed += 1
                    errors.append(f"{name}: not authorized")
                    return

                me = await client.get_me()
                phone = f"+{me.phone}" if me and me.phone else None
                await client.disconnect()
                client = None

                if not phone:
                    failed += 1
                    errors.append(f"{name}: could not get phone number")
                    return

                # Check for duplicates
                existing = await db.sessions.find_one({"phone_number": phone})
                if existing:
                    failed += 1
                    errors.append(f"{name}: duplicate ({phone})")
                    return

                # Save to DB
                result = await db.sessions.insert_one({
                    "country": country["name"],
                    "country_code": country_code,
                    "country_flag": country.get("flag", ""),
                    "phone_number": phone,
                    "session_data": session_bytes,
                    "two_fa_password": two_fa_password,
                    "is_available": True,
                    "added_at": datetime.utcnow(),
                    "added_by": added_by,
                    "zip_name": name,
                })
                session_doc = {
                    "_id": result.inserted_id,
                    "phone_number": phone,
                    "country": country["name"],
                    "country_code": country_code,
                    "country_flag": country.get("flag", ""),
                    "two_fa_password": two_fa_password,
                    "session_data": session_bytes,
                }

                # Remove temp upload file and reconnect properly through pool
                try:
                    os.remove(tmp_path + ".session")
                except Exception:
                    pass

                # Add to pool (creates a fresh persistent connection)
                ok = await session_pool.add_session(session_doc)
                if ok:
                    added += 1
                    logger.info(f"[Upload] ✅ {phone} logged in to pool.")
                else:
                    failed += 1
                    errors.append(f"{name}: pool connect failed ({phone})")
                    # Still saved in DB for next startup
                    return

                # Report progress
                if progress_callback:
                    await progress_callback(added + failed, len(names), added, failed)

            except Exception as e:
                failed += 1
                errors.append(f"{name}: {str(e)[:70]}")
                logger.error(f"[Upload] Error {name}: {e}")
            finally:
                if client:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                try:
                    sp = tmp_path + ".session"
                    if os.path.exists(sp):
                        os.remove(sp)
                except Exception:
                    pass

    # Run all in parallel (semaphore limits concurrency)
    tasks = [_process_one(name, data) for name, data in session_data_map.items()]
    await asyncio.gather(*tasks, return_exceptions=True)

    return {
        "success": True,
        "total": len(names),
        "added": added,
        "failed": failed,
        "errors": errors[:10],
    }
