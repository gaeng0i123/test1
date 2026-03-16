import logging
from datetime import date, timedelta

import sheets
from message_builder import build_weekly_report, build_full_weekly_report

logger = logging.getLogger(__name__)


def generate_weekly_report() -> str:
    """이번 주(월~일) 전체 주간 리포트 생성."""
    today = date.today()
    # 이번 주 월요일 ~ 일요일
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    week_label = f"{monday.month}/{monday.day}~{sunday.month}/{sunday.day}"

    children = sheets.get_children()
    child_reports = []

    for child in children:
        name = child["name"]
        total = 0
        done = 0
        incomplete = []

        for offset in range(7):
            day = monday + timedelta(days=offset)
            homework = sheets.get_homework(name, day)
            for hw in homework:
                total += 1
                if hw["완료여부"] == "O":
                    done += 1
                else:
                    page = f" {hw['페이지']}" if hw["페이지"] else ""
                    incomplete.append(f"{hw['과목']}{page}")

        report = build_weekly_report(name, week_label, total, done, incomplete)
        child_reports.append(report)

    return build_full_weekly_report(week_label, child_reports)
