import io
import zipfile
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from aiogram.fsm.context import FSMContext

from bot.database import get_db
from bot.keyboards.main_menu import back_to_main_kb
from bot.services.session_service import get_available_countries, get_country_info
from bot.services.wallet_service import deduct_balance
from bot.states.states import BulkBuyState
from bot.utils.helpers import log_event
from datetime import datetime

router = Router()


def bulk_countries_kb(countries):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = []
    for i in range(0, len(countries), 2):
        row = []
        for c in countries[i:i+2]:
            row.append(InlineKeyboardButton(
                text=f"{c['flag']} {c['name']} — ₹{c['price']:.0f}",
                callback_data=f"bulk_country:{c['code']}"
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="◀️ Back to Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bulk_qty_kb(country_code: str, max_qty: int):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    qty_options = [1, 5, 10, 25, 50]
    rows = []
    row = []
    for qty in qty_options:
        if qty <= max_qty:
            row.append(InlineKeyboardButton(
                text=f"{qty}", callback_data=f"bulk_qty:{country_code}:{qty}"
            ))
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="✏️ Custom Quantity", callback_data=f"bulk_custom:{country_code}")])
    rows.append([InlineKeyboardButton(text="◀️ Back", callback_data="get_sessions")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "get_sessions")
async def cb_get_sessions(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    countries = await get_available_countries()
    in_stock = [c for c in countries if c["stock"] > 0]

    if not in_stock:
        await callback.message.edit_text(
            "😔 *No Sessions Available*\n\nAll stock is empty. Check back soon!",
            reply_markup=back_to_main_kb(), parse_mode="Markdown"
        )
        await callback.answer()
        return

    lines = ["📦 *Bulk Sessions*"]
    for c in in_stock:
        lines.append(
            f"\n{c['flag']} *{c['name']}*\n"
            f"📦 Stock: {c['stock']}  •  💰 Price: ₹{c['price']:.2f}"
        )
    lines.append("\n\n👇 *Select a country to purchase:*")
    text = "\n".join(lines)

    try:
        await callback.message.edit_text(text, reply_markup=bulk_countries_kb(in_stock), parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text, reply_markup=bulk_countries_kb(in_stock), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("bulk_country:"))
async def cb_bulk_country(callback: CallbackQuery, state: FSMContext, db_user: dict = None):
    country_code = callback.data.split(":")[1]
    country = await get_country_info(country_code)

    if not country or country["stock"] == 0:
        await callback.answer("❌ Out of stock!", show_alert=True)
        return

    balance = float(db_user.get("balance", 0.0)) if db_user else 0.0
    max_can_buy = min(country["stock"], int(balance // country["price"]))

    if max_can_buy == 0:
        await callback.message.edit_text(
            f"❌ *Insufficient Balance*\n\n"
            f"💰 Price per session: `₹{country['price']:.2f}`\n"
            f"💎 Your balance: `₹{balance:.2f}`\n\n"
            f"Deposit funds to buy sessions.",
            reply_markup=back_to_main_kb(), parse_mode="Markdown"
        )
        await callback.answer()
        return

    text = (
        f"📦 *{country['flag']} {country['name']} Sessions*\n\n"
        f"📦 *Stock Available:* `{country['stock']}`\n"
        f"💰 *Price Per Session:* `₹{country['price']:.2f}`\n"
        f"💎 *Your Balance:* `₹{balance:.2f}`\n"
        f"🔢 *Max You Can Buy:* `{max_can_buy}`\n\n"
        f"📁 You'll receive a *ZIP file* with all .session files\n"
        f"🤖 Use them in your own session OTP bot\n\n"
        f"👇 Select quantity:"
    )
    await callback.message.edit_text(text, reply_markup=bulk_qty_kb(country_code, max_can_buy), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("bulk_qty:"))
async def cb_bulk_qty(callback: CallbackQuery, state: FSMContext, db_user: dict = None):
    parts = callback.data.split(":")
    country_code = parts[1]
    qty = int(parts[2])
    await _process_bulk_purchase(callback, state, db_user, country_code, qty)


@router.callback_query(F.data.startswith("bulk_custom:"))
async def cb_bulk_custom(callback: CallbackQuery, state: FSMContext):
    country_code = callback.data.split(":")[1]
    await state.update_data(bulk_country=country_code)
    await state.set_state(BulkBuyState.waiting_qty)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await callback.message.edit_text(
        "✏️ Enter the quantity you want to buy:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="get_sessions")]
        ])
    )
    await callback.answer()


@router.message(BulkBuyState.waiting_qty)
async def process_bulk_qty_msg(message: Message, state: FSMContext, db_user: dict = None):
    try:
        qty = int(message.text.strip())
        if qty < 1:
            await message.answer("❌ Minimum 1. Enter a valid number:")
            return
    except ValueError:
        await message.answer("❌ Invalid number. Enter a valid quantity:")
        return

    data = await state.get_data()
    country_code = data.get("bulk_country")

    class FakeCallback:
        def __init__(self, msg, user_id):
            self.message = msg
            self.from_user = type('obj', (object,), {'id': user_id})()
            self.bot = msg.bot
        async def answer(self, *a, **kw): pass

    await _process_bulk_purchase(FakeCallback(message, message.from_user.id), state, db_user, country_code, qty)


async def _process_bulk_purchase(callback, state: FSMContext, db_user, country_code: str, qty: int):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    user_id = callback.from_user.id
    country = await get_country_info(country_code)

    if not country:
        await callback.message.answer("❌ Country not found.")
        return

    if qty > country["stock"]:
        await callback.message.answer(
            f"❌ Only `{country['stock']}` sessions available. Choose a lower quantity.",
            parse_mode="Markdown"
        )
        return

    total_cost = country["price"] * qty
    balance = float(db_user.get("balance", 0.0)) if db_user else 0.0

    if balance < total_cost:
        needed = total_cost - balance
        await callback.message.answer(
            f"❌ *Insufficient Balance*\n\n"
            f"🔢 Quantity: {qty}\n"
            f"💰 Total Cost: `₹{total_cost:.2f}`\n"
            f"💎 Your Balance: `₹{balance:.2f}`\n"
            f"⚠️ Need `₹{needed:.2f}` more",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 Deposit", callback_data="deposit")],
                [InlineKeyboardButton(text="◀️ Back", callback_data="get_sessions")]
            ]),
            parse_mode="Markdown"
        )
        return

    processing_msg = await callback.message.answer(
        f"⏳ *Processing bulk purchase...*\n"
        f"🔢 Picking {qty} sessions for {country['flag']} {country['name']}...",
        parse_mode="Markdown"
    )

    db = get_db()
    sessions = await db.sessions.find(
        {"country_code": country_code, "is_available": True}
    ).limit(qty).to_list(qty)

    if len(sessions) < qty:
        await processing_msg.edit_text(
            f"❌ Only `{len(sessions)}` sessions available now. Please try with a lower quantity.",
            parse_mode="Markdown"
        )
        return

    session_ids = [s["_id"] for s in sessions]
    await db.sessions.update_many(
        {"_id": {"$in": session_ids}},
        {"$set": {"is_available": False, "sold_to": user_id, "sold_at": datetime.utcnow()}}
    )

    deducted = await deduct_balance(user_id, total_cost)
    if not deducted:
        await db.sessions.update_many(
            {"_id": {"$in": session_ids}},
            {"$set": {"is_available": True, "sold_to": None, "sold_at": None}}
        )
        await processing_msg.edit_text("❌ Balance deduction failed. Try again.")
        return

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, s in enumerate(sessions, 1):
            phone = s.get("phone_number", f"unknown_{i}").replace("+", "")
            session_bytes = s.get("session_data", b"")
            if session_bytes:
                zf.writestr(f"{phone}.session", session_bytes)
    zip_buffer.seek(0)

    purchase_record = {
        "user_id": user_id,
        "country": country["name"],
        "country_code": country_code,
        "country_flag": country.get("flag", ""),
        "quantity": qty,
        "amount": total_cost,
        "session_ids": session_ids,
        "phone_numbers": [s.get("phone_number") for s in sessions],
        "status": "bulk_delivered",
        "type": "bulk",
        "created_at": datetime.utcnow(),
    }
    await db.purchases.insert_one(purchase_record)
    await db.users.update_one(
        {"telegram_id": user_id},
        {"$inc": {"total_purchases": qty, "total_spent": total_cost}}
    )

    await log_event(user_id, "bulk_purchase", {
        "country": country_code,
        "qty": qty,
        "amount": total_cost,
        "phones": [s.get("phone_number") for s in sessions]
    })

    try:
        await processing_msg.delete()
    except Exception:
        pass

    zip_file = BufferedInputFile(zip_buffer.read(), filename=f"{country_code}_{qty}_sessions.zip")
    await callback.message.answer_document(
        document=zip_file,
        caption=(
            f"✅ *Bulk Sessions Delivered!*\n\n"
            f"🌎 *Country:* {country['flag']} *{country['name']}*\n"
            f"📦 *Sessions:* `{qty}`\n"
            f"💰 *Total Paid:* `₹{total_cost:.2f}`\n\n"
            f"📁 Extract the ZIP and use `.session` files\n"
            f"in your session OTP bot one by one! 🚀"
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Buy More", callback_data="get_sessions")],
            [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")],
        ]),
        parse_mode="Markdown"
    )

    await state.clear()
