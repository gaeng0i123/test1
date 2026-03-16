#!/usr/bin/env python3
"""자녀 학원/숙제 자동 메시지 알림 봇."""

import argparse
import asyncio
import logging
import sys
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram.ext import ApplicationBuilder, CommandHandler

import sheets
from commands import handle_done, handle_add, handle_today, handle_send, handle_status
from config import TELEGRAM_BOT_TOKEN
from message_builder import build_morning_summary
from scheduler import send_morning_summary, check_academy_reminders, send_homework_reminder
from stats import generate_weekly_report
from telegram_bot import send_message, notify_parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def send_weekly_report() -> None:
    """주간 리포트를 부모에게 발송."""
    try:
        settings = sheets.get_settings()
        parent_chat_id = int(settings.get("부모_텔레그램_chat_id", 0))
        if parent_chat_id:
            report = generate_weekly_report()
            await send_message(parent_chat_id, report)
    except Exception as e:
        logger.exception("주간 리포트 발송 오류: %s", e)


async def run_test() -> None:
    """테스트: 모든 자녀에게 즉시 아침 요약 메시지 발송."""
    logger.info("테스트 모드: 메시지 발송 시작")

    children = sheets.get_children()
    today = date.today()

    for child in children:
        name = child["name"]
        chat_id = child["chat_id"]
        academies = sheets.get_academy_schedule(name, today.weekday())
        homework = sheets.get_homework(name, today)

        msg = build_morning_summary(name, today, academies, homework)
        if msg:
            success = await send_message(chat_id, msg)
            status = "성공" if success else "실패"
            logger.info("%s (chat_id=%s): %s", name, chat_id, status)
        else:
            logger.info("%s: 오늘 일정 없음", name)

    # 부모에게도 테스트 알림
    settings = sheets.get_settings()
    parent_chat_id = int(settings.get("부모_텔레그램_chat_id", 0))
    if parent_chat_id:
        await send_message(parent_chat_id, "✅ 테스트 발송 완료!")

    logger.info("테스트 완료")


def main() -> None:
    parser = argparse.ArgumentParser(description="자녀 학원/숙제 알림 봇")
    parser.add_argument("--test", action="store_true", help="즉시 테스트 메시지 발송")
    args = parser.parse_args()

    if args.test:
        asyncio.run(run_test())
        return

    # 설정 읽기
    settings = sheets.get_settings()
    morning_time = settings.get("아침_발송시간", "07:00")
    homework_time = settings.get("숙제_발송시간", "19:00")
    timezone = settings.get("시간대", "Asia/Seoul")

    morning_h, morning_m = morning_time.split(":")
    homework_h, homework_m = homework_time.split(":")

    # 텔레그램 봇 Application (명령어 핸들러 등록)
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("done", handle_done))
    app.add_handler(CommandHandler("add", handle_add))
    app.add_handler(CommandHandler("today", handle_today))
    app.add_handler(CommandHandler("send", handle_send))
    app.add_handler(CommandHandler("status", handle_status))

    # APScheduler 설정
    ap_scheduler = AsyncIOScheduler(timezone=timezone)

    # ① 매일 아침 요약
    ap_scheduler.add_job(
        send_morning_summary,
        CronTrigger(hour=int(morning_h), minute=int(morning_m)),
        id="morning_summary",
    )

    # ② 학원 출발 전 알림 (매 분 체크)
    ap_scheduler.add_job(
        check_academy_reminders,
        CronTrigger(minute="*"),
        id="academy_reminder",
    )

    # ③ 저녁 숙제 알림
    ap_scheduler.add_job(
        send_homework_reminder,
        CronTrigger(hour=int(homework_h), minute=int(homework_m)),
        id="homework_reminder",
    )

    # ④ 주간 통계 (매주 일요일 20:00)
    ap_scheduler.add_job(
        send_weekly_report,
        CronTrigger(day_of_week="sun", hour=20, minute=0),
        id="weekly_report",
    )

    ap_scheduler.start()
    logger.info("봇 시작! (아침: %s, 숙제: %s, 시간대: %s)", morning_time, homework_time, timezone)

    # 텔레그램 봇 polling 시작 (blocking)
    app.run_polling()


if __name__ == "__main__":
    main()
