from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from bot.database import get_db
from bot.services.settings_service import get_setting

router = Router()


@router.callback_query(F.data == "referral")
async def cb_referral(callback: CallbackQuery, db_user: dict = None):
    if not db_user:
        await callback.answer("User not found.", show_alert=True)
        return

    user_id = callback.from_user.id
    db = get_db()

    referral_percent = await get_setting("referral_percent", 3.0)
    referral_bonus = await get_setting("referral_bonus", 10.0)

    referral_code = db_user.get("referral_code", "N/A")
    referral_earnings = float(db_user.get("referral_earnings", 0.0))
    referred_count = await db.users.count_documents({"referred_by": user_id})

    bot_info = await callback.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{referral_code}"

    text = (
        f"🎁 *Refer & Earn*\n\n"
        f"Earn *{referral_percent:.1f}% bonus* on every deposit your referrals make!\n"
        f"Plus `₹{referral_bonus:.0f}` instant bonus when they join!\n\n"
        f"🔗 *Your Referral Link:*\n"
        f"`{ref_link}`\n\n"
        f"👥 *Total Referred:* {referred_count}\n"
        f"💰 *Total Earned:* `₹{referral_earnings:.2f}`\n\n"
        f"📋 *How it works:*\n"
        f"1️⃣ Share your link\n"
        f"2️⃣ Friend joins & deposits\n"
        f"3️⃣ You get *{referral_percent:.1f}%* of their deposit!\n\n"
        f"_No limit — earn unlimited!_ ✨"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📤 Share Referral Link",
            url=f"https://t.me/share/url?url={ref_link}&text=Join%20this%20bot!"
        )],
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")],
    ])

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()
