import io
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from aiogram.fsm.context import FSMContext

from bot.database import get_db
from bot.keyboards.deposit import deposit_methods_kb, cancel_deposit_kb, after_deposit_kb
from bot.keyboards.main_menu import back_to_main_kb
from bot.states.states import DepositUPI, DepositCrypto
from bot.utils.helpers import generate_request_id, generate_upi_qr, log_event
from bot.services.wallet_service import add_balance, apply_referral_deposit_bonus
from bot.services.payment_service import verify_trc20_transaction
from bot.services.settings_service import get_setting, get_all_admin_ids
from datetime import datetime

router = Router()


@router.callback_query(F.data == "deposit")
async def cb_deposit(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    db = get_db()
    user = await db.users.find_one({"telegram_id": callback.from_user.id})
    balance = float(user.get("balance", 0.0)) if user else 0.0

    text = (
        f"💰 *Add Funds*\n\n"
        f"💎 *Your Balance:* `₹{balance:.2f}`\n\n"
        f"Choose a payment method:\n\n"
        f"⚡ *Crypto (USDT)* — Blockchain auto-verify\n"
        f"🇮🇳 *UPI* — Instant credit on submission\n"
    )
    try:
        await callback.message.edit_text(text, reply_markup=deposit_methods_kb(), parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text, reply_markup=deposit_methods_kb(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "deposit_upi")
async def cb_deposit_upi(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DepositUPI.waiting_amount)
    auto_approve = await get_setting("auto_approve_upi", True)
    min_amount = await get_setting("min_deposit_amount", 10.0)
    mode = "⚡ *Instant Credit*" if auto_approve else "🔍 Manual Verification"
    await callback.message.edit_text(
        f"🇮🇳 *UPI Deposit*\n\n"
        f"Status: {mode}\n\n"
        f"Enter amount to deposit:\n"
        f"_Minimum: ₹{min_amount:.0f}_",
        reply_markup=cancel_deposit_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(DepositUPI.waiting_amount)
async def process_upi_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.strip().replace("₹", "").replace(",", ""))
        min_amount = await get_setting("min_deposit_amount", 10.0)
        if amount < min_amount:
            await message.answer(
                f"❌ Minimum deposit is `₹{min_amount:.0f}`. Enter a valid amount:",
                reply_markup=cancel_deposit_kb(), parse_mode="Markdown"
            )
            return
        if amount > 50000:
            await message.answer("❌ Maximum ₹50,000 per deposit:", reply_markup=cancel_deposit_kb())
            return
    except ValueError:
        await message.answer("❌ Invalid. Enter a number like `100`:", parse_mode="Markdown")
        return

    upi_id = await get_setting("upi_id", "")
    upi_name = await get_setting("upi_name", "")
    auto_approve = await get_setting("auto_approve_upi", True)

    await state.update_data(deposit_amount=amount)
    request_id = generate_request_id()
    await state.update_data(request_id=request_id)

    upi_note = f"LSB{request_id[1:]}"
    qr_bytes = generate_upi_qr(upi_id, upi_name, amount, upi_note)

    caption = (
        f"🇮🇳 *Complete Your Payment*\n\n"
        f"💰 *Amount:* `₹{amount:.2f}`\n"
        f"💎 *UPI ID:* `{upi_id}`\n"
        f"📝 *Remark:* `{upi_note}`\n\n"
        f"📱 *Steps:*\n"
        f"1️⃣ Scan QR or copy UPI ID\n"
        f"2️⃣ Pay exactly `₹{amount:.2f}`\n"
        f"3️⃣ Add remark: `{upi_note}`\n"
        f"4️⃣ Copy your UTR / Transaction ID\n"
        f"5️⃣ Paste it below 👇\n\n"
        f"{'⚡ *Balance credited instantly!*' if auto_approve else '🔍 Admin will verify shortly.'}"
    )

    await message.answer_photo(
        photo=BufferedInputFile(qr_bytes, filename="upi_qr.png"),
        caption=caption, parse_mode="Markdown"
    )
    await state.set_state(DepositUPI.waiting_utr)


@router.message(DepositUPI.waiting_utr)
async def process_upi_utr(message: Message, state: FSMContext):
    utr = message.text.strip()
    if len(utr) < 6:
        await message.answer("❌ Invalid UTR. Enter a valid Transaction ID:")
        return

    data = await state.get_data()
    amount = data.get("deposit_amount", 0)
    request_id = data.get("request_id", generate_request_id())
    user_id = message.from_user.id
    db = get_db()

    existing = await db.deposits.find_one({"utr": utr, "status": {"$in": ["pending", "approved"]}})
    if existing:
        await message.answer(
            "❌ *This UTR has already been used!*\n\n"
            "Each UTR can only be submitted once.\n"
            "Contact support if this is an error.",
            parse_mode="Markdown", reply_markup=after_deposit_kb()
        )
        await state.clear()
        return

    auto_approve = await get_setting("auto_approve_upi", True)
    processing_msg = await message.answer("⏳ *Processing your deposit...*", parse_mode="Markdown")

    if auto_approve:
        await db.deposits.insert_one({
            "request_id": request_id,
            "user_id": user_id,
            "amount": amount,
            "method": "upi",
            "utr": utr,
            "status": "approved",
            "created_at": datetime.utcnow(),
            "verified_at": datetime.utcnow(),
            "verified_by": "auto",
        })
        new_balance = await add_balance(user_id, amount, reason=f"upi_deposit_{request_id}")
        await apply_referral_deposit_bonus(user_id, amount)
        await log_event(user_id, "deposit_approved", {"method": "upi", "amount": amount, "utr": utr})

        await processing_msg.delete()
        await message.answer(
            f"✅ *UPI Deposit Approved!*\n\n"
            f"💰 *Added:* `₹{amount:.2f}`\n"
            f"💎 *New Balance:* `₹{new_balance:.2f}`\n"
            f"🆔 *Request ID:* `{request_id}`\n\n"
            f"⚡ Credited instantly!",
            parse_mode="Markdown", reply_markup=after_deposit_kb()
        )

        user = await db.users.find_one({"telegram_id": user_id})
        uname = f"@{user['username']}" if user and user.get("username") else f"ID: {user_id}"
        for admin_id in await get_all_admin_ids():
            try:
                await message.bot.send_message(
                    admin_id,
                    f"💰 *Auto-Approved UPI Deposit*\n"
                    f"👤 {uname} (`{user_id}`)\n"
                    f"💰 ₹{amount:.2f}  •  UTR: `{utr}`\n"
                    f"🆔 {request_id}",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
    else:
        await db.deposits.insert_one({
            "request_id": request_id,
            "user_id": user_id,
            "amount": amount,
            "method": "upi",
            "utr": utr,
            "status": "pending",
            "created_at": datetime.utcnow(),
            "verified_at": None,
            "verified_by": None,
        })
        await log_event(user_id, "deposit_pending", {"method": "upi", "amount": amount, "utr": utr})
        deposit_doc = await db.deposits.find_one({"request_id": request_id})
        deposit_id = str(deposit_doc["_id"])
        from bot.keyboards.admin import deposit_approve_kb
        user = await db.users.find_one({"telegram_id": user_id})
        uname = f"@{user['username']}" if user and user.get("username") else f"ID: {user_id}"

        await processing_msg.delete()
        await message.answer(
            f"💎 *Deposit Received*\n\n"
            f"💰 *Amount:* `₹{amount:.2f}`\n"
            f"🆔 *Request ID:* `{request_id}`\n\n"
            f"⏳ Pending admin verification...",
            parse_mode="Markdown", reply_markup=after_deposit_kb()
        )
        for admin_id in await get_all_admin_ids():
            try:
                await message.bot.send_message(
                    admin_id,
                    f"💳 *New UPI Deposit Request*\n"
                    f"👤 {uname} (`{user_id}`)\n"
                    f"💰 ₹{amount:.2f}  •  UTR: `{utr}`\n"
                    f"🆔 {request_id}",
                    reply_markup=deposit_approve_kb(deposit_id, user_id),
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    await state.clear()


@router.callback_query(F.data == "deposit_crypto")
async def cb_deposit_crypto(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DepositCrypto.waiting_amount)
    auto_crypto = await get_setting("auto_approve_crypto", True)
    rate = await get_setting("crypto_exchange_rate", 83.0)
    mode = "⚡ *Blockchain Auto-Verify*" if auto_crypto else "🔍 Manual Verification"
    await callback.message.edit_text(
        f"💎 *USDT Deposit*\n\n"
        f"Status: {mode}\n\n"
        f"Enter USDT amount:\n"
        f"_Minimum: $1  •  Rate: 1 USDT ≈ ₹{rate:.0f}_",
        reply_markup=cancel_deposit_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(DepositCrypto.waiting_amount)
async def process_crypto_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.strip().replace("$", "").replace(",", ""))
        if amount < 1:
            await message.answer("❌ Minimum $1 USDT:", reply_markup=cancel_deposit_kb())
            return
    except ValueError:
        await message.answer("❌ Enter a number like `5`:", parse_mode="Markdown")
        return

    rate = await get_setting("crypto_exchange_rate", 83.0)
    usdt_network = await get_setting("usdt_network", "TRC20")
    usdt_address = await get_setting("usdt_address", "")
    inr_value = amount * rate
    await state.update_data(crypto_amount=amount, crypto_inr=inr_value)

    await message.answer(
        f"💎 *USDT Deposit*\n\n"
        f"💰 *Amount:* `${amount:.2f} USDT`\n"
        f"🇮🇳 *Credit Value:* `₹{inr_value:.2f}`\n"
        f"🌐 *Network:* {usdt_network}\n\n"
        f"📋 *Send to this address:*\n"
        f"`{usdt_address}`\n\n"
        f"⚠️ *Important:*\n"
        f"• Send exactly `${amount:.2f}` USDT\n"
        f"• Use *{usdt_network}* network only!\n"
        f"• Wrong network = lost funds\n\n"
        f"✅ After sending, paste your *Transaction Hash (TxID):*",
        reply_markup=cancel_deposit_kb(), parse_mode="Markdown"
    )
    await state.set_state(DepositCrypto.waiting_txhash)


@router.message(DepositCrypto.waiting_txhash)
async def process_crypto_txhash(message: Message, state: FSMContext):
    txhash = message.text.strip()
    if len(txhash) < 10:
        await message.answer("❌ Invalid TxHash. Paste a valid transaction hash:")
        return

    data = await state.get_data()
    amount = data.get("crypto_amount", 0)
    rate = await get_setting("crypto_exchange_rate", 83.0)
    inr_value = data.get("crypto_inr", amount * rate)
    usdt_address = await get_setting("usdt_address", "")
    auto_crypto = await get_setting("auto_approve_crypto", True)

    request_id = generate_request_id()
    user_id = message.from_user.id
    db = get_db()

    existing = await db.deposits.find_one({"utr": txhash, "status": {"$in": ["pending", "approved"]}})
    if existing:
        await message.answer("❌ This TxID already submitted!", reply_markup=after_deposit_kb())
        await state.clear()
        return

    processing_msg = await message.answer(
        f"⏳ *Verifying on blockchain...*\n`{txhash[:20]}...`",
        parse_mode="Markdown"
    )

    if auto_crypto and usdt_address:
        result = await verify_trc20_transaction(txhash, usdt_address, amount)

        if result.get("verified"):
            actual_amount = result.get("amount", amount)
            actual_inr = actual_amount * rate

            await db.deposits.insert_one({
                "request_id": request_id, "user_id": user_id,
                "amount": actual_inr, "method": "crypto",
                "utr": txhash, "status": "approved",
                "created_at": datetime.utcnow(),
                "verified_at": datetime.utcnow(),
                "verified_by": "blockchain_auto",
                "usdt_amount": actual_amount,
            })
            new_balance = await add_balance(user_id, actual_inr, reason=f"usdt_deposit_{request_id}")
            await apply_referral_deposit_bonus(user_id, actual_inr)
            await log_event(user_id, "deposit_approved", {
                "method": "crypto", "usdt": actual_amount, "inr": actual_inr, "txhash": txhash
            })
            await processing_msg.delete()
            await message.answer(
                f"✅ *USDT Deposit Verified!*\n\n"
                f"💎 *USDT:* `${actual_amount:.2f}`\n"
                f"🇮🇳 *Added:* `₹{actual_inr:.2f}`\n"
                f"💰 *New Balance:* `₹{new_balance:.2f}`\n"
                f"🆔 *Request ID:* `{request_id}`\n\n"
                f"⚡ Verified via blockchain!",
                parse_mode="Markdown", reply_markup=after_deposit_kb()
            )
        else:
            error = result.get("error", "Unknown error")
            await db.deposits.insert_one({
                "request_id": request_id, "user_id": user_id,
                "amount": inr_value, "method": "crypto",
                "utr": txhash, "status": "pending",
                "created_at": datetime.utcnow(), "verify_error": error,
            })
            await log_event(user_id, "deposit_pending", {"method": "crypto", "error": error})
            deposit_doc = await db.deposits.find_one({"request_id": request_id})
            deposit_id = str(deposit_doc["_id"])
            from bot.keyboards.admin import deposit_approve_kb
            await processing_msg.delete()
            await message.answer(
                f"⚠️ *Auto-Verify Pending*\n\n"
                f"Could not auto-verify: `{error}`\n\n"
                f"💰 `${amount:.2f} USDT` → `₹{inr_value:.2f}`\n"
                f"🆔 `{request_id}`\n\n"
                f"⏳ Admin will verify shortly.",
                parse_mode="Markdown", reply_markup=after_deposit_kb()
            )
            for admin_id in await get_all_admin_ids():
                try:
                    await message.bot.send_message(
                        admin_id,
                        f"💎 *USDT Deposit (verify failed)*\n"
                        f"👤 `{user_id}`\n"
                        f"💰 ${amount:.2f} → ₹{inr_value:.2f}\n"
                        f"TxID: `{txhash}`\n"
                        f"Error: {error}",
                        reply_markup=deposit_approve_kb(deposit_id, user_id),
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
    else:
        await db.deposits.insert_one({
            "request_id": request_id, "user_id": user_id,
            "amount": inr_value, "method": "crypto",
            "utr": txhash, "status": "pending",
            "created_at": datetime.utcnow(),
        })
        await log_event(user_id, "deposit_pending", {"method": "crypto", "amount": inr_value})
        deposit_doc = await db.deposits.find_one({"request_id": request_id})
        deposit_id = str(deposit_doc["_id"])
        from bot.keyboards.admin import deposit_approve_kb
        await processing_msg.delete()
        await message.answer(
            f"💎 *Crypto Deposit Received*\n\n"
            f"💰 `${amount:.2f} USDT` → `₹{inr_value:.2f}`\n"
            f"🆔 `{request_id}`\n\n"
            f"⏳ Admin verifying...",
            parse_mode="Markdown", reply_markup=after_deposit_kb()
        )
        for admin_id in await get_all_admin_ids():
            try:
                await message.bot.send_message(
                    admin_id,
                    f"💎 *New USDT Deposit*\n"
                    f"👤 `{user_id}`\n"
                    f"💰 ${amount:.2f} → ₹{inr_value:.2f}\n"
                    f"TxID: `{txhash}`",
                    reply_markup=deposit_approve_kb(deposit_id, user_id),
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    await state.clear()
