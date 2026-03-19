import logging
from datetime import date, datetime, time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import sheets
from config import DAY_NAMES
from holidays import is_holiday
from message_builder import (
    build_morning_summary,
    build_academy_reminder,
    build_homework_reminder,
    build_one_time_schedule_reminder,
    build_one_time_schedule_minute_reminder,
)
from telegram_bot import send_message, send_message_with_buttons, notify_parent


def _homework_buttons(child_name: str, homework):
    """숙제 완료 버튼 목록 생성."""
    buttons = []
    for hw in homework:
        if hw.get("완료여부") != "O":
            buttons.append([InlineKeyboardButton(
                text=f"✅ {hw['과목']} 완료!",
                callback_data=f"done:{child_name}:{hw['과목']}"
            )])
    return buttons

logger = logging.getLogger(__name__)


def _fill_homework_pages(homework: list, child_name: str) -> list:
    """숙제 목록에서 페이지가 비어있는 항목에 문제집_진도의 오늘 분량을 채워넣기."""
    for hw in homework:
        if not hw["페이지"]:
            page = sheets.get_today_page_assignment(child_name, hw["과목"])
            if page:
                hw["페이지"] = page
    return homework


def _reset_recurring_homework_done() -> None:
    """알림주기가 있는 숙제의 완료여부를 매일 리셋 (아침 발송 전 호출)."""
    try:
        ws = sheets._get_spreadsheet().worksheet(sheets.SHEET_HOMEWORK)
        headers = ws.row_values(1)
        col_map = {h.strip(): i for i, h in enumerate(headers, start=1)}
        col_done = col_map.get("완료여부")
        if not col_done:
            return

        rows = ws.get_all_records()
        for idx, r in enumerate(rows, start=2):
            schedule_str = str(r.get("알림주기", "")).strip()
            done_str = str(r.get("완료여부", "")).strip()
            if schedule_str and done_str == "O":
                ws.update_cell(idx, col_done, "")
                logger.info("알림주기 숙제 완료여부 리셋: 행%d", idx)
    except Exception as e:
        logger.warning("완료여부 리셋 중 오류: %s", e)


async def send_morning_summary() -> None:
    """매일 아침: 오늘의 학원+숙제 요약 메시지 발송."""
    try:
        # 1회성 스케줄 사전 알림 체크
        await check_one_time_schedule_reminders()

        # 문제집 진도 계산 & 시트 업데이트
        sheets.calculate_and_update_workbooks()

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

            # 페이지가 비어있는 숙제에 문제집 진도 자동 채우기
            homework = _fill_homework_pages(homework, name)

            msg = build_morning_summary(name, today, academies, homework)
            if msg:
                buttons = _homework_buttons(name, homework)
                if buttons:
                    success = await send_message_with_buttons(chat_id, msg, buttons)
                else:
                    success = await send_message(chat_id, msg)
                if not success and parent_chat_id:
                    await notify_parent(parent_chat_id, f"{name}에게 아침 메시지 발송 실패")
                # 부모에게도 같은 메시지 전달
                if parent_chat_id and parent_chat_id != chat_id:
                    await send_message(parent_chat_id, f"[{name}] {msg}")
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
                    time_str = academy["출발시간"][:5]  # "17:40:00" → "17:40"
                    dep_time = datetime.strptime(time_str, "%H:%M").replace(
                        year=now.year, month=now.month, day=now.day
                    )
                    diff_minutes = (dep_time - now).total_seconds() / 60
                    # 알림 시간 ±1분 범위 내에 있으면 발송
                    if abs(diff_minutes - minutes_before) < 1:
                        msg = build_academy_reminder(name, academy, minutes_before)
                        # 탑승완료 버튼 추가
                        buttons = [[InlineKeyboardButton(
                            text=f"🚌 {academy['학원명']} 탑승완료!",
                            callback_data=f"ride:{name}:{academy['학원명']}"
                        )]]
                        success = await send_message_with_buttons(chat_id, msg, buttons)
                        if not success and parent_chat_id:
                            await notify_parent(parent_chat_id, f"{name} 학원 알림 발송 실패: {academy['학원명']}")
                        # 부모에게도 같은 알림 전달
                        if parent_chat_id and parent_chat_id != chat_id:
                            await send_message(parent_chat_id, f"[{name}] {msg}")
                except ValueError:
                    logger.warning("출발시간 파싱 오류: %s", academy["출발시간"])
    except Exception as e:
        logger.exception("학원 알림 체크 중 오류")


async def send_homework_reminder() -> None:
    """저녁: 미완료 숙제 알림 발송 (글로벌 시간, 알림시간 시트가 없을 때 폴백)."""
    try:
        children = sheets.get_children()
        settings = sheets.get_settings()
        parent_chat_id = int(settings.get("부모_텔레그램_chat_id", 0))
        today = date.today()

        for child in children:
            name = child["name"]
            chat_id = child["chat_id"]
            homework = sheets.get_incomplete_homework(name, today)
            homework = _fill_homework_pages(homework, name)

            msg = build_homework_reminder(name, homework)
            if msg:
                buttons = _homework_buttons(name, homework)
                if buttons:
                    success = await send_message_with_buttons(chat_id, msg, buttons)
                else:
                    success = await send_message(chat_id, msg)
                if not success and parent_chat_id:
                    await notify_parent(parent_chat_id, f"{name}에게 숙제 알림 발송 실패")
                # 부모에게도 같은 알림 전달
                if parent_chat_id and parent_chat_id != chat_id:
                    await send_message(parent_chat_id, f"[{name}] {msg}")
    except Exception as e:
        logger.exception("숙제 알림 발송 중 오류")
        try:
            settings = sheets.get_settings()
            parent_chat_id = int(settings.get("부모_텔레그램_chat_id", 0))
            if parent_chat_id:
                await notify_parent(parent_chat_id, f"숙제 알림 발송 중 오류: {e}")
        except Exception:
            logger.exception("부모 알림 발송도 실패")


async def check_one_time_schedule_reminders() -> None:
    """매일 아침: 1회성 스케줄 사전 알림 체크. 대상별로 발송."""
    try:
        settings = sheets.get_settings()
        parent_chat_id = int(settings.get("부모_텔레그램_chat_id", 0))
        if not parent_chat_id:
            return

        today = date.today()
        schedules = sheets.get_one_time_schedule_reminders(today)
        if not schedules:
            return

        # 대상별로 그룹핑
        children = {c["name"]: c["chat_id"] for c in sheets.get_children()}
        by_target: dict[str, list] = {}
        for s in schedules:
            target = s["대상"]
            by_target.setdefault(target, []).append(s)

        for target, items in by_target.items():
            msg = build_one_time_schedule_reminder(items)
            if not msg:
                continue

            # 대상이 자녀목록에 있으면 해당 자녀 + 부모에게, 없으면 부모에게만
            chat_id = children.get(target)
            if chat_id:
                await send_message(chat_id, msg)
                if parent_chat_id != chat_id:
                    await send_message(parent_chat_id, f"[{target}] {msg}")
            else:
                # 대상이 비어있거나 자녀목록에 없으면 부모에게만
                await send_message(parent_chat_id, msg)

        logger.info("1회성 스케줄 알림 발송: %d건", len(schedules))
    except Exception as e:
        logger.exception("1회성 스케줄 알림 체크 중 오류: %s", e)


async def check_one_time_schedule_minute_reminders() -> None:
    """매 분 실행: 1회성 스케줄 시작시간 N분 전이면 알림 발송."""
    try:
        settings = sheets.get_settings()
        parent_chat_id = int(settings.get("부모_텔레그램_chat_id", 0))
        if not parent_chat_id:
            return

        now = datetime.now()
        schedules = sheets.get_one_time_schedule_minute_reminders(now)
        if not schedules:
            return

        children = {c["name"]: c["chat_id"] for c in sheets.get_children()}
        by_target: dict[str, list] = {}
        for s in schedules:
            target = s["대상"]
            by_target.setdefault(target, []).append(s)

        for target, items in by_target.items():
            msg = build_one_time_schedule_minute_reminder(items)
            if not msg:
                continue

            chat_id = children.get(target)
            if chat_id:
                await send_message(chat_id, msg)
                if parent_chat_id != chat_id:
                    await send_message(parent_chat_id, f"[{target}] {msg}")
            else:
                await send_message(parent_chat_id, msg)

        logger.info("1회성 스케줄 분전 알림 발송: %d건", len(schedules))
    except Exception as e:
        logger.exception("1회성 스케줄 분전 알림 체크 중 오류: %s", e)


async def send_child_homework_reminder(child_name: str) -> None:
    """특정 자녀에게 미완료 숙제 알림 발송 (자녀별 알림시간용)."""
    try:
        children = sheets.get_children()
        settings = sheets.get_settings()
        parent_chat_id = int(settings.get("부모_텔레그램_chat_id", 0))
        today = date.today()

        # 해당 자녀 찾기
        child = None
        for c in children:
            if c["name"] == child_name:
                child = c
                break
        if not child:
            logger.warning("자녀별 알림: '%s'를 자녀목록에서 찾을 수 없음", child_name)
            return

        chat_id = child["chat_id"]
        homework = sheets.get_incomplete_homework(child_name, today)
        homework = _fill_homework_pages(homework, child_name)

        msg = build_homework_reminder(child_name, homework)
        if msg:
            buttons = _homework_buttons(child_name, homework)
            if buttons:
                success = await send_message_with_buttons(chat_id, msg, buttons)
            else:
                success = await send_message(chat_id, msg)
            if not success and parent_chat_id:
                await notify_parent(parent_chat_id, f"{child_name}에게 숙제 알림 발송 실패")
            if parent_chat_id and parent_chat_id != chat_id:
                await send_message(parent_chat_id, f"[{child_name}] {msg}")
    except Exception as e:
        logger.exception("자녀별 숙제 알림 발송 중 오류: %s", child_name)
