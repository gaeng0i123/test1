import logging
from datetime import date, datetime, time

import sheets
from holidays import is_holiday
from message_builder import (
    build_morning_summary,
    build_academy_reminder,
    build_homework_reminder,
)
from telegram_bot import send_message, notify_parent

logger = logging.getLogger(__name__)


async def send_morning_summary() -> None:
    """매일 아침: 오늘의 학원+숙제 요약 메시지 발송."""
    try:
        children = sheets.get_children()
        settings = sheets.get_settings()
        parent_chat_id = int(settings.get("부모_텔레그램_chat_id", 0))
        holiday_data = sheets.get_holidays()
        today = date.today()
        is_hol = is_holiday(today, holiday_data)

        for child in children:
            name = child["name"]
            chat_id = child["chat_id"]

            # 휴일이면 학원 스케줄 제외
            academies = [] if is_hol else sheets.get_academy_schedule(name, today.weekday())
            homework = sheets.get_homework(name, today)

            msg = build_morning_summary(name, today, academies, homework)
            if msg:
                success = await send_message(chat_id, msg)
                if not success and parent_chat_id:
                    await notify_parent(parent_chat_id, f"{name}에게 아침 메시지 발송 실패")
    except Exception as e:
        logger.exception("아침 요약 발송 중 오류")
        try:
            settings = sheets.get_settings()
            parent_chat_id = int(settings.get("부모_텔레그램_chat_id", 0))
            if parent_chat_id:
                await notify_parent(parent_chat_id, f"아침 요약 발송 중 오류: {e}")
        except Exception:
            logger.exception("부모 알림 발송도 실패")


async def check_academy_reminders() -> None:
    """매 분 실행: 학원 출발 시간 N분 전이면 알림 발송."""
    try:
        children = sheets.get_children()
        settings = sheets.get_settings()
        parent_chat_id = int(settings.get("부모_텔레그램_chat_id", 0))
        minutes_before = int(settings.get("학원전_알림_분", 30))
        holiday_data = sheets.get_holidays()
        today = date.today()

        if is_holiday(today, holiday_data):
            return

        now = datetime.now()

        for child in children:
            name = child["name"]
            chat_id = child["chat_id"]
            academies = sheets.get_academy_schedule(name, today.weekday())

            for academy in academies:
                try:
                    dep_time = datetime.strptime(academy["출발시간"], "%H:%M").replace(
                        year=now.year, month=now.month, day=now.day
                    )
                    diff_minutes = (dep_time - now).total_seconds() / 60
                    # 알림 시간 ±1분 범위 내에 있으면 발송
                    if abs(diff_minutes - minutes_before) < 1:
                        msg = build_academy_reminder(name, academy, minutes_before)
                        success = await send_message(chat_id, msg)
                        if not success and parent_chat_id:
                            await notify_parent(parent_chat_id, f"{name} 학원 알림 발송 실패: {academy['학원명']}")
                except ValueError:
                    logger.warning("출발시간 파싱 오류: %s", academy["출발시간"])
    except Exception as e:
        logger.exception("학원 알림 체크 중 오류")


async def send_homework_reminder() -> None:
    """저녁: 미완료 숙제 알림 발송."""
    try:
        children = sheets.get_children()
        settings = sheets.get_settings()
        parent_chat_id = int(settings.get("부모_텔레그램_chat_id", 0))
        today = date.today()

        for child in children:
            name = child["name"]
            chat_id = child["chat_id"]
            homework = sheets.get_incomplete_homework(name, today)

            msg = build_homework_reminder(name, homework)
            if msg:
                success = await send_message(chat_id, msg)
                if not success and parent_chat_id:
                    await notify_parent(parent_chat_id, f"{name}에게 숙제 알림 발송 실패")
    except Exception as e:
        logger.exception("숙제 알림 발송 중 오류")
        try:
            settings = sheets.get_settings()
            parent_chat_id = int(settings.get("부모_텔레그램_chat_id", 0))
            if parent_chat_id:
                await notify_parent(parent_chat_id, f"숙제 알림 발송 중 오류: {e}")
        except Exception:
            logger.exception("부모 알림 발송도 실패")
