from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext

from bot.keyboards.main_menu import main_menu_kb
from bot.config import BOT_NAME
from bot.services.wallet_service import get_or_create_user, apply_referral

router = Router()


async def send_main_menu(chat_id: int, bot, balance: float, first_name: str = "User"):
    name_short = first_name[:12] if first_name else "User"
    text = (
        f"🏠 *Main Menu*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚡ *Premium Telegram Accounts*\n"
        f"Instant access to high-quality accounts from around the world.\n\n"
        f"👋 Welcome, *{name_short}*!\n"
        f"💎 Wallet Balance: `₹{balance:.2f}`\n\n"
        f"👇 Select an option to continue:"
    )
    await bot.send_message(chat_id, text, reply_markup=main_menu_kb(), parse_mode="Markdown")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db_user: dict = None):
    await state.clear()
    args = message.text.split()

    if len(args) > 1 and args[1].startswith("ref_"):
        ref_code = args[1][4:]
        if db_user and not db_user.get("referred_by"):
            applied = await apply_referral(message.from_user.id, ref_code)
            if applied:
                await message.answer(
                    "🎁 *Referral Applied!*\n\nYour referrer got rewarded. Welcome!",
                    parse_mode="Markdown"
                )

    balance = float(db_user.get("balance", 0.0)) if db_user else 0.0
    await send_main_menu(
        message.chat.id, message.bot, balance,
        message.from_user.first_name or "User"
    )


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext, db_user: dict = None):
    await state.clear()
    balance = float(db_user.get("balance", 0.0)) if db_user else 0.0
    first_name = callback.from_user.first_name or "User"
    name_short = first_name[:12]

    text = (
        f"🏠 *Main Menu*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚡ *Premium Telegram Accounts*\n"
        f"Instant access to high-quality accounts from around the world.\n\n"
        f"👋 Welcome, *{name_short}*!\n"
        f"💎 Wallet Balance: `₹{balance:.2f}`\n\n"
        f"👇 Select an option to continue:"
    )
    try:
        await callback.message.edit_text(text, reply_markup=main_menu_kb(), parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text, reply_markup=main_menu_kb(), parse_mode="Markdown")
    await callback.answer()
