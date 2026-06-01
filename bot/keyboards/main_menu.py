from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛒  Buy Account  ", callback_data="buy_account"),
            InlineKeyboardButton(text="📦  Get Sessions  ", callback_data="get_sessions"),
        ],
        [
            InlineKeyboardButton(text="👤  Profile  ", callback_data="profile"),
            InlineKeyboardButton(text="💰  Deposit  ", callback_data="deposit"),
        ],
        [
            InlineKeyboardButton(text="📋  History  ", callback_data="history"),
            InlineKeyboardButton(text="🔑  My OTPs  ", callback_data="my_sessions"),
        ],
        [
            InlineKeyboardButton(text="🎁  Refer & Earn  ", callback_data="referral"),
            InlineKeyboardButton(text="🆘  Support  ", callback_data="support"),
        ],
    ])


def back_to_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠  Main Menu  ", callback_data="main_menu")]
    ])


def back_and_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◀️ Back", callback_data="main_menu"),
            InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu"),
        ]
    ])
