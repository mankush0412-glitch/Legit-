from typing import List, Dict
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def countries_kb(countries: List[Dict]) -> InlineKeyboardMarkup:
    buttons = []
    for country in countries:
        label = f"{country['flag']}  {country['name']}  —  ₹{country['price']:.0f}  •  📦 {country['stock']}"
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"buy_country:{country['code']}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️  Back to Menu  ", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_buy_kb(country_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅  Buy Now  ", callback_data=f"confirm_buy:{country_code}"),
            InlineKeyboardButton(text="🔙  Cancel  ", callback_data="buy_account"),
        ]
    ])


def insufficient_balance_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰  Add Funds  ", callback_data="deposit")],
        [InlineKeyboardButton(text="◀️  Back  ", callback_data="buy_account")],
    ])


def otp_waiting_kb(purchase_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📨  Get New SMS  ", callback_data=f"get_new_sms:{purchase_id}")],
        [InlineKeyboardButton(text="🚫  Cancel Order  ", callback_data=f"cancel_order:{purchase_id}")],
    ])


def otp_received_kb(purchase_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄  Get OTP Again  ", callback_data=f"get_otp_again:{purchase_id}")],
        [InlineKeyboardButton(text="🔴  Logout Device  ", callback_data=f"logout_device:{purchase_id}")],
        [
            InlineKeyboardButton(text="🔑 My OTPs", callback_data="my_sessions"),
            InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu"),
        ],
    ])


def after_logout_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒  Buy Another  ", callback_data="buy_account")],
        [InlineKeyboardButton(text="🏠  Main Menu  ", callback_data="main_menu")],
    ])
