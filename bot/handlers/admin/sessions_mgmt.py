import os
import re
import zipfile
import io
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from datetime import datetime

from bot.database import get_db
from bot.keyboards.admin import admin_back_kb, cancel_admin_kb, prices_kb
from bot.states.states import AdminStates
from bot.utils.helpers import is_any_admin

router = Router()


# ─── helpers ─────────────────────────────────────────────────────────────────

def _phone_from_filename(name: str) -> str:
    """Extract phone number from session filename like '918511982372.session'"""
    base = os.path.splitext(os.path.basename(name))[0]
    digits = re.sub(r'[^\d]', '', base)
    if len(digits) >= 10:
        return f"+{digits}"
    return base


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


# ─── Upload Sessions ZIP ──────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_upload_zip")
async def cb_upload_zip(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return

    db = get_db()
    countries = await db.countries.find({"is_active": True}).sort("name", 1).to_list(100)

    if not countries:
        await callback.message.edit_text(
            "❌ *No Active Countries*\n\n"
            "Add a country first via ➕ Add Country, then upload sessions.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Add Country", callback_data="admin_add_country")],
                [InlineKeyboardButton(text="◀️ Back", callback_data="admin_panel")],
            ]),
            parse_mode="Markdown"
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "📤 *Upload Sessions*\n\n"
        "Select the country for these sessions:",
        reply_markup=countries_grid_kb(countries, "zip_country"),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("zip_country:"))
async def cb_zip_country_selected(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    country_code = callback.data.split(":")[1]

    db = get_db()
    country = await db.countries.find_one({"code": country_code})
    country_name = country["name"] if country else country_code
    country_flag = country.get("flag", "") if country else ""
    current_stock = await db.sessions.count_documents({"country_code": country_code, "is_available": True})

    await state.update_data(zip_country=country_code, zip_country_name=country_name, zip_country_flag=country_flag)
    await state.set_state(AdminStates.upload_zip)

    await callback.message.edit_text(
        f"📤 *Upload — {country_flag} {country_name}*\n\n"
        f"📦 *Current Stock:* `{current_stock}` sessions\n\n"
        f"Send a `.zip` file containing your `.session` files.\n"
        f"Phone numbers are read from filenames automatically.\n"
        f"_(e.g. `918511982372.session` → +918511982372)_",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Back", callback_data="admin_upload_zip")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.upload_zip, F.document)
async def process_zip_upload_handler(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return

    data = await state.get_data()
    country_code = data.get("zip_country", "")
    country_name = data.get("zip_country_name", country_code)
    country_flag = data.get("zip_country_flag", "")

    doc = message.document
    if not (doc.file_name or "").endswith(".zip"):
        await message.answer("❌ Please send a `.zip` file.")
        return

    processing_msg = await message.answer(
        f"⏳ *Reading ZIP...*\n\n"
        f"Loading sessions for {country_flag} *{country_name}*...",
        parse_mode="Markdown"
    )

    file = await message.bot.get_file(doc.file_id)
    file_bytes_io = await message.bot.download_file(file.file_path)
    zip_bytes = file_bytes_io.read()

    db = get_db()
    country = await db.countries.find_one({"code": country_code})
    if not country:
        await processing_msg.edit_text("❌ Country not found in database.")
        return

    # — Extract session names from zip
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            session_names = [n for n in zf.namelist() if n.endswith(".session")]
    except Exception as e:
        await processing_msg.edit_text(f"❌ Cannot read ZIP: `{e}`", parse_mode="Markdown")
        return

    if not session_names:
        await processing_msg.edit_text(
            f"⚠️ *No .session Files Found*\n\n"
            f"The ZIP contains no `.session` files.\n"
            f"Make sure your zip has files like `918511982372.session`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Back", callback_data="admin_upload_zip")]
            ])
        )
        await state.clear()
        return

    await processing_msg.edit_text(
        f"⏳ *Processing {len(session_names)} sessions...*\n\n"
        f"Country: {country_flag} *{country_name}*",
        parse_mode="Markdown"
    )

    added = 0
    skipped = 0
    errors = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in session_names:
            try:
                session_bytes = zf.read(name)
                phone = _phone_from_filename(name)

                # Check duplicate
                existing = await db.sessions.find_one({"phone_number": phone})
                if existing:
                    skipped += 1
                    continue

                await db.sessions.insert_one({
                    "country": country["name"],
                    "country_code": country_code,
                    "country_flag": country.get("flag", ""),
                    "phone_number": phone,
                    "session_data": session_bytes,
                    "two_fa_password": "",
                    "is_available": True,
                    "added_at": datetime.utcnow(),
                    "added_by": message.from_user.id,
                    "zip_name": name,
                })
                added += 1

            except Exception as e:
                errors.append(f"{name}: {str(e)[:60]}")

    if added == 0:
        current_stock = await db.sessions.count_documents({"country_code": country_code, "is_available": True})
        err_text = ("\n⚠️ *Errors:*\n" + "\n".join(f"• `{e}`" for e in errors[:3])) if errors else ""
        await processing_msg.edit_text(
            f"⚠️ *No New Sessions Added*\n\n"
            f"Found `{len(session_names)}` files — all were duplicates or invalid.\n"
            f"📦 Current stock: `{current_stock}`\n"
            f"🔄 Skipped (duplicates): `{skipped}`" + err_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Try Again", callback_data="admin_upload_zip")]
            ])
        )
        await state.clear()
        return

    # Save results for password step
    await state.update_data(zip_added=added, zip_skipped=skipped, zip_errors=errors)

    await processing_msg.edit_text(
        f"✅ *{added} Sessions Stored!*\n\n"
        f"🌎 *Country:* {country_flag} {country_name}\n"
        f"✅ *Added:* `{added}`\n"
        f"🔄 *Skipped (dup):* `{skipped}`\n\n"
        f"🔐 *Set 2FA Password for these sessions*\n"
        f"If all sessions share a common password, enter it now.\n"
        f"_(Or tap Skip if no password)_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Skip — No Password", callback_data="zip_password_skip")]
        ])
    )
    await state.set_state(AdminStates.waiting_zip_password)


@router.callback_query(F.data == "zip_password_skip")
async def cb_zip_password_skip(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    await _finish_zip_upload(callback.message, state, password="")
    await callback.answer()


@router.message(AdminStates.waiting_zip_password)
async def process_zip_password(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    password = message.text.strip()
    if password.lower() in ("none", "skip", "-", "no"):
        password = ""
    await _finish_zip_upload(message, state, password=password)


async def _finish_zip_upload(message_or_msg, state: FSMContext, password: str):
    data = await state.get_data()
    country_code = data.get("zip_country", "")
    country_name = data.get("zip_country_name", country_code)
    country_flag = data.get("zip_country_flag", "")
    added = data.get("zip_added", 0)
    skipped = data.get("zip_skipped", 0)
    errors = data.get("zip_errors", [])

    if password and added > 0:
        db = get_db()
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(minutes=30)
        await db.sessions.update_many(
            {"country_code": country_code, "two_fa_password": "", "added_at": {"$gte": cutoff}},
            {"$set": {"two_fa_password": password}}
        )

    db = get_db()
    current_stock = await db.sessions.count_documents({"country_code": country_code, "is_available": True})
    password_status = f"`{password}`" if password else "_None_"

    result_text = (
        f"✅ *Upload Complete!*\n\n"
        f"🌎 *Country:* {country_flag} {country_name}\n"
        f"✅ *Added:* `{added}` sessions\n"
        f"🔄 *Skipped:* `{skipped}` (duplicates)\n"
        f"📦 *Total Stock Now:* `{current_stock}`\n"
        f"🔐 *2FA Password:* {password_status}\n"
    )
    if errors:
        result_text += f"\n⚠️ *Sample Errors:*\n"
        for err in errors[:3]:
            result_text += f"• `{err}`\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Upload More", callback_data="admin_upload_zip")],
        [InlineKeyboardButton(text="◀️ Back to Admin", callback_data="admin_panel")],
    ])

    try:
        if hasattr(message_or_msg, 'edit_text'):
            await message_or_msg.edit_text(result_text, reply_markup=kb, parse_mode="Markdown")
        else:
            await message_or_msg.answer(result_text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        pass
    await state.clear()


# ─── Manage Prices ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_manage_prices")
async def cb_manage_prices(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return

    db = get_db()
    countries = await db.countries.find({}).sort("name", 1).to_list(100)

    await callback.message.edit_text(
        "💰 *Manage Prices*\n\nTap a country to update its price:",
        reply_markup=prices_kb(countries), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_price:"))
async def cb_set_price(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    country_code = callback.data.split(":")[1]
    db = get_db()
    country = await db.countries.find_one({"code": country_code})
    name = f"{country.get('flag', '')} {country.get('name', country_code)}" if country else country_code
    current = country.get("price", 0) if country else 0
    await state.update_data(price_country=country_code)
    await state.set_state(AdminStates.set_price_value)
    await callback.message.edit_text(
        f"💰 *Set Price — {name}*\n\nCurrent: `₹{current:.2f}`\n\nEnter new price in ₹:",
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
            f"✅ *Price Updated!*\n\n`{country_code}` → `₹{price:.2f}`",
            reply_markup=admin_back_kb(), parse_mode="Markdown"
        )
    except ValueError:
        await message.answer("❌ Invalid price. Enter a number like `30`:")


@router.callback_query(F.data == "admin_bulk_price")
async def cb_bulk_price(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return
    await state.set_state(AdminStates.set_bulk_price)
    await callback.message.edit_text(
        "💰 *Bulk Set Prices*\n\n"
        "Enter one price to apply to ALL countries at once:\n"
        "_(e.g. `30`)_",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.set_bulk_price)
async def process_bulk_price(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    try:
        price = float(message.text.strip())
        db = get_db()
        result = await db.countries.update_many({}, {"$set": {"price": price}})
        await state.clear()
        await message.answer(
            f"✅ *Bulk Price Updated!*\n\n"
            f"All `{result.modified_count}` countries → `₹{price:.2f}`",
            reply_markup=admin_back_kb(), parse_mode="Markdown"
        )
    except ValueError:
        await message.answer("❌ Invalid. Enter a number like `30`:")


# ─── Add / Manage Countries ───────────────────────────────────────────────────

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
        "`PK|Pakistan|🇵🇰|25`\n\n"
        "_If the country code already exists, it will be updated._",
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
            {"code": code.upper()},
            {"$set": {"code": code.upper(), "name": name, "flag": flag, "price": price, "is_active": True}},
            upsert=True
        )
        await state.clear()
        await message.answer(
            f"✅ *Country Saved!*\n\n{flag} *{name}* (`{code.upper()}`) — `₹{price:.2f}`\n\n"
            f"Sessions can now be uploaded for this country.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📤 Upload Sessions", callback_data="admin_upload_zip")],
                [InlineKeyboardButton(text="◀️ Back to Admin", callback_data="admin_panel")],
            ]),
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(f"❌ Error: `{e}`", parse_mode="Markdown")


@router.callback_query(F.data == "admin_countries")
async def cb_admin_countries(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return
    db = get_db()
    countries = await db.countries.find({}).sort("name", 1).to_list(100)

    # Show stock per country
    lines = ["🌍 *Manage Countries*\n"]
    for c in countries:
        stock = await db.sessions.count_documents({"country_code": c["code"], "is_available": True})
        status = "✅" if c.get("is_active", True) else "❌"
        lines.append(f"{status} {c['flag']} *{c['name']}* — ₹{c['price']:.0f} — 📦 `{stock}`")

    text = "\n".join(lines) + "\n\n_Tap to toggle active/hidden_"

    from bot.keyboards.admin import countries_toggle_kb
    await callback.message.edit_text(
        text, reply_markup=countries_toggle_kb(countries), parse_mode="Markdown"
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
        status_text = "✅ Activated" if new_status else "❌ Hidden"
        await callback.answer(f"{status_text}: {country.get('name', country_code)}")
    countries = await db.countries.find({}).sort("name", 1).to_list(100)
    from bot.keyboards.admin import countries_toggle_kb
    await callback.message.edit_reply_markup(reply_markup=countries_toggle_kb(countries))


@router.callback_query(F.data == "admin_reset_countries")
async def cb_reset_countries_confirm(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return
    await callback.message.edit_text(
        "⚠️ *Reset All Countries?*\n\n"
        "This will *delete ALL countries and ALL sessions* from the database.\n"
        "You will need to re-add countries and re-upload sessions.\n\n"
        "⚠️ *This cannot be undone!*",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑️ YES — Delete Everything", callback_data="admin_reset_countries_confirm")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_panel")],
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_reset_countries_confirm")
async def cb_reset_countries_execute(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return
    db = get_db()
    c_result = await db.countries.delete_many({})
    s_result = await db.sessions.delete_many({})
    await callback.message.edit_text(
        f"🗑️ *Reset Complete!*\n\n"
        f"Countries deleted: `{c_result.deleted_count}`\n"
        f"Sessions deleted: `{s_result.deleted_count}`\n\n"
        f"Use ➕ Add Country to start fresh.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Add Country", callback_data="admin_add_country")],
            [InlineKeyboardButton(text="◀️ Back to Admin", callback_data="admin_panel")],
        ]),
        parse_mode="Markdown"
    )
    await callback.answer("✅ Reset done!")


@router.callback_query(F.data.startswith("delete_country:"))
async def cb_delete_country(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return
    country_code = callback.data.split(":")[1]
    db = get_db()
    country = await db.countries.find_one({"code": country_code})
    if not country:
        await callback.answer("Country not found.", show_alert=True)
        return
    session_count = await db.sessions.count_documents({"country_code": country_code})
    await callback.message.edit_text(
        f"🗑️ *Delete Country?*\n\n"
        f"{country.get('flag', '')} *{country.get('name', '')}* (`{country_code}`)\n"
        f"📦 Sessions that will be deleted: `{session_count}`\n\n"
        f"⚠️ This cannot be undone!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑️ YES — Delete", callback_data=f"delete_country_confirm:{country_code}")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_countries")],
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delete_country_confirm:"))
async def cb_delete_country_confirm(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return
    country_code = callback.data.split(":")[1]
    db = get_db()
    c_result = await db.countries.delete_one({"code": country_code})
    s_result = await db.sessions.delete_many({"country_code": country_code})
    await callback.message.edit_text(
        f"✅ *Country Deleted!*\n\n"
        f"`{country_code}` removed\n"
        f"Sessions deleted: `{s_result.deleted_count}`",
        reply_markup=admin_back_kb(), parse_mode="Markdown"
    )
    await callback.answer("✅ Deleted!")
