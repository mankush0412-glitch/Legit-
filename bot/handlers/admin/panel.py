from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from datetime import datetime

from bot.database import get_db
from bot.keyboards.admin import admin_panel_kb, admin_settings_kb, cancel_admin_kb, admin_back_kb, manage_admins_kb
from bot.states.states import AdminStates
from bot.utils.helpers import is_owner, is_any_admin
from bot.services.settings_service import get_setting, set_setting

router = Router()


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    await state.clear()
    owner = is_owner(message.from_user.id)
    await message.answer(
        "🔑 *Admin Panel*\n\n"
        + ("👑 *Owner Mode* — Full Access\n\n" if owner else "")
        + "Select an action:",
        reply_markup=admin_panel_kb(is_owner=owner),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return
    await state.clear()
    owner = is_owner(callback.from_user.id)
    text = (
        "🔑 *Admin Panel*\n\n"
        + ("👑 *Owner Mode* — Full Access\n\n" if owner else "")
        + "Select an action:"
    )
    try:
        await callback.message.edit_text(text, reply_markup=admin_panel_kb(is_owner=owner), parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text, reply_markup=admin_panel_kb(is_owner=owner), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return

    db = get_db()
    total_users = await db.users.count_documents({})
    total_sessions = await db.sessions.count_documents({})
    available_sessions = await db.sessions.count_documents({"is_available": True})
    total_purchases = await db.purchases.count_documents({})
    pending_deposits = await db.deposits.count_documents({"status": "pending"})
    approved_deposits = await db.deposits.count_documents({"status": "approved"})
    banned_users = await db.users.count_documents({"is_banned": True})

    revenue_result = await db.deposits.aggregate([
        {"$match": {"status": "approved"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]).to_list(1)
    total_revenue = revenue_result[0]["total"] if revenue_result else 0

    wallet_result = await db.users.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$balance"}}}
    ]).to_list(1)
    total_wallets = wallet_result[0]["total"] if wallet_result else 0

    today_users = await db.users.count_documents({
        "joined_at": {"$gte": datetime.utcnow().replace(hour=0, minute=0, second=0)}
    })
    db_admins = await db.bot_admins.count_documents({"is_active": True})

    await callback.message.edit_text(
        f"📊 *Bot Statistics*\n\n"
        f"👥 *Users:* `{total_users}` (+{today_users} today)\n"
        f"🚫 *Banned:* `{banned_users}`\n"
        f"🔑 *DB Admins:* `{db_admins}`\n\n"
        f"📦 *Total Sessions:* `{total_sessions}`\n"
        f"✅ *Available:* `{available_sessions}`\n"
        f"🛒 *Total Purchases:* `{total_purchases}`\n\n"
        f"💳 *Pending Deposits:* `{pending_deposits}`\n"
        f"✅ *Approved Deposits:* `{approved_deposits}`\n"
        f"💰 *Total Revenue:* `₹{total_revenue:.2f}`\n"
        f"💎 *Total Wallets:* `₹{total_wallets:.2f}`",
        reply_markup=admin_back_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_settings")
async def cb_admin_settings(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return

    upi_id = await get_setting("upi_id", "")
    usdt_address = await get_setting("usdt_address", "")
    support_username = await get_setting("support_username", "")
    referral_bonus = await get_setting("referral_bonus", 10.0)
    referral_percent = await get_setting("referral_percent", 3.0)
    auto_upi = await get_setting("auto_approve_upi", True)
    auto_crypto = await get_setting("auto_approve_crypto", True)
    bot_name = await get_setting("bot_name", "Legit Stocks Bot")
    self_ping = await get_setting("self_ping_url", "")

    auto_upi_str = "✅ ON" if auto_upi else "❌ OFF"
    auto_crypto_str = "✅ ON" if auto_crypto else "❌ OFF"
    usdt_display = (usdt_address[:18] + "...") if usdt_address else "Not set"
    ping_display = (self_ping[:30] + "...") if len(self_ping) > 30 else (self_ping or "Not set")

    await callback.message.edit_text(
        f"⚙️ *Bot Settings*\n\n"
        f"🤖 *Bot Name:* {bot_name}\n"
        f"📱 *UPI ID:* `{upi_id or 'Not set'}`\n"
        f"💎 *USDT Address:* `{usdt_display}`\n"
        f"💬 *Support:* @{support_username or 'Not set'}\n\n"
        f"🎁 *Referral Join Bonus:* `₹{referral_bonus:.0f}`\n"
        f"📊 *Referral Deposit %:* `{referral_percent:.1f}%`\n\n"
        f"⚡ *Auto UPI Approve:* {auto_upi_str}\n"
        f"⚡ *Auto Crypto Approve:* {auto_crypto_str}\n"
        f"🔗 *Keep-Alive URL:* `{ping_display}`",
        reply_markup=admin_settings_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_set_upi")
async def cb_set_upi(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.set_upi)
    await callback.message.edit_text(
        "📱 *Set UPI ID*\n\nSend the new UPI ID:\n_Example: yourname@paytm_",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.set_upi)
async def process_set_upi(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    upi_id = message.text.strip()
    await set_setting("upi_id", upi_id)
    await state.clear()
    await message.answer(
        f"✅ *UPI ID Updated!*\n\n`{upi_id}`",
        reply_markup=admin_panel_kb(is_owner=is_owner(message.from_user.id)),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "admin_set_upi_name")
async def cb_set_upi_name(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.set_upi_name)
    await callback.message.edit_text(
        "📱 *Set UPI Display Name*\n\nSend the name to show on QR:",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.set_upi_name)
async def process_set_upi_name(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    name = message.text.strip()
    await set_setting("upi_name", name)
    await state.clear()
    await message.answer(
        f"✅ *UPI Name Updated!*\n\n`{name}`",
        reply_markup=admin_panel_kb(is_owner=is_owner(message.from_user.id)),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "admin_set_usdt")
async def cb_set_usdt(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.set_usdt)
    await callback.message.edit_text(
        "💎 *Set USDT Address*\n\nSend the new USDT TRC20 address:",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.set_usdt)
async def process_set_usdt(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    addr = message.text.strip()
    await set_setting("usdt_address", addr)
    await state.clear()
    await message.answer(
        f"✅ *USDT Address Updated!*\n\n`{addr}`",
        reply_markup=admin_panel_kb(is_owner=is_owner(message.from_user.id)),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "admin_set_support")
async def cb_set_support(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.set_support)
    await callback.message.edit_text(
        "💬 *Set Support Username*\n\nSend username (without @):",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.set_support)
async def process_set_support(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    username = message.text.strip().lstrip("@")
    await set_setting("support_username", username)
    await state.clear()
    await message.answer(
        f"✅ *Support Username Updated!*\n\n@{username}",
        reply_markup=admin_panel_kb(is_owner=is_owner(message.from_user.id)),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "admin_set_referral")
async def cb_set_referral(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.set_referral_bonus)
    await callback.message.edit_text(
        "🎁 *Set Referral Join Bonus*\n\nSend amount in ₹:\n_Paid once when a new user joins via referral link._",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.set_referral_bonus)
async def process_set_referral(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    try:
        amount = float(message.text.strip())
        await set_setting("referral_bonus", amount)
        await state.clear()
        await message.answer(
            f"✅ *Referral Join Bonus Updated!*\n\n`₹{amount:.0f}`",
            reply_markup=admin_panel_kb(is_owner=is_owner(message.from_user.id)),
            parse_mode="Markdown"
        )
    except ValueError:
        await message.answer("❌ Invalid amount. Enter a number:")


@router.callback_query(F.data == "admin_set_referral_pct")
async def cb_set_referral_pct(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.set_referral_percent)
    await callback.message.edit_text(
        "📊 *Set Referral Deposit %*\n\nSend percentage _(e.g. `3.0` = 3%):_\n"
        "_Referrer earns this % on every deposit their friend makes._",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.set_referral_percent)
async def process_set_referral_pct(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    try:
        pct = float(message.text.strip().replace("%", ""))
        await set_setting("referral_percent", pct)
        await state.clear()
        await message.answer(
            f"✅ *Referral Deposit % Updated!*\n\n`{pct:.1f}%`",
            reply_markup=admin_panel_kb(is_owner=is_owner(message.from_user.id)),
            parse_mode="Markdown"
        )
    except ValueError:
        await message.answer("❌ Invalid. Enter like `3.0`:", parse_mode="Markdown")


@router.callback_query(F.data == "admin_set_bot_name")
async def cb_set_bot_name(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.set_bot_name)
    await callback.message.edit_text(
        "🤖 *Set Bot Name*\n\nSend the new display name for the bot:",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.set_bot_name)
async def process_set_bot_name(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    name = message.text.strip()
    await set_setting("bot_name", name)
    await state.clear()
    await message.answer(
        f"✅ *Bot Name Updated!*\n\n`{name}`",
        reply_markup=admin_panel_kb(is_owner=is_owner(message.from_user.id)),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "admin_set_ping_url")
async def cb_set_ping_url(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.set_ping_url)
    await callback.message.edit_text(
        "🔗 *Set Keep-Alive URL*\n\nSend the full URL the bot should ping every 14 min:\n"
        "_Example: https://yourapp.onrender.com/health_\n\n"
        "_Send `clear` to disable._",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.set_ping_url)
async def process_set_ping_url(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    url = message.text.strip()
    if url.lower() == "clear":
        url = ""
    await set_setting("self_ping_url", url)
    await state.clear()
    display = f"`{url}`" if url else "_Disabled_"
    await message.answer(
        f"✅ *Keep-Alive URL Updated!*\n\n{display}",
        reply_markup=admin_panel_kb(is_owner=is_owner(message.from_user.id)),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "admin_manage_admins")
async def cb_manage_admins(callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("❌ Owner only!", show_alert=True)
        return

    db = get_db()
    admins = await db.bot_admins.find({"is_active": True}).to_list(50)

    if admins:
        lines = [f"👑 *Manage Admins*\n\n*Active DB Admins ({len(admins)}):*\n"]
        for a in admins:
            lines.append(f"• {a.get('name', 'Unknown')} — `{a['telegram_id']}`")
    else:
        lines = ["👑 *Manage Admins*\n\n_No DB admins added yet._\n\nOwner always has full access."]

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=manage_admins_kb(admins),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "add_new_admin")
async def cb_add_new_admin(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        await callback.answer("❌ Owner only!", show_alert=True)
        return
    await state.set_state(AdminStates.add_admin)
    await callback.message.edit_text(
        "👑 *Add New Admin*\n\n"
        "Send the Telegram ID of the new admin:\n\n"
        "_They can access the admin panel, upload sessions, approve deposits._\n"
        "_They cannot manage other admins — owner only._",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.add_admin)
async def process_add_admin(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        new_admin_id = int(message.text.strip())
        db = get_db()

        existing = await db.bot_admins.find_one({"telegram_id": new_admin_id})
        if existing:
            await db.bot_admins.update_one(
                {"telegram_id": new_admin_id},
                {"$set": {"is_active": True}}
            )
            await state.clear()
            await message.answer(
                f"✅ Admin `{new_admin_id}` re-activated.",
                reply_markup=admin_panel_kb(is_owner=True), parse_mode="Markdown"
            )
            return

        user = await db.users.find_one({"telegram_id": new_admin_id})
        name = user.get("first_name", "Unknown") if user else "Unknown"
        username = user.get("username", "") if user else ""

        await db.bot_admins.insert_one({
            "telegram_id": new_admin_id,
            "name": name,
            "username": username,
            "is_active": True,
            "added_by": message.from_user.id,
            "added_at": datetime.utcnow(),
        })
        await state.clear()
        await message.answer(
            f"✅ *Admin Added!*\n\n"
            f"👤 Name: {name}\n"
            f"🆔 ID: `{new_admin_id}`\n\n"
            f"They can now use `/admin` command.",
            reply_markup=admin_panel_kb(is_owner=True), parse_mode="Markdown"
        )
        try:
            await message.bot.send_message(
                new_admin_id,
                "🔑 *You've been granted Admin access!*\n\nUse /admin to open the panel.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
    except ValueError:
        await message.answer("❌ Invalid ID. Enter a valid Telegram user ID:")


@router.callback_query(F.data.startswith("remove_admin:"))
async def cb_remove_admin(callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("❌ Owner only!", show_alert=True)
        return

    admin_id = int(callback.data.split(":")[1])
    db = get_db()
    await db.bot_admins.update_one({"telegram_id": admin_id}, {"$set": {"is_active": False}})

    admins = await db.bot_admins.find({"is_active": True}).to_list(50)
    await callback.message.edit_reply_markup(reply_markup=manage_admins_kb(admins))
    await callback.answer(f"✅ Admin {admin_id} removed.")

    try:
        await callback.bot.send_message(
            admin_id,
            "🔑 Your admin access has been removed.",
        )
    except Exception:
        pass


