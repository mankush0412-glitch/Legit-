from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def admin_panel_kb(is_owner: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="📦 Upload Sessions", callback_data="admin_upload_zip"),
            InlineKeyboardButton(text="💰 Manage Prices", callback_data="admin_manage_prices"),
        ],
        [
            InlineKeyboardButton(text="💳 Pending Deposits", callback_data="admin_pending_deposits"),
            InlineKeyboardButton(text="📊 Stats", callback_data="admin_stats"),
        ],
        [
            InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast"),
            InlineKeyboardButton(text="💵 Add Balance", callback_data="admin_add_balance"),
        ],
        [
            InlineKeyboardButton(text="👥 Users", callback_data="admin_all_users"),
            InlineKeyboardButton(text="🌍 Countries", callback_data="admin_countries"),
        ],
        [
            InlineKeyboardButton(text="➕ Add Country", callback_data="admin_add_country"),
            InlineKeyboardButton(text="⚙️ Bot Settings", callback_data="admin_settings"),
        ],
        [
            InlineKeyboardButton(text="📥 Backup Data", callback_data="admin_backup"),
            InlineKeyboardButton(text="📋 Deposit Log", callback_data="admin_deposits_log"),
        ],
    ]
    if is_owner:
        rows.append([
            InlineKeyboardButton(text="👑 Manage Admins", callback_data="admin_manage_admins"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def deposit_approve_kb(deposit_id: str, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_deposit:{deposit_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_deposit:{deposit_id}"),
        ]
    ])


def prices_kb(countries: list) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(countries), 2):
        row = []
        for c in countries[i:i+2]:
            row.append(InlineKeyboardButton(
                text=f"{c['flag']} {c['name']} — ₹{c['price']:.0f}",
                callback_data=f"set_price:{c['code']}"
            ))
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text="🔄 Bulk Set All Prices", callback_data="admin_bulk_price"),
    ])
    rows.append([InlineKeyboardButton(text="➕ Add Country", callback_data="admin_add_country")])
    rows.append([InlineKeyboardButton(text="◀️ Back", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Set Bot Name", callback_data="admin_set_bot_name")],
        [InlineKeyboardButton(text="📱 Set UPI ID", callback_data="admin_set_upi")],
        [InlineKeyboardButton(text="🏷️ Set UPI Display Name", callback_data="admin_set_upi_name")],
        [InlineKeyboardButton(text="💎 Set USDT Address", callback_data="admin_set_usdt")],
        [InlineKeyboardButton(text="💬 Set Support Username", callback_data="admin_set_support")],
        [InlineKeyboardButton(text="🎁 Set Referral Join Bonus (₹)", callback_data="admin_set_referral")],
        [InlineKeyboardButton(text="📊 Set Referral Deposit %", callback_data="admin_set_referral_pct")],
        [InlineKeyboardButton(text="🔗 Set Keep-Alive URL", callback_data="admin_set_ping_url")],
        [InlineKeyboardButton(text="◀️ Back", callback_data="admin_panel")],
    ])


def admin_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Back to Admin", callback_data="admin_panel")]
    ])


def cancel_admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_panel")]
    ])


def countries_toggle_kb(countries: list) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(countries), 2):
        row = []
        for c in countries[i:i+2]:
            status = "✅" if c.get("is_active", True) else "❌"
            row.append(InlineKeyboardButton(
                text=f"{status} {c['flag']} {c['name']}",
                callback_data=f"toggle_country:{c['code']}"
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="◀️ Back", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Send to All", callback_data="broadcast_confirm"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="admin_panel"),
        ]
    ])


def manage_admins_kb(admins: list) -> InlineKeyboardMarkup:
    rows = []
    for a in admins:
        name = a.get("name", "Unknown")
        uid = a.get("telegram_id")
        rows.append([InlineKeyboardButton(
            text=f"❌ Remove {name} ({uid})",
            callback_data=f"remove_admin:{uid}"
        )])
    rows.append([InlineKeyboardButton(text="➕ Add New Admin", callback_data="add_new_admin")])
    rows.append([InlineKeyboardButton(text="◀️ Back", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
