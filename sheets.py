from __future__ import annotations

import logging
import math
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

import gspread
from google.oauth2.service_account import Credentials

from config import (
    GOOGLE_CREDENTIALS_PATH,
    GOOGLE_SHEET_ID,
    SHEET_ACADEMY,
    SHEET_HOMEWORK,
    SHEET_CHILDREN,
    SHEET_SETTINGS,
    SHEET_HOLIDAYS,
    SHEET_REMINDER_TIMES,
    SHEET_WORKBOOK,
    SHEET_ONE_TIME_SCHEDULE,
    SHEET_DONE,
    DAY_MAP,
    DAY_NAMES,
)

# 숙제 날짜 비교에 사용할 형식들
_HW_DATE_FORMATS = ["%Y.%m.%d", "%Y. %m. %d.", "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"]

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_client() -> gspread.Client:
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)
    return gspread.authorize(creds)


def _get_spreadsheet() -> gspread.Spreadsheet:
    client = _get_client()
    return client.open_by_key(GOOGLE_SHEET_ID)


# ── 자녀 목록 ──────────────────────────────────────────────


def get_children() -> List[Dict]:
    """자녀목록 시트에서 {이름, chat_id, test_account} 리스트 반환.

    텔레그램_chat_id에 숫자가 아닌 값(test, test1, test2 등)을 적으면
    부모 chat_id로 대체하고 test_account 필드에 원래 값을 저장.
    """
    ws = _get_spreadsheet().worksheet(SHEET_CHILDREN)
    rows = ws.get_all_records()

    # test용: 부모 chat_id 미리 가져오기
    parent_chat_id = None
    try:
        settings = get_settings()
        parent_chat_id = int(settings.get("부모_텔레그램_chat_id", 0))
    except Exception:
        pass

    children = []
    for r in rows:
        try:
            name = str(r.get("이름", "")).strip()
            chat_id_raw = str(r.get("텔레그램_chat_id", "")).strip().lower()
            if not name or not chat_id_raw:
                continue
            # 숫자로 변환 불가 = 테스트 계정 (test, test1, test2 등)
            try:
                chat_id_int = int(float(chat_id_raw))
                children.append({"name": name, "chat_id": chat_id_int, "test_account": None})
            except ValueError:
                if parent_chat_id:
                    children.append({"name": name, "chat_id": parent_chat_id, "test_account": chat_id_raw})
                else:
                    logger.warning("테스트 계정(%s)인데 부모 chat_id가 설정에 없습니다", chat_id_raw)
        except (ValueError, KeyError) as e:
            logger.warning("자녀목록 파싱 오류, 행 스킵: %s (오류: %s)", r, e)
    return children


# ── 설정 ────────────────────────────────────────────────────


def get_settings() -> Dict[str, str]:
    """설정 시트에서 {항목: 값} 딕셔너리 반환."""
    ws = _get_spreadsheet().worksheet(SHEET_SETTINGS)
    rows = ws.get_all_records()
    return {str(r["항목"]).strip(): str(r["값"]).strip() for r in rows}


# ── 학원 고정 스케줄 ────────────────────────────────────────


def get_academy_schedule(child_name: str, weekday: int) -> List[Dict]:
    """특정 자녀의 특정 요일 학원 스케줄 반환.

    Returns:
        [{"학원명": str, "출발시간": str, "메모": str}, ...]
    """
    ws = _get_spreadsheet().worksheet(SHEET_ACADEMY)
    rows = ws.get_all_records()
    result = []
    for r in rows:
        name = str(r.get("자녀명", "")).strip()
        day_str = str(r.get("요일", "")).strip()
        if name != child_name:
            continue
        # "월,수,금" 같이 쉼표로 구분된 요일 지원
        days = [d.strip() for d in day_str.replace(" ", "").split(",")]
        if weekday not in [DAY_MAP.get(d) for d in days]:
            continue
        result.append({
            "학원명": str(r.get("학원명", "")).strip(),
            "출발시간": str(r.get("출발시간", "")).strip(),
            "메모": str(r.get("메모", "")).strip(),
        })
    return result


# ── 알림주기 파싱 ──────────────────────────────────────────


def _parse_day_schedule(schedule: str) -> Optional[List[int]]:
    """알림주기 문자열을 요일 번호 리스트로 변환.

    지원 형식:
      - "매일"       → [0,1,2,3,4,5,6]
      - "월,수,금"   → [0,2,4]
      - "월-토"      → [0,1,2,3,4,5]
      - "월-금"      → [0,1,2,3,4]
      - ""(빈값)     → None (날짜 기반 매칭 사용)
    """
    schedule = schedule.strip()
    if not schedule:
        return None

    if schedule == "매일":
        return list(range(7))

    # "월-토" 범위 형식
    if "-" in schedule and "," not in schedule:
        parts = schedule.split("-", 1)
        start = DAY_MAP.get(parts[0].strip())
        end = DAY_MAP.get(parts[1].strip())
        if start is not None and end is not None:
            if start <= end:
                return list(range(start, end + 1))
            else:
                # 예: 토-화 → [5,6,0,1]
                return list(range(start, 7)) + list(range(0, end + 1))
        return None

    # "월,수,금" 쉼표 형식
    days = [d.strip() for d in schedule.replace(" ", "").split(",")]
    result = []
    for d in days:
        num = DAY_MAP.get(d)
        if num is not None:
            result.append(num)
    return result if result else None


# ── 숙제 ────────────────────────────────────────────────────


def _parse_hw_date(date_str: str) -> Optional[date]:
    """숙제 날짜 문자열을 date로 변환. 여러 형식 지원."""
    date_str = str(date_str).strip().rstrip(".")  # 끝의 점 제거
    # 구글시트 "2026. 3. 16" → "2026.3.16" 로 정규화
    import re
    normalized = re.sub(r'\s*\.\s*', '.', date_str)
    for fmt in _HW_DATE_FORMATS:
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    # 구글시트가 숫자(시리얼)로 줄 수도 있음
    try:
        serial = int(float(date_str))
        if 40000 < serial < 60000:
            from datetime import timedelta
            return date(1899, 12, 30) + timedelta(days=serial)
    except (ValueError, TypeError):
        pass
    return None


def get_done_today(child_name: str, target_date: date) -> Dict[str, str]:
    """숙제_완료 시트에서 오늘 완료한 과목 → 완료시간 딕셔너리 반환.

    Returns:
        {"수학": "14:30", "영어": "15:45", ...}
    """
    try:
        ws = _get_spreadsheet().worksheet(SHEET_DONE)
    except gspread.exceptions.WorksheetNotFound:
        return {}

    today_str = target_date.strftime("%Y.%m.%d")
    rows = ws.get_all_records()
    result = {}
    for r in rows:
        if str(r.get("날짜", "")).strip() != today_str:
            continue
        if str(r.get("자녀명", "")).strip() != child_name:
            continue
        subject = str(r.get("과목", "")).strip()
        done_time = str(r.get("완료시간", "")).strip()
        if subject:
            result[subject] = done_time
    return result


def get_homework(child_name: str, target_date: date) -> List[Dict]:
    """특정 자녀의 특정 날짜 숙제 목록 반환.

    알림주기 컬럼이 있으면 요일 기반 필터링:
      - 알림주기가 비어있으면 → 날짜로 매칭 (1회성)
      - 알림주기가 "매일", "월,수,금" 등이면 → 해당 요일에만 포함

    완료여부는 숙제_완료 시트 기준으로 판단.

    Returns:
        [{"과목": str, "내용": str, "페이지": str, "완료여부": str, "완료시간": str, "row_index": int}, ...]
    """
    ws = _get_spreadsheet().worksheet(SHEET_HOMEWORK)
    rows = ws.get_all_records()
    today_weekday = target_date.weekday()
    done_map = get_done_today(child_name, target_date)
    result = []
    for idx, r in enumerate(rows, start=2):
        name = str(r.get("자녀명", "")).strip()
        if name != child_name:
            continue

        schedule_str = str(r.get("알림주기", "")).strip()
        day_list = _parse_day_schedule(schedule_str)

        if day_list is not None:
            if today_weekday not in day_list:
                continue
        else:
            hw_date_raw = str(r.get("날짜", "")).strip()
            hw_date = _parse_hw_date(hw_date_raw)
            if hw_date != target_date:
                if hw_date is None and hw_date_raw:
                    logger.warning("숙제 날짜 파싱 실패: '%s'", hw_date_raw)
                continue

        subject = str(r.get("과목", "")).strip()
        done_time = done_map.get(subject, "")
        result.append({
            "과목": subject,
            "내용": str(r.get("내용", "")).strip(),
            "페이지": str(r.get("페이지", "")).strip(),
            "완료여부": "O" if done_time else "",
            "완료시간": done_time,
            "row_index": idx,
        })
    return result


def get_incomplete_homework(child_name: str, target_date: date) -> List[Dict]:
    """완료되지 않은 숙제만 반환."""
    return [hw for hw in get_homework(child_name, target_date) if hw["완료여부"] != "O"]


def mark_homework_done(child_name: str, target_date: date, subject: str) -> bool:
    """특정 과목 숙제를 숙제_완료 시트에 기록. 성공 시 True 반환."""
    # 해당 숙제가 오늘 목록에 있는지 확인
    homework_list = get_homework(child_name, target_date)
    target_hw = next((hw for hw in homework_list if hw["과목"] == subject), None)
    if target_hw is None:
        return False

    # 이미 완료된 경우 중복 기록 방지
    if target_hw["완료여부"] == "O":
        return True

    # 숙제_완료 시트에 기록
    try:
        ws = _get_spreadsheet().worksheet(SHEET_DONE)
    except gspread.exceptions.WorksheetNotFound:
        logger.warning("'%s' 시트가 없습니다. 먼저 시트를 생성하세요.", SHEET_DONE)
        return False

    done_time = datetime.now().strftime("%H:%M")
    ws.append_row([
        target_date.strftime("%Y.%m.%d"),
        child_name,
        subject,
        done_time,
    ])
    logger.info("숙제 완료 기록: %s %s %s %s", target_date, child_name, subject, done_time)

    # 문제집 진도 자동 진행
    advance_workbook_page(child_name, subject)
    return True


def get_status_today(child_name: str, target_date: date) -> Dict:
    """오늘 숙제 현황 반환.

    Returns:
        {"total": int, "done": int, "details": [{"과목": str, "완료여부": str, "완료시간": str}, ...]}
    """
    homework = get_homework(child_name, target_date)
    total = len(homework)
    done = sum(1 for hw in homework if hw["완료여부"] == "O")
    details = [{"과목": hw["과목"], "완료여부": hw["완료여부"], "완료시간": hw["완료시간"]} for hw in homework]
    return {"total": total, "done": done, "details": details}


def add_homework(child_name: str, target_date: date, subject: str, content: str, page: str, schedule: str = "") -> None:
    """숙제를 구글 시트에 추가.

    Args:
        schedule: 알림주기 (예: "매일", "월,수,금"). 비어있으면 날짜 기반.
    """
    ws = _get_spreadsheet().worksheet(SHEET_HOMEWORK)
    headers = ws.row_values(1)
    date_str = target_date.strftime("%Y.%m.%d") if not schedule else ""

    # 헤더 기반으로 값 매핑
    row_data = {}
    row_data["자녀명"] = child_name
    row_data["날짜"] = date_str
    row_data["과목"] = subject
    row_data["내용"] = content
    row_data["페이지"] = page
    row_data["완료여부"] = ""
    if schedule:
        row_data["알림주기"] = schedule

    row = [row_data.get(h.strip(), "") for h in headers]
    ws.append_row(row)


# ── 알림시간 (자녀별 숙제 알림 시간) ──────────────────────────


def get_reminder_times() -> List[Dict]:
    """알림시간 시트에서 자녀별·요일별 숙제 알림 시간 반환.

    시트 컬럼: 자녀명 | 요일 | 알림시간
    예시:
      정꾸 | 월,수,목,금 | 13:30
      정꾸 | 화         | 14:40
      지꾸 | 월,수,금   | 15:45
      지꾸 | 화,목      | 17:00

    Returns:
        [{"자녀명": str, "요일": [int, ...], "시": int, "분": int}, ...]
    """
    try:
        ws = _get_spreadsheet().worksheet(SHEET_REMINDER_TIMES)
    except gspread.exceptions.WorksheetNotFound:
        logger.info("'%s' 시트가 없습니다. 자녀별 알림시간 미사용.", SHEET_REMINDER_TIMES)
        return []

    rows = ws.get_all_records()
    result = []
    for r in rows:
        name = str(r.get("자녀명", "")).strip()
        day_str = str(r.get("요일", "")).strip()
        time_str = str(r.get("알림시간", "")).strip()

        if not name or not time_str:
            continue

        # 요일 파싱
        day_list = _parse_day_schedule(day_str)
        if day_list is None:
            day_list = list(range(7))  # 요일 미지정이면 매일

        # 시간 파싱 ("13:30" → 시=13, 분=30)
        try:
            h, m = time_str.split(":")
            result.append({
                "자녀명": name,
                "요일": day_list,
                "시": int(h),
                "분": int(m),
            })
        except (ValueError, AttributeError):
            logger.warning("알림시간 파싱 오류: %s %s", name, time_str)

    return result


# ── 문제집 진도 ────────────────────────────────────────────

import re as _re


def _parse_amount(val) -> int:
    """1회양 파싱: '4p', '4P', '3쪽', '2일치', '5장', '4' 등 → 정수.

    지원 형식: 4p, 4P, 3쪽, 2일치, 5장, 단순 숫자
    """
    s = str(val).strip()
    if not s:
        return 0
    # 숫자 + 단위 패턴: "4p", "3쪽", "2일치", "5장" 등
    m = _re.match(r'^(\d+)\s*(p|P|쪽|장|일치|페이지)?$', s)
    if m:
        return int(m.group(1))
    # 단순 숫자 (float 대응)
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def _count_schedule_days(start_date: date, end_date: date, day_list: List[int]) -> int:
    """start_date~end_date 사이에 day_list에 해당하는 날 수 계산."""
    count = 0
    d = start_date
    while d <= end_date:
        if d.weekday() in day_list:
            count += 1
        d += timedelta(days=1)
    return count


def _find_nth_schedule_day(start_date: date, day_list: List[int], n: int) -> date:
    """start_date부터 day_list에 해당하는 n번째 날 찾기."""
    count = 0
    d = start_date
    while True:
        if d.weekday() in day_list:
            count += 1
            if count == n:
                return d
        d += timedelta(days=1)


def get_workbook_plans(child_name: Optional[str] = None) -> List[Dict]:
    """문제집_진도 시트에서 진도 목록 반환.

    시트 컬럼: 자녀명 | 과목 | 문제집명 | 시작페이지 | 끝페이지 | 현재페이지 | 주기 | 1회양 | 목표완료일 | 완료예정일
    """
    try:
        ws = _get_spreadsheet().worksheet(SHEET_WORKBOOK)
    except gspread.exceptions.WorksheetNotFound:
        logger.info("'%s' 시트가 없습니다.", SHEET_WORKBOOK)
        return []

    rows = ws.get_all_records()
    result = []
    for idx, r in enumerate(rows, start=2):
        name = str(r.get("자녀명", "")).strip()
        if child_name and name != child_name:
            continue

        def _int(val, default=0):
            try:
                return int(float(str(val).strip())) if str(val).strip() else default
            except (ValueError, TypeError):
                return default

        result.append({
            "자녀명": name,
            "과목": str(r.get("과목", "")).strip(),
            "문제집명": str(r.get("문제집명", "")).strip(),
            "시작페이지": _int(r.get("시작페이지"), 1),
            "끝페이지": _int(r.get("끝페이지"), 0),
            "현재페이지": _int(r.get("현재페이지"), 0),
            "주기": str(r.get("주기", "")).strip(),
            "1회양": _parse_amount(r.get("1회양")),
            "목표완료일": str(r.get("목표완료일", "")).strip(),
            "완료예정일": str(r.get("완료예정일", "")).strip(),
            "row_index": idx,
        })
    return result


def calculate_and_update_workbooks() -> None:
    """문제집_진도 시트의 1회양/완료예정일을 계산하여 자동 기록."""
    try:
        ws = _get_spreadsheet().worksheet(SHEET_WORKBOOK)
    except gspread.exceptions.WorksheetNotFound:
        return

    headers = ws.row_values(1)
    col_map = {h.strip(): i for i, h in enumerate(headers, start=1)}

    col_1회양 = col_map.get("1회양")
    col_완료예정일 = col_map.get("완료예정일")
    if not col_1회양 or not col_완료예정일:
        logger.warning("문제집_진도 시트에 '1회양' 또는 '완료예정일' 컬럼이 없습니다.")
        return

    rows = ws.get_all_records()
    today = date.today()
    updates = []  # (row, col, value) 배치 업데이트용

    for idx, r in enumerate(rows, start=2):
        def _int(val, default=0):
            try:
                return int(float(str(val).strip())) if str(val).strip() else default
            except (ValueError, TypeError):
                return default

        start_p = _int(r.get("시작페이지"), 1)
        end_p = _int(r.get("끝페이지"), 0)
        cur_p = _int(r.get("현재페이지"), 0)
        per_session = _parse_amount(r.get("1회양"))
        schedule_str = str(r.get("주기", "")).strip()
        target_date_str = str(r.get("목표완료일", "")).strip()

        if end_p <= 0:
            continue

        # 현재페이지가 0이면 시작페이지 기준
        if cur_p < start_p:
            cur_p = start_p

        remaining = end_p - cur_p
        if remaining <= 0:
            continue  # 이미 완료

        day_list = _parse_day_schedule(schedule_str)
        if day_list is None:
            day_list = list(range(7))  # 주기 미설정이면 매일

        # 목표완료일 → 1회양 계산
        target_date = _parse_hw_date(target_date_str) if target_date_str else None

        if target_date and per_session == 0:
            # 목표완료일이 있고 1회양이 비어있음 → 계산
            sessions = _count_schedule_days(today, target_date, day_list)
            if sessions > 0:
                per_session = math.ceil(remaining / sessions)
                updates.append((idx, col_1회양, per_session))

        elif per_session > 0 and not target_date:
            # 1회양이 있고 목표완료일이 비어있음 → 완료예정일 계산
            sessions_needed = math.ceil(remaining / per_session)
            finish_date = _find_nth_schedule_day(today, day_list, sessions_needed)
            updates.append((idx, col_완료예정일, finish_date.strftime("%Y.%m.%d")))

        elif target_date and per_session > 0:
            # 둘 다 있으면 완료예정일만 재계산 (1회양 기준)
            sessions_needed = math.ceil(remaining / per_session)
            finish_date = _find_nth_schedule_day(today, day_list, sessions_needed)
            updates.append((idx, col_완료예정일, finish_date.strftime("%Y.%m.%d")))

    # 시트에 일괄 업데이트
    for row, col, val in updates:
        ws.update_cell(row, col, val)
        logger.info("문제집_진도 업데이트: 행%d 열%d → %s", row, col, val)


def get_today_page_assignment(child_name: str, subject: str) -> Optional[str]:
    """오늘 해당 과목의 풀어야 할 페이지 범위 반환.

    Returns: "p.31~33" 같은 문자열, 또는 None
    """
    plans = get_workbook_plans(child_name)
    today_weekday = date.today().weekday()

    for p in plans:
        if p["과목"] != subject:
            continue

        day_list = _parse_day_schedule(p["주기"])
        if day_list is None:
            day_list = list(range(7))

        if today_weekday not in day_list:
            continue

        per_session = p["1회양"]
        if per_session <= 0:
            continue

        cur = p["현재페이지"]
        start = p["시작페이지"]
        if cur < start:
            cur = start

        end_p = p["끝페이지"]
        if cur >= end_p:
            continue  # 이미 완료

        page_from = cur + 1
        page_to = min(cur + per_session, end_p)

        if page_from == page_to:
            return f"p.{page_from}"
        return f"p.{page_from}~{page_to}"

    return None


def advance_workbook_page(child_name: str, subject: str) -> bool:
    """숙제 완료 시 문제집_진도의 현재페이지를 1회양만큼 진행. 성공 시 True."""
    try:
        ws = _get_spreadsheet().worksheet(SHEET_WORKBOOK)
    except gspread.exceptions.WorksheetNotFound:
        return False

    headers = ws.row_values(1)
    col_map = {h.strip(): i for i, h in enumerate(headers, start=1)}
    col_현재 = col_map.get("현재페이지")
    if not col_현재:
        return False

    rows = ws.get_all_records()
    for idx, r in enumerate(rows, start=2):
        name = str(r.get("자녀명", "")).strip()
        subj = str(r.get("과목", "")).strip()
        if name != child_name or subj != subject:
            continue

        def _int(val, default=0):
            try:
                return int(float(str(val).strip())) if str(val).strip() else default
            except (ValueError, TypeError):
                return default

        cur = _int(r.get("현재페이지"), 0)
        start_p = _int(r.get("시작페이지"), 1)
        per_session = _parse_amount(r.get("1회양"))
        end_p = _int(r.get("끝페이지"), 0)

        if per_session <= 0:
            return False

        if cur < start_p:
            cur = start_p

        new_page = min(cur + per_session, end_p)
        ws.update_cell(idx, col_현재, new_page)
        logger.info("문제집 진도 업데이트: %s %s → 현재페이지 %d", child_name, subject, new_page)
        return True

    return False


# ── 휴일 ────────────────────────────────────────────────────


def get_holidays() -> List[Dict]:
    """휴일 시트에서 [{날짜: str, 사유: str}, ...] 반환."""
    ws = _get_spreadsheet().worksheet(SHEET_HOLIDAYS)
    rows = ws.get_all_records()
    return [
        {"날짜": str(r.get("날짜", "")).strip(), "사유": str(r.get("사유", "")).strip()}
        for r in rows
    ]


# ── 1회성 스케줄 알림 ──────────────────────────────────────


def get_one_time_schedule_reminders(target_date: date) -> List[Dict]:
    """1회성_스케줄 시트에서 target_date에 발송해야 할 알림 목록 반환.

    시트 컬럼: 대상 | 날짜 | 시작시간 | 행위명 | 종료시간 | 알림주기
    알림주기 예: "1,3,7"  → 이벤트 1일 전, 3일 전, 7일 전에 각각 알림 발송

    Returns:
        [{"대상": str, "날짜": date, "시작시간": str, "행위명": str, "종료시간": str, "days_before": int}, ...]
    """
    import re as _re2
    try:
        ws = _get_spreadsheet().worksheet(SHEET_ONE_TIME_SCHEDULE)
    except gspread.exceptions.WorksheetNotFound:
        logger.info("'%s' 시트가 없습니다. 1회성 스케줄 미사용.", SHEET_ONE_TIME_SCHEDULE)
        return []

    rows = ws.get_all_records()
    result = []
    for r in rows:
        target_name = str(r.get("대상", "")).strip()
        date_str = str(r.get("날짜", "")).strip()
        start_time = str(r.get("시작시간", "")).strip()
        event_name = str(r.get("행위명", "")).strip()
        end_time = str(r.get("종료시간", "")).strip()
        reminder_str = str(r.get("알림주기", "")).strip()

        if not date_str or not event_name or not reminder_str:
            continue

        event_date = _parse_hw_date(date_str)
        if event_date is None:
            logger.warning("1회성 스케줄 날짜 파싱 실패: '%s'", date_str)
            continue

        # 알림주기 파싱: "1,3,7" 또는 "1일전,3일전,7일전" → [1, 3, 7]
        days_before_list = []
        for part in reminder_str.split(","):
            m = _re2.match(r"(\d+)", part.strip())
            if m:
                days_before_list.append(int(m.group(1)))

        # 당일(D-day) 알림: 0이 포함되어 있거나 알림주기와 무관하게 당일이면 포함
        if 0 not in days_before_list:
            days_before_list.append(0)

        for days_before in days_before_list:
            notify_date = event_date - timedelta(days=days_before)
            if notify_date == target_date:
                result.append({
                    "대상": target_name,
                    "날짜": event_date,
                    "시작시간": start_time,
                    "행위명": event_name,
                    "종료시간": end_time,
                    "days_before": days_before,
                })
                break  # 동일 이벤트 중복 알림 방지

    return result


def get_one_time_schedule_minute_reminders(now: datetime) -> List[Dict]:
    """1회성_스케줄 시트에서 now 기준 분전 알림 대상 반환.

    시트 컬럼 '분전_알림' 예: "30,60,90" → 시작시간 30/60/90분 전에 알림 발송

    Returns:
        [{"대상": str, "날짜": date, "시작시간": str, "행위명": str,
          "종료시간": str, "minutes_before": int}, ...]
    """
    import re as _re3
    try:
        ws = _get_spreadsheet().worksheet(SHEET_ONE_TIME_SCHEDULE)
    except gspread.exceptions.WorksheetNotFound:
        return []

    rows = ws.get_all_records()
    today = now.date() if hasattr(now, 'date') else now
    result = []
    for r in rows:
        target_name = str(r.get("대상", "")).strip()
        date_str = str(r.get("날짜", "")).strip()
        start_time = str(r.get("시작시간", "")).strip()
        event_name = str(r.get("행위명", "")).strip()
        end_time = str(r.get("종료시간", "")).strip()
        minute_reminder_str = str(r.get("분전_알림", "")).strip()

        if not date_str or not event_name or not start_time or not minute_reminder_str:
            continue

        event_date = _parse_hw_date(date_str)
        if event_date is None or event_date != today:
            continue

        # 분전_알림 파싱: "30,60,90" 또는 "30분,60분,90분" → [30, 60, 90]
        minutes_before_list = []
        for part in minute_reminder_str.split(","):
            m = _re3.match(r"(\d+)", part.strip())
            if m:
                minutes_before_list.append(int(m.group(1)))

        if not minutes_before_list:
            continue

        # 시작시간 파싱 (HH:MM 또는 HH:MM:SS)
        try:
            time_str = start_time[:5]  # "14:00:00" → "14:00"
            event_dt = datetime.strptime(time_str, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day
            )
        except ValueError:
            logger.warning("1회성 스케줄 시작시간 파싱 실패: '%s'", start_time)
            continue

        for mins in minutes_before_list:
            notify_dt = event_dt - timedelta(minutes=mins)
            diff = abs((now - notify_dt).total_seconds()) / 60
            if diff < 1:  # ±1분 범위
                result.append({
                    "대상": target_name,
                    "날짜": event_date,
                    "시작시간": start_time,
                    "행위명": event_name,
                    "종료시간": end_time,
                    "minutes_before": mins,
                })
                break  # 동일 이벤트 중복 알림 방지

    return result
