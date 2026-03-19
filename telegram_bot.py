from __future__ import annotations

import logging
from typing import List, Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from config import TELEGRAM_BOT_TOKEN

logger = logging.getLogger(__name__)

_bot: Optional[Bot] = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=TELEGRAM_BOT_TOKEN)
    return _bot


async def send_message(chat_id: int, text: str, retries: int = 3) -> bool:
    """텔레그램 메시지 발송. 실패 시 retries 횟수만큼 재시도."""
    bot = get_bot()
    for attempt in range(retries):
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            return True
        except TelegramError as e:
            logger.error("텔레그램 발송 실패 (시도 %d/%d, chat_id=%s): %s", attempt + 1, retries, chat_id, e)
    return False


async def send_message_with_buttons(chat_id: int, text: str, buttons: List[List[InlineKeyboardButton]], retries: int = 3) -> bool:
    """인라인 버튼이 포함된 메시지 발송."""
    bot = get_bot()
    markup = InlineKeyboardMarkup(buttons)
    for attempt in range(retries):
        try:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode="HTML")
            return True
        except TelegramError as e:
            logger.error("버튼 메시지 발송 실패 (시도 %d/%d): %s", attempt + 1, retries, e)
    return False


async def notify_parent(parent_chat_id: int, text: str) -> None:
    """부모에게 알림 메시지 발송 (에러 알림 등)."""
    await send_message(parent_chat_id, f"⚠️ [시스템 알림]\n{text}")
