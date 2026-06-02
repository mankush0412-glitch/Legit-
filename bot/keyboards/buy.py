from typing import List, Dict
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def countries_kb(countries: List[Dict]) -> InlineKeyboardMarkup:
    """2-column country grid for buying."""
    rows = []
    for i in range(0, len(countries), 2):
        row = []
        for c in countries[i:i+2]:
            row.append(InlineKeyboardButton(
                text=f"{c['flag']} {c['name']} — ₹{c['price']:.0f}",
                callback_data=f"buy_country:{c['code']}"
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="◀️ Back to Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_buy_kb(country_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Buy Now", callback_data=f"confirm_buy:{country_code}"),
            InlineKeyboardButton(text="🔙 Cancel", callback_data="buy_account"),
        ]
    ])


def insufficient_balance_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Deposit Funds", callback_data="deposit")],
        [InlineKeyboardButton(text="◀️ Back", callback_data="buy_account")],
    ])


def otp_waiting_kb(purchase_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Get New SMS", callback_data=f"get_new_sms:{purchase_id}")],
        [InlineKeyboardButton(text="🚫 Cancel Order", callback_data=f"cancel_order:{purchase_id}")],
    ])


def otp_received_kb(purchase_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Get OTP Again", callback_data=f"get_otp_again:{purchase_id}")],
        [InlineKeyboardButton(text="🔴 Log Out Device", callback_data=f"logout_device:{purchase_id}")],
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")],
    ])


def after_logout_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Buy Another", callback_data="buy_account")],
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")],
    ])


def buy_again_kb() -> InlineKeyboardMarkup:
    """Shown after session error / cancel — quick retry."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Buy Again", callback_data="buy_account")],
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")],
    ])
