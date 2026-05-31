from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from bson import ObjectId

from bot.database import get_db
from bot.keyboards.buy import countries_kb, confirm_buy_kb, otp_waiting_kb, otp_received_kb, after_logout_kb
from bot.keyboards.main_menu import back_to_main_kb
from bot.services.session_service import (
    get_available_countries,
    get_country_info,
    pick_session,
    reserve_session,
    create_purchase,
    start_otp_monitor,
    get_fresh_otp,
    logout_device,
)
from bot.services.wallet_service import deduct_balance
from bot.states.states import BuyAccount

router = Router()


@router.callback_query(F.data == "buy_account")
async def cb_buy_account(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    countries = await get_available_countries()
    in_stock = [c for c in countries if c["stock"] > 0]

    if not in_stock:
        await callback.message.edit_text(
            "😔 *No Accounts Available*\n\n"
            "Stock is currently empty.\n"
            "Please check back soon or contact support.",
            reply_markup=back_to_main_kb(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return

    lines = ["📌 *Available Accounts*\n"]
    for c in in_stock:
        lines.append(
            f"{c['flag']} *{c['name']}*  ✅ {c['stock']} in stock  •  💰 ₹{c['price']:.2f}"
        )
    lines.append("\n👇 *Select a country to purchase:*")
    text = "\n".join(lines)

    try:
        await callback.message.edit_text(text, reply_markup=countries_kb(in_stock), parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text, reply_markup=countries_kb(in_stock), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("buy_country:"))
async def cb_buy_country(callback: CallbackQuery, state: FSMContext, db_user: dict = None):
    country_code = callback.data.split(":")[1]
    country = await get_country_info(country_code)

    if not country:
        await callback.answer("❌ Country unavailable.", show_alert=True)
        return
    if country["stock"] == 0:
        await callback.answer("❌ Out of stock! Try another country.", show_alert=True)
        return

    balance = float(db_user.get("balance", 0.0)) if db_user else 0.0
    insufficient = balance < country["price"]

    text = (
        f"⚡ *Account Summary*\n\n"
        f"🌎 *Country:* {country['flag']} {country['name']}\n"
        f"📦 *Stock:* {country['stock']} available\n"
        f"💰 *Price:* `₹{country['price']:.2f}`\n"
        f"💎 *Your Balance:* `₹{balance:.2f}`\n\n"
        f"✅ High Quality  •  ✅ Verified  •  ⚡ Instant\n"
    )

    if insufficient:
        needed = country["price"] - balance
        text += (
            f"\n❌ *Insufficient Balance*\n"
            f"You need `₹{needed:.2f}` more.\n"
            f"Please deposit funds to continue."
        )
        from bot.keyboards.buy import insufficient_balance_kb
        await callback.message.edit_text(text, reply_markup=insufficient_balance_kb(), parse_mode="Markdown")
    else:
        text += f"\n⚠️ _Use responsibly. Not liable for bans from misuse._"
        await callback.message.edit_text(text, reply_markup=confirm_buy_kb(country_code), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_buy:"))
async def cb_confirm_buy(callback: CallbackQuery, state: FSMContext, db_user: dict = None):
    country_code = callback.data.split(":")[1]
    country = await get_country_info(country_code)
    user_id = callback.from_user.id

    if not country or country["stock"] == 0:
        await callback.answer("❌ Out of stock!", show_alert=True)
        return

    session = await pick_session(country_code)
    if not session:
        await callback.answer("❌ No sessions available.", show_alert=True)
        return

    reserved = await reserve_session(session["_id"], user_id)
    if not reserved:
        await callback.answer("❌ Session just taken. Try again.", show_alert=True)
        return

    deducted = await deduct_balance(user_id, country["price"])
    if not deducted:
        db = get_db()
        await db.sessions.update_one(
            {"_id": session["_id"]},
            {"$set": {"is_available": True, "sold_to": None, "sold_at": None}}
        )
        await callback.answer("❌ Insufficient balance!", show_alert=True)
        return

    db = get_db()
    await db.users.update_one(
        {"telegram_id": user_id},
        {"$inc": {"total_purchases": 1, "total_spent": country["price"]}}
    )

    purchase_id = await create_purchase(user_id, session, country)

    await callback.message.edit_text(
        "⏳ *Processing...*\n\n_Securing your account, please wait._",
        parse_mode="Markdown"
    )

    started = await start_otp_monitor(purchase_id, callback.bot)

    if not started:
        await db.sessions.update_one(
            {"_id": session["_id"]},
            {"$set": {"is_available": True}}
        )
        await _add_balance_back(user_id, country["price"])
        await callback.message.edit_text(
            "❌ *Session Error*\n\n"
            "Failed to load session. Your balance has been refunded.\n"
            "Please contact support.",
            reply_markup=back_to_main_kb(), parse_mode="Markdown"
        )
        await callback.answer()
        return

    waiting_text = (
        f"📡 *Waiting for OTP...*\n\n"
        f"🌎 *Country:* {country['flag']} {country['name']}\n"
        f"📱 *Number:* `{session['phone_number']}`\n\n"
        f"📋 *Instructions:*\n"
        f"1️⃣ Open Telegram App\n"
        f"2️⃣ Enter number: `{session['phone_number']}`\n"
        f"3️⃣ OTP will appear here automatically ✨\n"
    )

    try:
        await callback.message.edit_text(
            waiting_text, reply_markup=otp_waiting_kb(purchase_id), parse_mode="Markdown"
        )
    except Exception:
        await callback.message.answer(
            waiting_text, reply_markup=otp_waiting_kb(purchase_id), parse_mode="Markdown"
        )
    await callback.answer()


async def _add_balance_back(user_id: int, amount: float):
    from bot.services.wallet_service import add_balance
    await add_balance(user_id, amount, reason="session_error_refund")


@router.callback_query(F.data.startswith("get_new_sms:"))
async def cb_get_new_sms(callback: CallbackQuery):
    purchase_id = callback.data.split(":")[1]
    otp = await get_fresh_otp(purchase_id)

    if otp:
        db = get_db()
        purchase = await db.purchases.find_one_and_update(
            {"_id": ObjectId(purchase_id)},
            {"$inc": {"otp_requested_count": 1}},
            return_document=True
        )
        password = purchase.get("two_fa_password", "") if purchase else ""
        await callback.message.edit_text(
            _build_otp_message(purchase, otp, password),
            reply_markup=otp_received_kb(purchase_id), parse_mode="Markdown"
        )
    else:
        await callback.answer("⏳ OTP not received yet. Please wait...", show_alert=True)


@router.callback_query(F.data.startswith("get_otp_again:"))
async def cb_get_otp_again(callback: CallbackQuery):
    purchase_id = callback.data.split(":")[1]
    otp = await get_fresh_otp(purchase_id)

    if otp:
        db = get_db()
        purchase = await db.purchases.find_one_and_update(
            {"_id": ObjectId(purchase_id)},
            {"$inc": {"otp_requested_count": 1}},
            return_document=True
        )
        password = purchase.get("two_fa_password", "") if purchase else ""
        await callback.message.edit_text(
            _build_otp_message(purchase, otp, password),
            reply_markup=otp_received_kb(purchase_id), parse_mode="Markdown"
        )
        await callback.answer("✅ OTP refreshed!")
    else:
        await callback.answer("⏳ OTP not available yet.", show_alert=True)


def _build_otp_message(purchase, otp, password):
    text = (
        f"✅ *Number Acquired!*\n\n"
        f"🌎 *Country:* {purchase.get('country_flag', '')} {purchase.get('country', 'N/A')}\n"
        f"📱 *Number:* `{purchase.get('phone_number', 'N/A')}`\n"
        f"💬 *OTP:* `{otp}`\n"
    )
    if password:
        text += f"🔐 *2FA Password:* `{password}`\n"
    text += "\n✅ *Thank you for purchasing!*\n_Tap Get OTP Again to refresh anytime._"
    return text


@router.callback_query(F.data.startswith("cancel_order:"))
async def cb_cancel_order(callback: CallbackQuery):
    purchase_id = callback.data.split(":")[1]
    db = get_db()
    purchase = await db.purchases.find_one({"_id": ObjectId(purchase_id)})

    if purchase and purchase.get("status") == "waiting_otp":
        await db.sessions.update_one(
            {"_id": purchase["session_id"]},
            {"$set": {"is_available": True, "sold_to": None, "sold_at": None}}
        )
        from bot.services.wallet_service import add_balance
        await add_balance(callback.from_user.id, purchase["amount"], reason="order_cancelled_refund")
        await db.purchases.update_one(
            {"_id": ObjectId(purchase_id)},
            {"$set": {"status": "cancelled"}}
        )
        from bot.services.session_service import active_monitors
        monitor = active_monitors.get(purchase_id)
        if monitor and monitor.get("task"):
            monitor["task"].cancel()
        active_monitors.pop(purchase_id, None)

    await callback.message.edit_text(
        "❌ *Order Cancelled*\n\n✅ Your balance has been refunded.",
        reply_markup=back_to_main_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("logout_device:"))
async def cb_logout_device(callback: CallbackQuery):
    purchase_id = callback.data.split(":")[1]
    await callback.message.edit_text("⏳ *Logging out device...*", parse_mode="Markdown")
    success = await logout_device(purchase_id)

    if success:
        await callback.message.edit_text(
            "✅ *Logged Out Successfully!*\n\n"
            "The session has been terminated.\n"
            "Account is now clean and ready.",
            reply_markup=after_logout_kb(), parse_mode="Markdown"
        )
    else:
        await callback.message.edit_text(
            "❌ *Logout Failed*\n\nCould not terminate session. Contact support.",
            reply_markup=back_to_main_kb(), parse_mode="Markdown"
        )
    await callback.answer()
