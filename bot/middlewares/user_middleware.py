from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from bot.services.wallet_service import get_or_create_user


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user:
            db_user = await get_or_create_user(
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
            )
            data["db_user"] = db_user

            if db_user.get("is_banned"):
                if isinstance(event, Message):
                    await event.answer("🚫 You have been banned from using this bot.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🚫 You have been banned.", show_alert=True)
                return

        return await handler(event, data)
