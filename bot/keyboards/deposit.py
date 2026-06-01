from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def deposit_methods_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇮🇳  UPI / Scanner — Instant Credit  ", callback_data="deposit_upi")],
        [InlineKeyboardButton(text="💎  Crypto USDT — Auto Verify  ", callback_data="deposit_crypto")],
        [InlineKeyboardButton(text="◀️  Back to Menu  ", callback_data="main_menu")],
    ])


def cancel_deposit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌  Cancel  ", callback_data="deposit")],
    ])


def after_deposit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒  Buy Account  ", callback_data="buy_account")],
        [InlineKeyboardButton(text="🏠  Main Menu  ", callback_data="main_menu")],
    ])
