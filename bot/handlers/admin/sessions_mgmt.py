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

    await callback.message.edit_text(
        "📂 *Upload Sessions*\n\nChoose a country to upload sessions for:",
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
        f"📂 *Upload Sessions — {country_flag} {country_name}*\n\n"
        f"📦 *Current Stock:* `{current_stock}` sessions\n\n"
        f"Send a `.zip` file containing your `.session` files.\n"
        f"Each file will be verified and added to inventory.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Back to Countries", callback_data="admin_upload_zip")]
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
    if not doc.file_name.endswith(".zip"):
        await message.answer("❌ Please send a `.zip` file.")
        return

    processing_msg = await message.answer(
        f"⏳ *Processing ZIP...*\n\n"
        f"Scanning for {country_flag} *{country_name}* sessions...",
        parse_mode="Markdown"
    )

    file = await message.bot.get_file(doc.file_id)
    file_bytes_io = await message.bot.download_file(file.file_path)
    zip_bytes = file_bytes_io.read()

    import zipfile, io, tempfile, os
    from telethon import TelegramClient
    from bot.config import TELEGRAM_API_ID, TELEGRAM_API_HASH
    from datetime import datetime

    db = get_db()
    country = await db.countries.find_one({"code": country_code})
    if not country:
        await processing_msg.edit_text("❌ Country not found in database.")
        return

    session_names = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            session_names = [n for n in zf.namelist() if n.endswith(".session")]
    except Exception as e:
        await processing_msg.edit_text(f"❌ Cannot read ZIP: `{e}`", parse_mode="Markdown")
        return

    if not session_names:
        current_stock = await db.sessions.count_documents({"country_code": country_code, "is_available": True})
        await processing_msg.edit_text(
            f"⚠️ *No .session Files Found!*\n\n"
            f"The ZIP has no `.session` files for *{country_name}*.\n"
            f"Current stock: `{current_stock}`",
            parse_mode="Markdown"
        )
        await state.clear()
        return

    await processing_msg.edit_text(
        f"⏳ *Processing Sessions...*\n\n"
        f"Found `{len(session_names)}` files for *{country_flag} {country_name}*.\n"
        f"Verifying and adding to inventory `(0/{len(session_names)})`...",
        parse_mode="Markdown"
    )

    added = 0
    failed = 0
    errors = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for idx, name in enumerate(session_names):
            try:
                if idx % 3 == 0 and idx > 0:
                    try:
                        await processing_msg.edit_text(
                            f"⏳ *Processing Sessions...*\n\n"
                            f"Found `{len(session_names)}` files for *{country_flag} {country_name}*.\n"
                            f"Verifying `({idx}/{len(session_names)})`...\n"
                            f"✅ Added: `{added}` | ❌ Failed: `{failed}`",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass

                session_bytes = zf.read(name)
                tmp_dir = tempfile.mkdtemp()
                session_path = os.path.join(tmp_dir, "temp")

                with open(session_path + ".session", "wb") as f:
                    f.write(session_bytes)

                client = TelegramClient(session_path, TELEGRAM_API_ID, TELEGRAM_API_HASH)
                await client.connect()
                phone = None
                if await client.is_user_authorized():
                    me = await client.get_me()
                    phone = f"+{me.phone}" if me and me.phone else None
                await client.disconnect()

                if not phone:
                    failed += 1
                    errors.append(f"{name}: not authorized")
                    continue

                existing = await db.sessions.find_one({"phone_number": phone})
                if existing:
                    failed += 1
                    errors.append(f"{name}: duplicate ({phone})")
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
                failed += 1
                errors.append(f"{name}: {str(e)[:50]}")
            finally:
                try:
                    os.remove(session_path + ".session")
                    os.rmdir(tmp_dir)
                except Exception:
                    pass

    await state.update_data(zip_added=added, zip_failed=failed, zip_errors=errors)

    if added == 0:
        current_stock = await db.sessions.count_documents({"country_code": country_code, "is_available": True})
        await processing_msg.edit_text(
            f"⚠️ *No Valid Sessions Found!*\n\n"
            f"No authorized sessions in ZIP for *{country_name}*.\n"
            f"Current stock: `{current_stock}`\n"
            f"❌ Failed: `{failed}`\n"
            + (f"\n*Errors:*\n" + "\n".join(f"• `{e}`" for e in errors[:3]) if errors else ""),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Back to Countries", callback_data="admin_upload_zip")]
            ])
        )
        await state.clear()
        return

    await processing_msg.edit_text(
        f"🔐 *Set Session Password*\n\n"
        f"✅ Added `{added}` sessions for {country_flag} *{country_name}*\n"
        f"❌ Failed: `{failed}`\n\n"
        f"Enter the *2FA password* for these sessions.\n"
        f"If no password, send `none` or tap Skip.",
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
    if password.lower() == "none":
        password = ""
    await _finish_zip_upload(message, state, password=password)


async def _finish_zip_upload(message_or_msg, state: FSMContext, password: str):
    data = await state.get_data()
    country_code = data.get("zip_country", "")
    country_name = data.get("zip_country_name", country_code)
    country_flag = data.get("zip_country_flag", "")
    added = data.get("zip_added", 0)
    failed = data.get("zip_failed", 0)
    errors = data.get("zip_errors", [])

    if password and added > 0:
        from datetime import datetime, timedelta
        db = get_db()
        cutoff = datetime.utcnow() - timedelta(minutes=15)
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
        f"❌ *Failed:* `{failed}` sessions\n"
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


@router.callback_query(F.data == "admin_manage_prices")
async def cb_manage_prices(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return

    db = get_db()
    countries = await db.countries.find({}).to_list(100)

    await callback.message.edit_text(
        "💰 *Manage Prices*\n\nTap a country to update its price:\n_Or use Bulk Set to update all at once._",
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
    await state.update_data(price_country=country_code)
    await state.set_state(AdminStates.set_price_value)
    await callback.message.edit_text(
        f"💰 *Set Price — {name}*\n\nEnter new price in ₹:",
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
        await message.answer("❌ Invalid price. Enter a number:")


@router.callback_query(F.data == "admin_bulk_price")
async def cb_bulk_price(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return
    await state.set_state(AdminStates.set_bulk_price)
    await callback.message.edit_text(
        "💰 *Bulk Set Prices*\n\n"
        "Set a price for ALL countries at once.\n\n"
        "Enter a single price in ₹ that will apply to every country:",
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
            f"All `{result.modified_count}` countries set to `₹{price:.2f}`",
            reply_markup=admin_back_kb(), parse_mode="Markdown"
        )
    except ValueError:
        await message.answer("❌ Invalid price. Enter a number like `30`:")


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
        "`US|USA|🇺🇸|50`",
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
            f"✅ *Country Saved!*\n\n{flag} *{name}* (`{code}`) — `₹{price:.2f}`",
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
        "🌍 *Manage Countries*\n\n✅ = Active  •  ❌ = Hidden\nTap to toggle:",
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
