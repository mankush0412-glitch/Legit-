import os
import re
import zipfile
import io
import asyncio
import tempfile
from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from bot.database import get_db
from bot.keyboards.admin import admin_back_kb, cancel_admin_kb, prices_kb, countries_toggle_kb
from bot.states.states import AdminStates
from bot.utils.helpers import is_any_admin

router = Router()

# Max concurrent Telethon verify connections
_verify_semaphore = asyncio.Semaphore(8)

COUNTRY_FLAGS = {
    "IN":"🇮🇳","US":"🇺🇸","BD":"🇧🇩","PK":"🇵🇰","NG":"🇳🇬","ID":"🇮🇩","VN":"🇻🇳",
    "MM":"🇲🇲","KE":"🇰🇪","CO":"🇨🇴","ZW":"🇿🇼","GB":"🇬🇧","AU":"🇦🇺","CA":"🇨🇦",
    "BR":"🇧🇷","PH":"🇵🇭","EG":"🇪🇬","GH":"🇬🇭","TZ":"🇹🇿","ET":"🇪🇹","TR":"🇹🇷",
    "RU":"🇷🇺","DE":"🇩🇪","FR":"🇫🇷","IT":"🇮🇹","ES":"🇪🇸","MX":"🇲🇽","AR":"🇦🇷",
    "UM":"🇺🇲","TH":"🇹🇭","UA":"🇺🇦","SA":"🇸🇦","AE":"🇦🇪","JP":"🇯🇵","KR":"🇰🇷",
    "CN":"🇨🇳","IR":"🇮🇷","IQ":"🇮🇶","MA":"🇲🇦","DZ":"🇩🇿","LY":"🇱🇾","SD":"🇸🇩",
    "UZ":"🇺🇿","KZ":"🇰🇿","BY":"🇧🇾","AZ":"🇦🇿","GE":"🇬🇪","AF":"🇦🇫","NP":"🇳🇵",
    "LK":"🇱🇰","KH":"🇰🇭","LA":"🇱🇦","MY":"🇲🇾","SG":"🇸🇬","HK":"🇭🇰","TW":"🇹🇼",
}


def _phone_from_filename(name: str) -> str:
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


async def _verify_session(session_bytes: bytes, phone: str) -> bool:
    from bot.config import TELEGRAM_API_ID, TELEGRAM_API_HASH
    from telethon import TelegramClient
    from telethon.errors import (
        AuthKeyUnregisteredError, UserDeactivatedError,
        SessionRevokedError, AuthKeyDuplicatedError, PhoneNumberBannedError,
    )
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        return True
    tmp_dir = tempfile.mkdtemp()
    session_path = os.path.join(tmp_dir, "v")
    client = None
    async with _verify_semaphore:
        try:
            with open(session_path + ".session", "wb") as f:
                f.write(session_bytes)
            client = TelegramClient(
                session_path, TELEGRAM_API_ID, TELEGRAM_API_HASH,
                connection_retries=1, retry_delay=1, timeout=15,
            )
            await client.connect()
            return await client.is_user_authorized()
        except (AuthKeyUnregisteredError, SessionRevokedError,
                AuthKeyDuplicatedError, UserDeactivatedError, PhoneNumberBannedError):
            return False
        except Exception:
            return False
        finally:
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    pass
            for ext in [".session", ".session-journal"]:
                try:
                    sp = session_path + ext
                    if os.path.exists(sp):
                        os.remove(sp)
                except Exception:
                    pass
            try:
                os.rmdir(tmp_dir)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
#   COUNTRIES MANAGEMENT
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_countries")
async def cb_admin_countries(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return
    await state.clear()
    db = get_db()
    countries = await db.countries.find({}).sort("name", 1).to_list(100)

    if not countries:
        await callback.message.edit_text(
            "🌍 *Countries*\n\nNo countries added yet.\nUse ➕ Add Country to get started.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Add Country", callback_data="admin_add_country")],
                [InlineKeyboardButton(text="◀️ Back", callback_data="admin_panel")],
            ]),
            parse_mode="Markdown"
        )
        await callback.answer()
        return

    # Build stock summary per country
    lines = ["🌍 *Manage Countries*\n"]
    for c in countries:
        stock = await db.sessions.count_documents({"country_code": c["code"], "is_available": True})
        status = "✅" if c.get("is_active", True) else "❌"
        lines.append(f"{status} {c['flag']} *{c['name']}* — Stock: `{stock}` — ₹{c.get('price', 0):.0f}")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=countries_toggle_kb(countries),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_country:"))
async def cb_toggle_country(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        return
    code = callback.data.split(":")[1]
    db = get_db()
    country = await db.countries.find_one({"code": code})
    if not country:
        await callback.answer("❌ Country not found.", show_alert=True)
        return
    new_status = not country.get("is_active", True)
    await db.countries.update_one({"code": code}, {"$set": {"is_active": new_status}})
    status_text = "✅ Enabled" if new_status else "❌ Disabled"
    await callback.answer(f"{status_text}: {country['name']}")
    # Refresh the view
    countries = await db.countries.find({}).sort("name", 1).to_list(100)
    lines = ["🌍 *Manage Countries*\n"]
    for c in countries:
        stock = await db.sessions.count_documents({"country_code": c["code"], "is_available": True})
        status = "✅" if c.get("is_active", True) else "❌"
        lines.append(f"{status} {c['flag']} *{c['name']}* — Stock: `{stock}` — ₹{c.get('price', 0):.0f}")
    try:
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=countries_toggle_kb(countries),
            parse_mode="Markdown"
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("delete_country:"))
async def cb_delete_country(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        return
    code = callback.data.split(":")[1]
    db = get_db()
    country = await db.countries.find_one({"code": code})
    if not country:
        await callback.answer("❌ Country not found.", show_alert=True)
        return
    stock = await db.sessions.count_documents({"country_code": code, "is_available": True})
    await callback.message.edit_text(
        f"⚠️ *Delete Country — {country['flag']} {country['name']}?*\n\n"
        f"📦 Sessions in stock: `{stock}`\n\n"
        f"This will delete the country entry only.\n"
        f"_Sessions already in DB will remain but won't be purchasable._",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑️ Yes, Delete", callback_data=f"confirm_del_country:{code}"),
                InlineKeyboardButton(text="◀️ Cancel", callback_data="admin_countries"),
            ]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_del_country:"))
async def cb_confirm_del_country(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        return
    code = callback.data.split(":")[1]
    db = get_db()
    result = await db.countries.delete_one({"code": code})
    if result.deleted_count:
        await callback.answer(f"🗑️ Country {code} deleted.")
    else:
        await callback.answer("❌ Already deleted.")
    countries = await db.countries.find({}).sort("name", 1).to_list(100)
    if countries:
        lines = ["🌍 *Manage Countries*\n"]
        for c in countries:
            stock = await db.sessions.count_documents({"country_code": c["code"], "is_available": True})
            status = "✅" if c.get("is_active", True) else "❌"
            lines.append(f"{status} {c['flag']} *{c['name']}* — Stock: `{stock}` — ₹{c.get('price', 0):.0f}")
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=countries_toggle_kb(countries),
            parse_mode="Markdown"
        )
    else:
        await callback.message.edit_text(
            "🌍 *Countries*\n\nNo countries left.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Add Country", callback_data="admin_add_country")],
                [InlineKeyboardButton(text="◀️ Back", callback_data="admin_panel")],
            ]),
            parse_mode="Markdown"
        )


@router.callback_query(F.data == "admin_reset_countries")
async def cb_reset_countries(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        return
    await callback.message.edit_text(
        "⚠️ *Reset All Countries?*\n\n"
        "This will SET ALL countries to **Active** status.\n"
        "No countries or sessions will be deleted.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yes, Enable All", callback_data="confirm_reset_countries"),
                InlineKeyboardButton(text="◀️ Cancel", callback_data="admin_countries"),
            ]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "confirm_reset_countries")
async def cb_confirm_reset_countries(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        return
    db = get_db()
    await db.countries.update_many({}, {"$set": {"is_active": True}})
    await callback.answer("✅ All countries enabled!")
    countries = await db.countries.find({}).sort("name", 1).to_list(100)
    lines = ["🌍 *Manage Countries — All Enabled*\n"]
    for c in countries:
        stock = await db.sessions.count_documents({"country_code": c["code"], "is_available": True})
        lines.append(f"✅ {c['flag']} *{c['name']}* — Stock: `{stock}` — ₹{c.get('price', 0):.0f}")
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=countries_toggle_kb(countries),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "admin_add_country")
async def cb_add_country(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return
    await state.set_state(AdminStates.add_country)
    await callback.message.edit_text(
        "➕ *Add Country*\n\n"
        "Send country details in this format:\n\n"
        "`CODE, Name, Emoji, Price`\n\n"
        "Examples:\n"
        "`IN, India, 🇮🇳, 30`\n"
        "`US, USA, 🇺🇸, 50`\n"
        "`BD, Bangladesh, 🇧🇩, 25`\n"
        "`NG, Nigeria, 🇳🇬, 20`\n\n"
        "_Price is in ₹. Enter 0 for free._\n"
        "_Known country codes get flag auto-filled if you skip emoji._",
        reply_markup=cancel_admin_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.add_country)
async def process_add_country(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    text = message.text.strip()
    parts = [p.strip() for p in text.split(",")]

    if len(parts) < 3:
        await message.answer(
            "❌ Wrong format. Use: `CODE, Name, Emoji, Price`\n"
            "Example: `IN, India, 🇮🇳, 30`\n\n"
            "_At least CODE, Name, and Price are required._",
            parse_mode="Markdown"
        )
        return

    code = parts[0].upper()
    name = parts[1]

    # Handle optional emoji and price
    if len(parts) == 3:
        flag = COUNTRY_FLAGS.get(code, "🏳️")
        try:
            price = float(parts[2])
        except ValueError:
            # Maybe they gave emoji without price
            flag = parts[2] if parts[2] else COUNTRY_FLAGS.get(code, "🏳️")
            price = 0.0
    else:
        raw_flag = parts[2]
        flag = raw_flag if raw_flag else COUNTRY_FLAGS.get(code, "🏳️")
        try:
            price = float(parts[3])
        except ValueError:
            await message.answer(
                "❌ Price must be a number. Example: `30` or `0`",
                parse_mode="Markdown"
            )
            return

    if price < 0:
        await message.answer("❌ Price cannot be negative. Enter 0 or above:")
        return

    db = get_db()
    existing = await db.countries.find_one({"code": code})
    if existing:
        await message.answer(
            f"⚠️ *Country `{code}` already exists!*\n\n"
            f"Current: {existing['flag']} *{existing['name']}* — ₹{existing.get('price', 0):.0f}\n\n"
            f"Use 💰 Prices to update its price, or 🌍 Countries to manage it.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 Manage Prices", callback_data="admin_manage_prices")],
                [InlineKeyboardButton(text="🌍 Countries", callback_data="admin_countries")],
                [InlineKeyboardButton(text="◀️ Admin Panel", callback_data="admin_panel")],
            ]),
            parse_mode="Markdown"
        )
        await state.clear()
        return

    await db.countries.insert_one({
        "code": code,
        "name": name,
        "flag": flag,
        "price": price,
        "is_active": True,
        "added_at": datetime.utcnow(),
        "added_by": message.from_user.id,
    })
    await state.clear()

    price_str = "FREE" if price == 0 else f"₹{price:.0f}"
    await message.answer(
        f"✅ *Country Added!*\n\n"
        f"{flag} *{name}* (`{code}`)\n"
        f"💰 Price: *{price_str}*\n\n"
        f"Now upload sessions for this country via 📤 Upload Sessions.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Upload Sessions", callback_data="admin_upload_zip")],
            [InlineKeyboardButton(text="🌍 Manage Countries", callback_data="admin_countries")],
            [InlineKeyboardButton(text="◀️ Admin Panel", callback_data="admin_panel")],
        ]),
        parse_mode="Markdown"
    )


# ═══════════════════════════════════════════════════════════════
#   UPLOAD SESSIONS
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_upload_zip")
async def cb_upload_zip(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return
    await state.clear()
    db = get_db()
    countries = await db.countries.find({"is_active": True}).sort("name", 1).to_list(100)

    if not countries:
        await callback.message.edit_text(
            "❌ *No Active Countries*\n\n"
            "Add a country first, then upload sessions.",
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
        f"Each session will be *verified via Telethon* before saving.\n"
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
        await message.answer("❌ Please send a `.zip` file.", parse_mode="Markdown")
        return

    status_msg = await message.answer(
        f"⏳ *Downloading ZIP...*\n\nCountry: {country_flag} *{country_name}*",
        parse_mode="Markdown"
    )

    try:
        file = await message.bot.get_file(doc.file_id)
        file_bytes_io = await message.bot.download_file(file.file_path)
        zip_bytes = file_bytes_io.read()
    except Exception as e:
        await status_msg.edit_text(f"❌ Download failed: `{e}`", parse_mode="Markdown")
        await state.clear()
        return

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            session_names = [n for n in zf.namelist() if n.endswith(".session")]
    except Exception as e:
        await status_msg.edit_text(f"❌ Cannot read ZIP: `{e}`", parse_mode="Markdown")
        await state.clear()
        return

    if not session_names:
        await status_msg.edit_text(
            f"⚠️ *No .session Files Found*\n\n"
            f"ZIP contains no `.session` files.\n"
            f"Example: `918511982372.session`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Back", callback_data="admin_upload_zip")]
            ])
        )
        await state.clear()
        return

    db = get_db()
    country = await db.countries.find_one({"code": country_code})
    if not country:
        await status_msg.edit_text("❌ Country not found in database.")
        await state.clear()
        return

    total = len(session_names)
    await status_msg.edit_text(
        f"🔍 *Verifying {total} Sessions...*\n\n"
        f"{country_flag} *{country_name}*\n"
        f"Checking each session via Telethon...\n\n"
        f"`(0 / {total})` ⏳",
        parse_mode="Markdown"
    )

    added = 0
    skipped_dup = 0
    skipped_invalid = 0
    errors = []
    done = 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        async def process_one(name):
            nonlocal added, skipped_dup, skipped_invalid, done
            try:
                session_bytes = zf.read(name)
                phone = _phone_from_filename(name)
                existing = await db.sessions.find_one({"phone_number": phone})
                if existing:
                    skipped_dup += 1
                    done += 1
                    return
                is_valid = await _verify_session(session_bytes, phone)
                if not is_valid:
                    skipped_invalid += 1
                    done += 1
                    return
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
                done += 1
            except Exception as e:
                errors.append(f"{name}: {str(e)[:60]}")
                done += 1

        async def progress_updater():
            while done < total:
                await asyncio.sleep(4)
                if total > 0:
                    pct = int((done / total) * 100)
                    bar_filled = int(pct / 10)
                    bar = "█" * bar_filled + "░" * (10 - bar_filled)
                    try:
                        await status_msg.edit_text(
                            f"🔍 *Verifying Sessions...*\n\n"
                            f"{country_flag} *{country_name}*\n"
                            f"|{bar}| `{pct}%`\n"
                            f"`({done} / {total})`\n\n"
                            f"✅ Valid: `{added}` | ❌ Invalid: `{skipped_invalid}` | 🔄 Dup: `{skipped_dup}`",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass

        await asyncio.gather(
            asyncio.gather(*[process_one(n) for n in session_names]),
            progress_updater(),
        )

    if added == 0:
        current_stock = await db.sessions.count_documents({"country_code": country_code, "is_available": True})
        err_text = ("\n\n⚠️ *Errors:*\n" + "\n".join(f"• `{e}`" for e in errors[:3])) if errors else ""
        await status_msg.edit_text(
            f"⚠️ *No Valid Sessions Added*\n\n"
            f"Checked `{total}` files:\n"
            f"❌ Invalid/Expired: `{skipped_invalid}`\n"
            f"🔄 Duplicates: `{skipped_dup}`\n"
            f"📦 Current stock unchanged: `{current_stock}`" + err_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📤 Try Again", callback_data="admin_upload_zip")],
                [InlineKeyboardButton(text="◀️ Admin Panel", callback_data="admin_panel")],
            ])
        )
        await state.clear()
        return

    await state.update_data(
        zip_added=added, zip_skipped_dup=skipped_dup,
        zip_skipped_invalid=skipped_invalid, zip_errors=errors, zip_total=total
    )

    await status_msg.edit_text(
        f"✅ *{added} Sessions Verified!*\n\n"
        f"🌎 Country: {country_flag} *{country_name}*\n"
        f"✅ Valid & Stored: `{added}`\n"
        f"❌ Invalid/Expired: `{skipped_invalid}`\n"
        f"🔄 Duplicates Skipped: `{skipped_dup}`\n\n"
        f"🔐 *Set 2FA Password for these sessions:*\n"
        f"_(Type password or press Skip if no 2FA)_",
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
    await _finish_zip_upload(callback.message, state, password="", from_callback=True)
    await callback.answer()


@router.message(AdminStates.waiting_zip_password)
async def process_zip_password(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    password = message.text.strip()
    if password.lower() in ("none", "skip", "-", "no"):
        password = ""
    await _finish_zip_upload(message, state, password=password, from_callback=False)


async def _finish_zip_upload(msg, state: FSMContext, password: str, from_callback: bool = False):
    data = await state.get_data()
    country_code = data.get("zip_country", "")
    country_name = data.get("zip_country_name", country_code)
    country_flag = data.get("zip_country_flag", "")
    added = data.get("zip_added", 0)
    skipped_dup = data.get("zip_skipped_dup", 0)
    skipped_invalid = data.get("zip_skipped_invalid", 0)
    errors = data.get("zip_errors", [])

    if password and added > 0:
        from datetime import timedelta
        db = get_db()
        cutoff = datetime.utcnow() - timedelta(minutes=30)
        await db.sessions.update_many(
            {"country_code": country_code, "two_fa_password": "", "added_at": {"$gte": cutoff}},
            {"$set": {"two_fa_password": password}}
        )

    db = get_db()
    current_stock = await db.sessions.count_documents({"country_code": country_code, "is_available": True})
    password_status = f"`{password}`" if password else "_None (No 2FA)_"

    result_text = (
        f"✅ *Upload Complete!*\n\n"
        f"🌎 *Country:* {country_flag} {country_name}\n"
        f"✅ *Added & Verified:* `{added}` sessions\n"
        f"❌ *Invalid/Expired:* `{skipped_invalid}`\n"
        f"🔄 *Duplicates Skipped:* `{skipped_dup}`\n"
        f"📦 *Total Stock Now:* `{current_stock}`\n"
        f"🔐 *2FA Password:* {password_status}\n\n"
        f"_Sessions verified and ready for buyers!_ ✨"
    )
    if errors:
        result_text += "\n\n⚠️ *Sample Errors:*\n"
        for err in errors[:3]:
            result_text += f"• `{err}`\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Upload More", callback_data="admin_upload_zip")],
        [InlineKeyboardButton(text="◀️ Admin Panel", callback_data="admin_panel")],
    ])
    await state.clear()

    if from_callback:
        try:
            await msg.edit_text(result_text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            await msg.answer(result_text, reply_markup=kb, parse_mode="Markdown")
    else:
        await msg.answer(result_text, reply_markup=kb, parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════
#   MANAGE PRICES
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_manage_prices")
async def cb_manage_prices(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return
    db = get_db()
    countries = await db.countries.find({}).sort("name", 1).to_list(100)
    if not countries:
        await callback.message.edit_text(
            "💰 *No Countries Added Yet*\n\nAdd a country first.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Add Country", callback_data="admin_add_country")],
                [InlineKeyboardButton(text="◀️ Back", callback_data="admin_panel")],
            ]),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        "💰 *Manage Prices*\n\nTap a country to update its price:",
        reply_markup=prices_kb(countries),
        parse_mode="Markdown"
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
        f"💰 *Set Price — {name}*\n\n"
        f"Current: `₹{current:.2f}`\n\n"
        f"Enter new price in ₹\n_(Enter `0` for free)_:",
        reply_markup=cancel_admin_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.set_price_value)
async def process_set_price(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    try:
        price = float(message.text.strip().replace("₹", "").replace(",", ""))
        if price < 0:
            await message.answer("❌ Price cannot be negative. Enter 0 or above:")
            return
        data = await state.get_data()
        country_code = data.get("price_country")
        db = get_db()
        await db.countries.update_one({"code": country_code}, {"$set": {"price": price}})
        await state.clear()
        price_str = "FREE" if price == 0 else f"₹{price:.2f}"
        await message.answer(
            f"✅ *Price Updated!*\n\n`{country_code}` → *{price_str}*",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 Manage More Prices", callback_data="admin_manage_prices")],
                [InlineKeyboardButton(text="◀️ Admin Panel", callback_data="admin_panel")],
            ]),
            parse_mode="Markdown"
        )
    except ValueError:
        await message.answer("❌ Invalid. Enter a number like `30` or `0`:", parse_mode="Markdown")


@router.callback_query(F.data == "admin_bulk_price")
async def cb_bulk_price(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.set_bulk_price)
    db = get_db()
    countries = await db.countries.find({}).sort("name", 1).to_list(100)
    country_list = "\n".join(f"• {c['flag']} {c['name']} — ₹{c.get('price', 0):.0f}" for c in countries)
    await callback.message.edit_text(
        f"🔄 *Bulk Set Price — All Countries*\n\n"
        f"Current prices:\n{country_list}\n\n"
        f"Enter *one price* to apply to ALL countries (in ₹):",
        reply_markup=cancel_admin_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.set_bulk_price)
async def process_bulk_price(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    try:
        price = float(message.text.strip().replace("₹", "").replace(",", ""))
        if price < 0:
            await message.answer("❌ Price cannot be negative. Enter 0 or above:")
            return
        db = get_db()
        result = await db.countries.update_many({}, {"$set": {"price": price}})
        await state.clear()
        price_str = "FREE" if price == 0 else f"₹{price:.2f}"
        await message.answer(
            f"✅ *Bulk Price Updated!*\n\n"
            f"All {result.modified_count} countries → *{price_str}*",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 View Prices", callback_data="admin_manage_prices")],
                [InlineKeyboardButton(text="◀️ Admin Panel", callback_data="admin_panel")],
            ]),
            parse_mode="Markdown"
        )
    except ValueError:
        await message.answer("❌ Invalid. Enter a number like `30` or `0`:", parse_mode="Markdown")
