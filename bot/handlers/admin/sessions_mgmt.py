import asyncio
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from bot.database import get_db
from bot.keyboards.admin import admin_back_kb, cancel_admin_kb, prices_kb
from bot.states.states import AdminStates
from bot.utils.helpers import is_any_admin

router = Router()


def countries_grid_kb(countries: list, action: str = "zip_country") -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(countries), 2):
        row = []
        for c in countries[i:i+2]:
            row.append(InlineKeyboardButton(
                text=f"{c['flag']} {c['name']}",
                callback_data=f"{action}:{c['code']}"
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="◀️ Back", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─────────────────────────────────────────────────────────────
#  STEP 1: Admin selects country for upload
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_upload_zip")
async def cb_upload_zip(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return

    db = get_db()
    countries = await db.countries.find({"is_active": True}).to_list(100)

    if not countries:
        await callback.message.edit_text(
            "❌ No active countries.\n\nAdd countries first via ➕ Add Country.",
            reply_markup=admin_back_kb(), parse_mode="Markdown"
        )
        await callback.answer()
        return

    from bot.services.session_service import session_pool
    pool_stats = session_pool.get_stats()

    lines = ["📂 *Upload Sessions*\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n*Live Stock (pool):*\n"]
    for c in countries:
        code = c["code"]
        st = pool_stats.get(code, {})
        available = st.get("available", 0)
        total = st.get("total", 0)
        lines.append(f"• {c.get('flag', '')} *{c['name']}* — {available} available / {total} total")

    lines.append("\n\n👇 *Select country to upload sessions for:*")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=countries_grid_kb(countries, "zip_country"),
        parse_mode="Markdown"
    )
    await callback.answer()


# ─────────────────────────────────────────────────────────────
#  STEP 2: Admin picks country
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("zip_country:"))
async def cb_zip_country_selected(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    country_code = callback.data.split(":")[1]

    db = get_db()
    country = await db.countries.find_one({"code": country_code})
    country_name = country["name"] if country else country_code
    country_flag = country.get("flag", "") if country else ""

    from bot.services.session_service import session_pool
    live_count = session_pool.available_count(country_code)

    await state.update_data(
        zip_country=country_code,
        zip_country_name=country_name,
        zip_country_flag=country_flag,
    )
    await state.set_state(AdminStates.upload_zip)

    await callback.message.edit_text(
        f"📂 *Upload Sessions — {country_flag} {country_name}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔌 Live in Pool: `{live_count}` sessions connected\n\n"
        f"Send the `.zip` file containing `.session` files.\n\n"
        f"_Each session will be:_\n"
        f"_1. Verified (Telethon login check)_\n"
        f"_2. Saved to database_\n"
        f"_3. Immediately connected to pool_\n\n"
        f"_Members buying will get instant OTP delivery!_",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Back to Countries", callback_data="admin_upload_zip")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()


# ─────────────────────────────────────────────────────────────
#  STEP 3: Admin sends ZIP file
# ─────────────────────────────────────────────────────────────

@router.message(AdminStates.upload_zip, F.document)
async def process_zip_upload_handler(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return

    data = await state.get_data()
    country_code = data.get("zip_country", "")
    country_name = data.get("zip_country_name", country_code)
    country_flag = data.get("zip_country_flag", "")

    doc = message.document
    if not doc.file_name.endswith(".zip"):
        await message.answer(
            "❌ Please send a `.zip` file only.\n"
            "Pack all `.session` files into a `.zip` archive.",
            parse_mode="Markdown"
        )
        return

    processing_msg = await message.answer(
        f"⏳ *Downloading ZIP...*\n\n"
        f"Country: {country_flag} *{country_name}*",
        parse_mode="Markdown"
    )

    file = await message.bot.get_file(doc.file_id)
    file_bytes_io = await message.bot.download_file(file.file_path)
    zip_bytes = file_bytes_io.read()

    # Count sessions in ZIP
    import zipfile, io as _io
    try:
        with zipfile.ZipFile(_io.BytesIO(zip_bytes)) as zf:
            total_files = len([n for n in zf.namelist() if n.endswith(".session")])
    except Exception as e:
        await processing_msg.edit_text(f"❌ Cannot read ZIP: `{e}`", parse_mode="Markdown")
        await state.clear()
        return

    if total_files == 0:
        await processing_msg.edit_text(
            f"⚠️ *No .session Files in ZIP!*\n\n"
            f"Make sure your ZIP contains `.session` files directly.",
            parse_mode="Markdown"
        )
        await state.clear()
        return

    await state.update_data(zip_bytes_cached=False, zip_total=total_files)

    # Ask for 2FA password before starting upload
    await processing_msg.edit_text(
        f"✅ *ZIP Found: {total_files} session files*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔐 *Enter 2FA Password* for these sessions:\n\n"
        f"_If no 2FA password, type `none` or press Skip._",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Skip — No Password", callback_data="zip_password_skip")]
        ]),
        parse_mode="Markdown"
    )

    # Cache zip bytes temporarily in state
    # (aiogram state has size limits — we store in memory dict keyed by user id)
    _pending_zips[message.from_user.id] = zip_bytes
    await state.set_state(AdminStates.waiting_zip_password)


# In-memory temp storage for zip bytes between FSM steps
_pending_zips: dict = {}


@router.callback_query(F.data == "zip_password_skip")
async def cb_zip_password_skip(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    await _start_upload(callback.message, state, callback.from_user.id, password="")
    await callback.answer()


@router.message(AdminStates.waiting_zip_password)
async def process_zip_password(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    password = message.text.strip()
    if password.lower() == "none":
        password = ""
    await _start_upload(message, state, message.from_user.id, password=password)


async def _start_upload(msg_or_cb_msg, state: FSMContext, admin_id: int, password: str):
    data = await state.get_data()
    country_code = data.get("zip_country", "")
    country_name = data.get("zip_country_name", country_code)
    country_flag = data.get("zip_country_flag", "")
    total_files = data.get("zip_total", 0)

    zip_bytes = _pending_zips.pop(admin_id, None)
    if not zip_bytes:
        try:
            await msg_or_cb_msg.answer("❌ Session data lost. Please upload ZIP again.")
        except Exception:
            pass
        await state.clear()
        return

    password_display = f"`{password}`" if password else "_None (no 2FA)_"
    try:
        status_msg = await msg_or_cb_msg.answer(
            f"🔄 *Starting Upload + Login...*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🌎 Country: {country_flag} *{country_name}*\n"
            f"📦 Total Sessions: `{total_files}`\n"
            f"🔐 2FA Password: {password_display}\n\n"
            f"_Verifying, saving to DB, and connecting to pool..._\n"
            f"`(0 / {total_files})` ⏳",
            parse_mode="Markdown"
        )
    except Exception:
        status_msg = await msg_or_cb_msg.answer("⏳ Uploading sessions...")

    progress_counter = {"done": 0, "ok": 0, "fail": 0}

    async def _progress(done, total, ok, fail):
        progress_counter["done"] = done
        progress_counter["ok"] = ok
        progress_counter["fail"] = fail
        if done % 5 == 0 or done == total:
            try:
                pct = int((done / total) * 100) if total > 0 else 0
                bar_filled = int(pct / 10)
                bar = "█" * bar_filled + "░" * (10 - bar_filled)
                await status_msg.edit_text(
                    f"🔄 *Logging In Sessions...*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🌎 {country_flag} *{country_name}*\n"
                    f"|{bar}| `{pct}%`\n"
                    f"`({done} / {total})`\n\n"
                    f"✅ Connected: `{ok}` | ❌ Failed: `{fail}`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    # Run the actual upload + pool connect
    from bot.services.session_service import process_zip_and_connect
    result = await process_zip_and_connect(
        zip_bytes=zip_bytes,
        country_code=country_code,
        two_fa_password=password,
        added_by=admin_id,
        progress_callback=_progress,
    )

    await state.clear()

    from bot.services.session_service import session_pool
    live_count = session_pool.available_count(country_code)

    if not result.get("success"):
        await status_msg.edit_text(
            f"❌ *Upload Failed!*\n\n`{result.get('error', 'Unknown error')}`",
            reply_markup=admin_back_kb(),
            parse_mode="Markdown"
        )
        return

    added = result.get("added", 0)
    failed = result.get("failed", 0)
    errors = result.get("errors", [])

    result_text = (
        f"{'✅' if added > 0 else '⚠️'} *Upload Complete!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌎 Country: {country_flag} *{country_name}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Logged In & Ready: `{added}`\n"
        f"❌ Failed / Skipped: `{failed}`\n"
        f"📦 Total in Pool Now: `{live_count}` (live)\n"
        f"🔐 2FA Password: {password_display}\n"
    )
    if errors:
        result_text += f"\n⚠️ *Sample Errors:*\n"
        for err in errors[:5]:
            result_text += f"• `{err}`\n"

    result_text += f"\n_Sessions are now logged in and ready for buyers!_"

    await status_msg.edit_text(
        result_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Upload More", callback_data="admin_upload_zip")],
            [InlineKeyboardButton(text="🗂 View Pool Stats", callback_data="admin_view_sessions")],
            [InlineKeyboardButton(text="◀️ Back to Admin", callback_data="admin_panel")],
        ]),
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────────────────────────
#  Price management
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_manage_prices")
async def cb_manage_prices(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return

    db = get_db()
    countries = await db.countries.find({}).to_list(100)

    await callback.message.edit_text(
        "💰 *Manage Prices*\n━━━━━━━━━━━━━━━━━━━━━━━━\n\nTap a country to update price:",
        reply_markup=prices_kb(countries), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_price:"))
async def cb_set_price(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    country_code = callback.data.split(":")[1]
    await state.update_data(price_country=country_code)
    await state.set_state(AdminStates.set_price_value)
    await callback.message.edit_text(
        f"💰 Enter new price for `{country_code}` (in ₹):",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.set_price_value)
async def process_set_price(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    try:
        price = float(message.text.strip())
        data = await state.get_data()
        country_code = data.get("price_country")
        db = get_db()
        await db.countries.update_one({"code": country_code}, {"$set": {"price": price}})
        await state.clear()
        await message.answer(
            f"✅ Price updated: `{country_code}` → `₹{price:.2f}`",
            reply_markup=admin_back_kb(), parse_mode="Markdown"
        )
    except ValueError:
        await message.answer("❌ Invalid price. Enter a number:")


# ─────────────────────────────────────────────────────────────
#  Country management
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_add_country")
async def cb_add_country(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.add_country)
    await callback.message.edit_text(
        "🌍 *Add / Update Country*\n\n"
        "Format: `CODE|Name|Flag|Price`\n\n"
        "*Examples:*\n"
        "`IN|India|🇮🇳|30`\n"
        "`BD|Bangladesh|🇧🇩|28`\n"
        "`US|USA|🇺🇸|50`\n"
        "`PK|Pakistan|🇵🇰|25`\n"
        "`IN_2024|India [2024]|🇮🇳|35`\n"
        "`US_SP|USA (Special)|🇺🇸|55`",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.add_country)
async def process_add_country(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    try:
        parts = [p.strip() for p in message.text.strip().split("|")]
        if len(parts) != 4:
            await message.answer(
                "❌ Format: `CODE|Name|Flag|Price`\nExample: `IN|India|🇮🇳|30`",
                parse_mode="Markdown"
            )
            return
        code, name, flag, price = parts
        price = float(price)
        db = get_db()
        await db.countries.update_one(
            {"code": code},
            {"$set": {"code": code, "name": name, "flag": flag, "price": price, "is_active": True}},
            upsert=True
        )
        await state.clear()
        await message.answer(
            f"✅ Country saved:\n{flag} *{name}* (`{code}`) — `₹{price:.2f}`",
            reply_markup=admin_back_kb(), parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(f"❌ Error: `{e}`", parse_mode="Markdown")


@router.callback_query(F.data == "admin_countries")
async def cb_admin_countries(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return
    db = get_db()
    countries = await db.countries.find({}).to_list(100)
    from bot.keyboards.admin import countries_toggle_kb
    await callback.message.edit_text(
        "🌍 *Manage Countries*\n\n✅ = Active | ❌ = Hidden\nTap to toggle:",
        reply_markup=countries_toggle_kb(countries), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_country:"))
async def cb_toggle_country(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        return
    country_code = callback.data.split(":")[1]
    db = get_db()
    country = await db.countries.find_one({"code": country_code})
    if country:
        new_status = not country.get("is_active", True)
        await db.countries.update_one({"code": country_code}, {"$set": {"is_active": new_status}})
    countries = await db.countries.find({}).to_list(100)
    from bot.keyboards.admin import countries_toggle_kb
    await callback.message.edit_reply_markup(reply_markup=countries_toggle_kb(countries))
    await callback.answer("✅ Updated!")


# ─────────────────────────────────────────────────────────────
#  Session Pool: View & Clear
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_view_sessions")
async def cb_view_sessions(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return

    from bot.services.session_service import session_pool
    db = get_db()
    countries = await db.countries.find({}).to_list(100)
    pool_stats = session_pool.get_stats()

    lines = [
        "🗂 *Live Session Pool*",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🔌 Total Connected: `{session_pool.total}`\n",
    ]
    rows = []
    for c in countries:
        code = c["code"]
        st = pool_stats.get(code, {"available": 0, "occupied": 0, "total": 0})
        lines.append(
            f"{c.get('flag', '')} *{c['name']}*\n"
            f"  ✅ Available: `{st['available']}`  "
            f"🔄 In Use: `{st['occupied']}`  "
            f"📦 Total: `{st['total']}`"
        )
        rows.append([
            InlineKeyboardButton(
                text=f"🗑 Clear {c.get('flag', '')} {c['name']} ({st['available']} sessions)",
                callback_data=f"clear_sessions:{code}"
            )
        ])

    if not any(pool_stats.values()):
        lines.append("\n_No sessions currently in pool._\n_Upload sessions to get started._")

    rows.append([InlineKeyboardButton(text="🗑 Clear ALL Sessions", callback_data="clear_sessions:ALL")])
    rows.append([InlineKeyboardButton(text="◀️ Back", callback_data="admin_panel")])

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("clear_sessions:"))
async def cb_clear_sessions(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return

    from bot.services.session_service import session_pool
    country_code = callback.data.split(":")[1]
    db = get_db()

    if country_code == "ALL":
        await session_pool.clear_all()
        await db.sessions.update_many({"is_available": True}, {"$set": {"is_available": False}})
        await callback.answer("🗑 All sessions cleared from pool + DB.", show_alert=True)
    else:
        await session_pool.clear_country(country_code)
        await db.sessions.update_many(
            {"country_code": country_code, "is_available": True},
            {"$set": {"is_available": False}}
        )
        await callback.answer(f"🗑 {country_code} sessions cleared.", show_alert=True)

    await cb_view_sessions(callback)
