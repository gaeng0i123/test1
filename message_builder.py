from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from config import DAY_NAMES


def build_morning_summary(child_name: str, today: date, academies: List[Dict], homework: List[Dict]) -> Optional[str]:
    """매일 아침 요약 메시지 생성. 학원+숙제 모두 없으면 None 반환."""
    if not academies and not homework:
        return None

    day_name = DAY_NAMES[today.weekday()]
    lines = [f"📅 {child_name}아, 오늘({today.month}/{today.day} {day_name}요일) 일정이야!"]
    lines.append("")

    if academies:
        lines.append("🏫 학원")
        for a in academies:
            memo = f" ({a['메모']})" if a["메모"] else ""
            lines.append(f"  • {a['출발시간']} {a['학원명']}{memo}")
        lines.append("")

    if homework:
        lines.append("📚 숙제")
        for hw in homework:
            page = f" {hw['페이지']}" if hw["페이지"] else ""
            lines.append(f"  • {hw['과목']}: {hw['내용']}{page}")
        lines.append("")

    lines.append("화이팅! 💪")
    return "\n".join(lines)


def build_academy_reminder(child_name: str, academy: dict, minutes_before: int) -> str:
    """학원 출발 전 알림 메시지."""
    memo = f"\n📌 {academy['메모']}" if academy["메모"] else ""
    return (
        f"🏫 {academy['학원명']} 출발해!\n\n"
        f"⏰ {child_name}아, {minutes_before}분 후 출발!{memo}\n"
        f"준비하자! 🏃"
    )


def build_homework_reminder(child_name: str, homework: List[Dict]) -> Optional[str]:
    """저녁 숙제 알림 메시지. 남은 숙제가 없으면 None 반환."""
    if not homework:
        return None

    lines = [f"📚 {child_name}아, 아직 남은 숙제가 있어!"]
    lines.append("")
    for hw in homework:
        page = f" {hw['페이지']}" if hw["페이지"] else ""
        lines.append(f"  • {hw['과목']}: {hw['내용']}{page}")
    lines.append("")
    lines.append("다 하고 /done [과목] 으로 완료 체크해줘! ✅")
    return "\n".join(lines)


def build_done_response(child_name: str, subject: str) -> str:
    """숙제 완료 응답 메시지."""
    return f"✅ {subject} 숙제 완료! {child_name}아 잘했어 👍"


def build_weekly_report(child_name: str, week_label: str, total: int, done: int, incomplete: List[str]) -> str:
    """주간 리포트 (자녀 1명분)."""
    pct = int(done / total * 100) if total > 0 else 0
    lines = [f"👤 {child_name}"]
    lines.append(f"  ✅ 완료: {done}/{total} ({pct}%)")
    if incomplete:
        lines.append(f"  ❌ 미완료: {', '.join(incomplete)}")
    return "\n".join(lines)


def build_full_weekly_report(week_label: str, child_reports: List[str]) -> str:
    """전체 주간 리포트."""
    lines = [f"📊 이번 주 숙제 리포트 ({week_label})", ""]
    lines.extend(child_reports)
    return "\n".join(lines)


def build_one_time_schedule_reminder(schedules: List[Dict]) -> Optional[str]:
    """1회성 스케줄 사전 알림 메시지 생성."""
    if not schedules:
        return None

    lines = ["📅 다가오는 일정 알림!", ""]
    for s in schedules:
        event_date = s["날짜"]
        days_before = s["days_before"]
        target = s.get("대상", "")
        target_prefix = f"[{target}] " if target else ""
        time_range = ""
        if s["시작시간"]:
            time_range = s["시작시간"]
            if s["종료시간"]:
                time_range += f"~{s['종료시간']}"
        date_str = event_date.strftime("%Y.%m.%d")
        time_part = f" ({time_range})" if time_range else ""
        d_day = "D-Day!" if days_before == 0 else f"D-{days_before}"
        lines.append(f"  📌 {target_prefix}{s['행위명']}")
        lines.append(f"     📆 {date_str}{time_part}")
        lines.append(f"     ⏰ {d_day}")
        lines.append("")
    return "\n".join(lines).rstrip()


def build_one_time_schedule_minute_reminder(schedules: List[Dict]) -> Optional[str]:
    """1회성 스케줄 분전 알림 메시지 생성."""
    if not schedules:
        return None

    lines = ["⏰ 일정 알림!", ""]
    for s in schedules:
        event_date = s["날짜"]
        minutes_before = s["minutes_before"]
        target = s.get("대상", "")
        target_prefix = f"[{target}] " if target else ""
        time_range = ""
        if s["시작시간"]:
            time_range = s["시작시간"][:5]  # HH:MM
            if s["종료시간"]:
                time_range += f"~{s['종료시간'][:5]}"
        date_str = event_date.strftime("%Y.%m.%d")
        time_part = f" {time_range}" if time_range else ""
        lines.append(f"  📌 {target_prefix}{s['행위명']}")
        lines.append(f"     📆 {date_str}{time_part}")
        lines.append(f"     ⏰ {minutes_before}분 후 시작!")
        lines.append("")
    return "\n".join(lines).rstrip()


def build_status_message(today: date, child_statuses: List[Dict]) -> str:
    """오늘 숙제 현황 메시지 (부모용 수시 조회).

    child_statuses: [{"name": str, "total": int, "done": int, "details": [...]}, ...]
    """
    from config import DAY_NAMES
    day_name = DAY_NAMES[today.weekday()]
    lines = [f"📊 오늘({today.month}/{today.day} {day_name}요일) 숙제 현황", ""]

    for child in child_statuses:
        name = child["name"]
        total = child["total"]
        done = child["done"]
        details = child["details"]

        if total == 0:
            lines.append(f"👤 {name}: 오늘 숙제 없음")
        else:
            pct = int(done / total * 100)
            lines.append(f"👤 {name}  {done}/{total} ({pct}%)")
            for d in details:
                if d["완료여부"] == "O":
                    lines.append(f"  ✅ {d['과목']} ({d['완료시간']})")
                else:
                    lines.append(f"  ⬜ {d['과목']}")
        lines.append("")

    return "\n".join(lines).rstrip()
