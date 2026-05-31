from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from bot.keyboards.main_menu import back_to_main_kb
from bot.services.settings_service import get_setting, get_all_admin_ids
from bot.states.states import SupportState

router = Router()


@router.callback_query(F.data == "support")
async def cb_support(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    support_username = await get_setting("support_username", "")

    buttons = []
    if support_username:
        buttons.append([InlineKeyboardButton(
            text=f"💬 Contact @{support_username}",
            url=f"https://t.me/{support_username}"
        )])
    buttons.append([InlineKeyboardButton(text="✉️ Send Message to Admin", callback_data="send_support_msg")])
    buttons.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")])

    text = (
        f"🆘 *Support*\n\n"
        f"Having an issue? We're here to help!\n\n"
        f"⏰ *Response time:* Typically within 1-2 hours\n\n"
        f"📋 *Common Issues:*\n"
        f"• OTP not received — Try 'Get New SMS'\n"
        f"• Balance not updated — Wait 2 minutes\n"
        f"• Session not working — Contact support\n"
    )
    if support_username:
        text += f"\n👤 Support: @{support_username}"

    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="Markdown"
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="Markdown"
        )
    await callback.answer()


@router.callback_query(F.data == "send_support_msg")
async def cb_send_support_msg(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SupportState.waiting_message)
    await callback.message.edit_text(
        "✉️ *Send Message to Support*\n\n"
        "Describe your issue and we'll respond ASAP:",
        reply_markup=back_to_main_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(SupportState.waiting_message)
async def process_support_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {user_id}"
    name = message.from_user.first_name or "User"

    for admin_id in await get_all_admin_ids():
        try:
            await message.bot.send_message(
                admin_id,
                f"📩 *Support Message*\n\n"
                f"👤 {name} ({username})\n"
                f"🆔 `{user_id}`\n\n"
                f"💬 {message.text}",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    await message.answer(
        "✅ *Message Sent!*\n\nOur support team will respond shortly.",
        reply_markup=back_to_main_kb(),
        parse_mode="Markdown"
    )
    await state.clear()
