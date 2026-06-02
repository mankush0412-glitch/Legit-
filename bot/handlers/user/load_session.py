import io
import zipfile
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from aiogram.fsm.context import FSMContext

from bot.database import get_db
from bot.keyboards.main_menu import back_to_main_kb
from bot.states.states import LoadSessionState
from bot.config import TELEGRAM_API_ID, TELEGRAM_API_HASH

router = Router()


@router.callback_query(F.data == "load_session")
async def cb_load_session(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    user_id = callback.from_user.id
    db = get_db()
    purchases = await db.purchases.find(
        {"user_id": user_id, "type": "bulk", "status": "bulk_delivered"}
    ).sort("created_at", -1).limit(5).to_list(5)

    recent_singles = await db.purchases.find(
        {"user_id": user_id, "status": {"$in": ["otp_received", "completed"]}}
    ).sort("created_at", -1).limit(5).to_list(5)

    lines = [
        "📂 *Load Session*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Send your `.session` file or a `.zip` of session files.\n"
        "The bot will extract OTP from each session.\n\n"
        "📌 *Your Recent Purchased Sessions:*"
    ]

    if recent_singles:
        for p in recent_singles:
            otp = p.get("otp", "—")
            lines.append(
                f"• {p.get('country_flag', '')} `{p.get('phone_number', 'N/A')}` — OTP: `{otp}`"
            )
    else:
        lines.append("_No single sessions purchased yet._")

    if purchases:
        lines.append("\n📦 *Your Bulk Session Orders:*")
        for p in purchases:
            lines.append(
                f"• {p.get('country_flag', '')} {p.get('country', 'N/A')} × {p.get('quantity', 1)}"
            )

    lines.append(
        "\n\n💡 *Usage:*\n"
        "• Send a `.session` file → bot logs in & shows OTP\n"
        "• Send a `.zip` file → extracts all sessions inside"
    )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")]
    ])

    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await callback.message.answer("\n".join(lines), reply_markup=kb, parse_mode="Markdown")
    await state.set_state(LoadSessionState.waiting_file)
    await callback.answer()


@router.message(LoadSessionState.waiting_file, F.document)
async def process_session_file(message: Message, state: FSMContext):
    doc = message.document
    file_name = doc.file_name or ""

    if not (file_name.endswith(".session") or file_name.endswith(".zip")):
        await message.answer(
            "❌ Please send a `.session` or `.zip` file.",
            reply_markup=back_to_main_kb()
        )
        return

    processing_msg = await message.answer("⏳ *Loading session...*", parse_mode="Markdown")

    file = await message.bot.get_file(doc.file_id)
    file_bytes_io = await message.bot.download_file(file.file_path)
    file_bytes = file_bytes_io.read()

    import tempfile
    import os
    from telethon import TelegramClient

    results = []

    if file_name.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                session_names = [n for n in zf.namelist() if n.endswith(".session")]
                for sname in session_names[:10]:
                    s_bytes = zf.read(sname)
                    phone, otp_info = await _check_session_otp(s_bytes, sname)
                    results.append((sname, phone, otp_info))
        except Exception as e:
            await processing_msg.edit_text(f"❌ Failed to read ZIP: {e}")
            return
    else:
        phone, otp_info = await _check_session_otp(file_bytes, file_name)
        results.append((file_name, phone, otp_info))

    await processing_msg.delete()

    if not results:
        await message.answer("❌ No valid sessions found.", reply_markup=back_to_main_kb())
        return

    lines = ["✅ *Session(s) Loaded*\n━━━━━━━━━━━━━━━━━━━━━━━━"]
    for name, phone, info in results:
        status = "✅ Authorized" if info.get("authorized") else "❌ Not Authorized"
        lines.append(f"\n📱 *{name}*\n📞 Phone: `{phone or 'Unknown'}`\nStatus: {status}")

    await message.answer(
        "\n".join(lines),
        reply_markup=back_to_main_kb(),
        parse_mode="Markdown"
    )
    await state.clear()


async def _check_session_otp(session_bytes: bytes, name: str):
    import tempfile
    import os
    from telethon import TelegramClient
    from bot.config import TELEGRAM_API_ID, TELEGRAM_API_HASH

    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        return None, {"authorized": False, "error": "API credentials not set"}

    tmp_dir = tempfile.mkdtemp()
    session_path = os.path.join(tmp_dir, "sess")
    try:
        with open(session_path + ".session", "wb") as f:
            f.write(session_bytes)

        client = TelegramClient(session_path, TELEGRAM_API_ID, TELEGRAM_API_HASH)
        await client.connect()
        authorized = await client.is_user_authorized()
        phone = None
        if authorized:
            me = await client.get_me()
            if me:
                phone = f"+{me.phone}" if me.phone else None
        await client.disconnect()
        return phone, {"authorized": authorized}
    except Exception as e:
        return None, {"authorized": False, "error": str(e)}
    finally:
        try:
            os.remove(session_path + ".session")
            os.rmdir(tmp_dir)
        except Exception:
            pass
