import asyncio
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from bot.database import get_db
from bot.keyboards.admin import admin_back_kb, cancel_admin_kb, broadcast_confirm_kb
from bot.states.states import AdminStates
from bot.services.wallet_service import add_balance
from bot.utils.helpers import is_any_admin, is_owner, format_datetime

router = Router()


@router.callback_query(F.data == "admin_all_users")
async def cb_all_users(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return

    db = get_db()
    total = await db.users.count_documents({})
    banned = await db.users.count_documents({"is_banned": True})
    recent = await db.users.find({}).sort("joined_at", -1).limit(15).to_list(15)

    lines = [
        f"👥 *All Users*",
        f"Total: `{total}` | Banned: `{banned}`\n",
        "_Recent 15 users:_\n"
    ]
    for u in recent:
        name = u.get("first_name", "N/A")
        username = f"@{u['username']}" if u.get("username") else "—"
        balance = float(u.get("balance", 0))
        purchases = u.get("total_purchases", 0)
        banned_tag = " 🚫" if u.get("is_banned") else ""
        lines.append(f"• `{u['telegram_id']}`{banned_tag} {name} {username} — ₹{balance:.0f} — {purchases} orders")

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Search User", callback_data="admin_search_user")],
        [InlineKeyboardButton(text="🚫 Ban User", callback_data="admin_ban_user")],
        [InlineKeyboardButton(text="✅ Unban User", callback_data="admin_unban_user")],
        [InlineKeyboardButton(text="◀️ Back", callback_data="admin_panel")],
    ])

    await callback.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "admin_search_user")
async def cb_search_user(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.search_user)
    await callback.message.edit_text(
        "🔍 *Search User*\n\nSend Telegram ID or @username:",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.search_user)
async def process_search_user(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    db = get_db()
    query = message.text.strip().lstrip("@")

    try:
        uid = int(query)
        user = await db.users.find_one({"telegram_id": uid})
    except ValueError:
        user = await db.users.find_one({"username": {"$regex": query, "$options": "i"}})

    await state.clear()

    if not user:
        await message.answer("❌ User not found.", reply_markup=admin_back_kb())
        return

    uid = user["telegram_id"]
    total_deposits = await db.deposits.aggregate([
        {"$match": {"user_id": uid, "status": "approved"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]).to_list(1)
    total_dep = total_deposits[0]["total"] if total_deposits else 0

    purchases = await db.purchases.count_documents({"user_id": uid})
    banned = "🚫 Banned" if user.get("is_banned") else "✅ Active"
    joined = format_datetime(user.get("joined_at"))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 Add/Deduct Balance", callback_data=f"quick_balance:{uid}")],
        [InlineKeyboardButton(
            text="✅ Unban" if user.get("is_banned") else "🚫 Ban",
            callback_data=f"quick_ban:{uid}:{1 if user.get('is_banned') else 0}"
        )],
        [InlineKeyboardButton(text="◀️ Back", callback_data="admin_all_users")],
    ])

    await message.answer(
        f"👤 *User Profile*\n\n"
        f"🆔 *ID:* `{uid}`\n"
        f"👤 *Name:* {user.get('first_name', 'N/A')}\n"
        f"📛 *Username:* @{user.get('username', 'none')}\n"
        f"💎 *Balance:* `₹{float(user.get('balance', 0)):.2f}`\n"
        f"💰 *Total Deposited:* `₹{total_dep:.2f}`\n"
        f"🛒 *Purchases:* `{purchases}`\n"
        f"📅 *Joined:* {joined}\n"
        f"🔘 *Status:* {banned}",
        reply_markup=kb, parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("quick_balance:"))
async def cb_quick_balance(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    uid = int(callback.data.split(":")[1])
    await state.update_data(balance_user_id=uid)
    await state.set_state(AdminStates.add_balance_amount)
    await callback.message.answer(
        f"💵 Enter amount to add/deduct for `{uid}`:\n_(negative to deduct e.g. `-50`)_",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("quick_ban:"))
async def cb_quick_ban(callback: CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        return
    parts = callback.data.split(":")
    uid = int(parts[1])
    is_banned_now = int(parts[2]) == 1
    db = get_db()
    new_status = not is_banned_now
    await db.users.update_one({"telegram_id": uid}, {"$set": {"is_banned": new_status}})
    status = "✅ Unbanned" if not new_status else "🚫 Banned"
    await callback.answer(f"{status} user {uid}!", show_alert=True)
    try:
        msg = "🚫 You have been banned." if new_status else "✅ Your ban has been lifted."
        await callback.bot.send_message(uid, msg)
    except Exception:
        pass


@router.callback_query(F.data == "admin_ban_user")
async def cb_ban_user(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.ban_user)
    await state.update_data(ban_action="ban")
    await callback.message.edit_text(
        "🚫 *Ban User*\n\nSend Telegram ID to ban:",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_unban_user")
async def cb_unban_user(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.ban_user)
    await state.update_data(ban_action="unban")
    await callback.message.edit_text(
        "✅ *Unban User*\n\nSend Telegram ID to unban:",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.ban_user)
async def process_ban(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    try:
        uid = int(message.text.strip())
        data = await state.get_data()
        ban_action = data.get("ban_action", "ban")
        db = get_db()
        new_status = ban_action == "ban"
        await db.users.update_one({"telegram_id": uid}, {"$set": {"is_banned": new_status}})
        await state.clear()
        action_text = "🚫 Banned" if new_status else "✅ Unbanned"
        await message.answer(
            f"{action_text} user `{uid}`",
            reply_markup=admin_back_kb(), parse_mode="Markdown"
        )
        try:
            msg = "🚫 You have been banned from this bot." if new_status else "✅ Your ban has been lifted!"
            await message.bot.send_message(uid, msg)
        except Exception:
            pass
    except ValueError:
        await message.answer("❌ Invalid Telegram ID:")


@router.callback_query(F.data == "admin_add_balance")
async def cb_add_balance(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return
    await state.set_state(AdminStates.add_balance_user)
    await callback.message.edit_text(
        "💵 *Add / Deduct Balance*\n\nSend the user's Telegram ID:",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.add_balance_user)
async def process_balance_user(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    try:
        user_id = int(message.text.strip())
        db = get_db()
        user = await db.users.find_one({"telegram_id": user_id})
        if not user:
            await message.answer("❌ User not found.")
            return
        await state.update_data(balance_user_id=user_id)
        await state.set_state(AdminStates.add_balance_amount)
        name = user.get("first_name", "Unknown")
        await message.answer(
            f"👤 User: *{name}* (`{user_id}`)\n"
            f"💰 Current Balance: `₹{float(user.get('balance', 0)):.2f}`\n\n"
            f"Enter amount _(negative = deduct)_:",
            parse_mode="Markdown"
        )
    except ValueError:
        await message.answer("❌ Invalid ID:")


@router.message(AdminStates.add_balance_amount)
async def process_balance_amount(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return
    try:
        amount = float(message.text.strip())
        data = await state.get_data()
        user_id = data.get("balance_user_id")
        new_balance = await add_balance(user_id, amount, reason="admin_manual")
        await state.clear()
        action = "added to" if amount > 0 else "deducted from"
        await message.answer(
            f"✅ *Balance Updated!*\n"
            f"👤 User: `{user_id}`\n"
            f"💰 {action.title()}: `₹{abs(amount):.2f}`\n"
            f"💎 New Balance: `₹{new_balance:.2f}`",
            reply_markup=admin_back_kb(), parse_mode="Markdown"
        )
        try:
            await message.bot.send_message(
                user_id,
                f"💰 Admin has {action} your balance: `₹{abs(amount):.2f}`\n"
                f"💎 New Balance: `₹{new_balance:.2f}`",
                parse_mode="Markdown"
            )
        except Exception:
            pass
    except ValueError:
        await message.answer("❌ Invalid amount:")


@router.callback_query(F.data == "admin_broadcast")
async def cb_broadcast(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        await callback.answer("❌ Access denied.", show_alert=True)
        return
    await state.set_state(AdminStates.broadcast)

    db = get_db()
    total = await db.users.count_documents({"is_banned": False})

    await callback.message.edit_text(
        f"📢 *Broadcast Message*\n\n"
        f"👥 Will be sent to `{total}` active users\n\n"
        f"Send your message:\n"
        f"• Text with *bold*, _italic_, `code`\n"
        f"• Or send a *photo with caption*\n"
        f"• Or *forward* any message",
        reply_markup=cancel_admin_kb(), parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.broadcast)
async def process_broadcast_preview(message: Message, state: FSMContext):
    if not await is_any_admin(message.from_user.id):
        return

    db = get_db()
    total = await db.users.count_documents({"is_banned": False})

    await state.update_data(
        broadcast_text=message.text,
        broadcast_photo=message.photo[-1].file_id if message.photo else None,
        broadcast_caption=message.caption if message.photo else None,
        broadcast_is_forward=bool(message.forward_from or message.forward_from_chat),
        broadcast_msg_id=message.message_id,
        broadcast_chat_id=message.chat.id,
    )
    await state.set_state(AdminStates.broadcast_confirm)

    preview_text = (
        f"📢 *Broadcast Preview*\n\n"
        f"👥 *Recipients:* `{total}` users\n\n"
        f"✅ Confirm to send broadcast?"
    )

    await message.answer(preview_text, reply_markup=broadcast_confirm_kb(), parse_mode="Markdown")


@router.callback_query(F.data == "broadcast_confirm")
async def cb_broadcast_confirm(callback: CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return

    data = await state.get_data()
    await state.clear()

    db = get_db()
    users = await db.users.find({"is_banned": False}, {"telegram_id": 1}).to_list(100000)

    sent = 0
    failed = 0
    status_msg = await callback.message.answer(
        f"📢 *Broadcasting...*\n`0 / {len(users)}`",
        parse_mode="Markdown"
    )

    broadcast_text = data.get("broadcast_text")
    broadcast_photo = data.get("broadcast_photo")
    broadcast_caption = data.get("broadcast_caption")
    src_chat_id = data.get("broadcast_chat_id")
    src_msg_id = data.get("broadcast_msg_id")

    for i, user in enumerate(users):
        try:
            uid = user["telegram_id"]
            if broadcast_photo:
                await callback.bot.send_photo(
                    uid,
                    photo=broadcast_photo,
                    caption=broadcast_caption or "",
                    parse_mode="Markdown"
                )
            elif broadcast_text:
                await callback.bot.send_message(uid, broadcast_text, parse_mode="Markdown")
            elif src_chat_id and src_msg_id:
                await callback.bot.forward_message(uid, src_chat_id, src_msg_id)
            sent += 1
        except Exception:
            failed += 1

        if (i + 1) % 50 == 0:
            try:
                await status_msg.edit_text(
                    f"📢 *Broadcasting...*\n`{i+1} / {len(users)}`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"✅ *Broadcast Complete!*\n\n"
        f"📤 *Sent:* `{sent}`\n"
        f"❌ *Failed:* `{failed}`\n"
        f"👥 *Total:* `{len(users)}`",
        reply_markup=admin_back_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()
