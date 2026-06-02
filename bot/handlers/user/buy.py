from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from bson import ObjectId

from bot.database import get_db
from bot.keyboards.buy import (
    countries_kb, confirm_buy_kb, otp_waiting_kb,
    otp_received_kb, after_logout_kb, buy_again_kb, insufficient_balance_kb
)
from bot.keyboards.main_menu import back_to_main_kb
from bot.services.session_service import (
    get_available_countries,
    get_country_info,
    create_purchase,
    start_otp_monitor,
    get_fresh_otp,
    logout_device,
    cancel_monitor,
    session_pool,
)
from bot.services.wallet_service import deduct_balance, add_balance

router = Router()


@router.callback_query(F.data == "buy_account")
async def cb_buy_account(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    countries = await get_available_countries()
    in_stock = [c for c in countries if c["stock"] > 0]

    if not in_stock:
        await callback.message.edit_text(
            "😔 *No Accounts Available*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Stock khali hai abhi.\n"
            "Thodi der baad try karo ya support se contact karo.",
            reply_markup=back_to_main_kb(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return

    lines = ["📌 *Available Accounts*\n━━━━━━━━━━━━━━━━━━━━━━━━"]
    for c in countries:
        if c["stock"] > 0:
            lines.append(
                f"\n{c['flag']} *{c['name']}*\n"
                f"📦 Stock: `{c['stock']}`  •  💰 Price: `₹{c['price']:.0f}`\n"
                f"Status: ✅ In Stock"
            )
        else:
            lines.append(
                f"\n{c['flag']} *{c['name']}*\n"
                f"📦 Stock: `0`  •  💰 Price: `₹{c['price']:.0f}`\n"
                f"Status: ❌ Out of Stock"
            )
    lines.append("\n\n👇 *Select a country to purchase:*")

    try:
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=countries_kb(in_stock),
            parse_mode="Markdown"
        )
    except Exception:
        await callback.message.answer(
            "\n".join(lines),
            reply_markup=countries_kb(in_stock),
            parse_mode="Markdown"
        )
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
    needed = country["price"] - balance

    text = (
        f"⚡ *Account Summary*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌎 Country: {country['flag']} *{country['name']}*\n"
        f"📦 Stock Available: `{country['stock']}`\n"
        f"💰 Price: `₹{country['price']:.0f}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ High Quality  •  ✅ Verified  •  ⚡ Instant OTP\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 Your Balance: `₹{balance:.2f}`\n"
    )

    if insufficient:
        text += (
            f"\n❌ *Insufficient Balance!*\n"
            f"You need `₹{needed:.0f}` more.\n"
            f"Deposit to continue."
        )
        await callback.message.edit_text(text, reply_markup=insufficient_balance_kb(), parse_mode="Markdown")
    else:
        text += "\n⚠️ _Use responsibly. Not liable for misuse bans._"
        await callback.message.edit_text(text, reply_markup=confirm_buy_kb(country_code), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_buy:"))
async def cb_confirm_buy(callback: CallbackQuery, state: FSMContext, db_user: dict = None):
    country_code = callback.data.split(":")[1]
    user_id = callback.from_user.id

    await callback.message.edit_text(
        "⏳ *Processing...*\n_Securing your account..._",
        parse_mode="Markdown"
    )
    await callback.answer()

    country = await get_country_info(country_code)
    if not country or country["stock"] == 0:
        await callback.message.edit_text(
            "❌ *Out of Stock!*\n\nYeh country ka stock khatam. Doosra try karo.",
            reply_markup=buy_again_kb(), parse_mode="Markdown"
        )
        return

    # Pick an ALREADY-CONNECTED client from the pool
    pool_slot = await session_pool.pick(country_code)
    if not pool_slot:
        await callback.message.edit_text(
            "❌ *No Sessions Available!*\n\nSab slots liye hue hain. Thodi der baad try karo.",
            reply_markup=buy_again_kb(), parse_mode="Markdown"
        )
        return

    phone = pool_slot["phone"]

    # Deduct balance
    deducted = await deduct_balance(user_id, country["price"])
    if not deducted:
        await session_pool.release(phone)  # Put back to available
        await callback.message.edit_text(
            "❌ *Insufficient Balance!*\n\nDeposit karo aur try karo.",
            reply_markup=insufficient_balance_kb(), parse_mode="Markdown"
        )
        return

    # Track stats
    db = get_db()
    await db.users.update_one(
        {"telegram_id": user_id},
        {"$inc": {"total_purchases": 1, "total_spent": country["price"]}}
    )

    # Create purchase record
    purchase_id = await create_purchase(user_id, phone, pool_slot, country)

    # Show "Waiting for OTP" screen
    waiting_text = (
        f"📡 *Waiting for OTP...*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌎 Country: {country['flag']} *{country['name']}*\n"
        f"📱 Number: `{phone}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 *Instructions:*\n"
        f"1️⃣ Open Telegram App\n"
        f"2️⃣ Enter number: `{phone}`\n"
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

    # Start OTP monitor on already-connected client (NO new connection created)
    started = await start_otp_monitor(purchase_id, phone, pool_slot, callback.bot)
    if not started:
        # Immediate failure — refund and restore
        new_bal = await add_balance(user_id, country["price"], reason="monitor_start_fail_refund")
        await session_pool.release(phone)
        await callback.bot.send_message(
            user_id,
            f"❌ *Session Error*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Something went wrong. Balance refunded.\n"
            f"💎 New Balance: `₹{new_bal:.2f}`",
            reply_markup=buy_again_kb(),
            parse_mode="Markdown"
        )


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
            reply_markup=otp_received_kb(purchase_id),
            parse_mode="Markdown"
        )
        await callback.answer("✅ Refreshed!")
    else:
        await callback.answer("⏳ OTP abhi nahi aaya. Wait karo...", show_alert=True)


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
            reply_markup=otp_received_kb(purchase_id),
            parse_mode="Markdown"
        )
        await callback.answer("✅ OTP refreshed!")
    else:
        await callback.answer("⏳ OTP nahi mila abhi.", show_alert=True)


def _build_otp_message(purchase, otp, password):
    return (
        f"✅ *Number Acquired!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌎 Country: {purchase.get('country_flag', '')} *{purchase.get('country', 'N/A')}*\n"
        f"📱 Number: `{purchase.get('phone_number', 'N/A')}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 OTP: `{otp}`\n"
        + (f"🔐 2FA Password: `{password}`\n" if password else "")
        + f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *Thank you for purchasing!*\n"
        f"🔄 Tap _Get OTP Again_ to refresh anytime."
    )


@router.callback_query(F.data.startswith("cancel_order:"))
async def cb_cancel_order(callback: CallbackQuery):
    purchase_id = callback.data.split(":")[1]
    db = get_db()
    purchase = await db.purchases.find_one({"_id": ObjectId(purchase_id)})

    if purchase and purchase.get("status") in ("waiting_otp",):
        # Cancel the background OTP task first
        await cancel_monitor(purchase_id)

        # Release session slot back to pool
        phone = purchase.get("phone_number")
        if phone:
            await session_pool.release(phone)
            await db.sessions.update_one(
                {"_id": purchase["session_id"]},
                {"$set": {"is_available": True}}
            )

        # Refund balance
        new_bal = await add_balance(callback.from_user.id, purchase["amount"], reason="order_cancelled_refund")
        await db.purchases.update_one(
            {"_id": ObjectId(purchase_id)},
            {"$set": {"status": "cancelled"}}
        )
        await callback.message.edit_text(
            f"❌ *Order Cancelled*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ `₹{purchase['amount']:.0f}` refunded.\n"
            f"💎 Balance: `₹{new_bal:.2f}`",
            reply_markup=buy_again_kb(),
            parse_mode="Markdown"
        )
    else:
        await callback.message.edit_text(
            "❌ *Order Cancelled*\n\n✅ Balance refunded.",
            reply_markup=back_to_main_kb(), parse_mode="Markdown"
        )
    await callback.answer()


@router.callback_query(F.data.startswith("logout_device:"))
async def cb_logout_device(callback: CallbackQuery):
    purchase_id = callback.data.split(":")[1]
    await callback.message.edit_text("⏳ *Logging out other devices...*", parse_mode="Markdown")
    success = await logout_device(purchase_id)

    if success:
        await callback.message.edit_text(
            "✅ *Logged Out Successfully!*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Saare doosre devices logout ho gaye.\n"
            "Account ab clean aur safe hai.",
            reply_markup=after_logout_kb(), parse_mode="Markdown"
        )
    else:
        await callback.message.edit_text(
            "❌ *Logout Failed*\n\nDevice logout nahi hua. Support se contact karo.",
            reply_markup=back_to_main_kb(), parse_mode="Markdown"
        )
    await callback.answer()
