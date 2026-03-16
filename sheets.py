import logging
from datetime import datetime, date

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
    DAY_MAP,
)

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


def get_children() -> list[dict]:
    """자녀목록 시트에서 {이름, chat_id} 리스트 반환."""
    ws = _get_spreadsheet().worksheet(SHEET_CHILDREN)
    rows = ws.get_all_records()
    children = []
    for r in rows:
        try:
            children.append({
                "name": str(r["이름"]).strip(),
                "chat_id": int(r["텔레그램_chat_id"]),
            })
        except (ValueError, KeyError):
            logger.warning("자녀목록 파싱 오류, 행 스킵: %s", r)
    return children


# ── 설정 ────────────────────────────────────────────────────


def get_settings() -> dict[str, str]:
    """설정 시트에서 {항목: 값} 딕셔너리 반환."""
    ws = _get_spreadsheet().worksheet(SHEET_SETTINGS)
    rows = ws.get_all_records()
    return {str(r["항목"]).strip(): str(r["값"]).strip() for r in rows}


# ── 학원 고정 스케줄 ────────────────────────────────────────


def get_academy_schedule(child_name: str, weekday: int) -> list[dict]:
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
        if DAY_MAP.get(day_str) != weekday:
            continue
        result.append({
            "학원명": str(r.get("학원명", "")).strip(),
            "출발시간": str(r.get("출발시간", "")).strip(),
            "메모": str(r.get("메모", "")).strip(),
        })
    return result


# ── 숙제 ────────────────────────────────────────────────────


def get_homework(child_name: str, target_date: date) -> list[dict]:
    """특정 자녀의 특정 날짜 숙제 목록 반환.

    Returns:
        [{"과목": str, "내용": str, "페이지": str, "완료여부": str, "row_index": int}, ...]
    """
    ws = _get_spreadsheet().worksheet(SHEET_HOMEWORK)
    rows = ws.get_all_records()
    date_str = target_date.strftime("%Y-%m-%d")
    result = []
    for idx, r in enumerate(rows, start=2):  # 헤더가 1행
        name = str(r.get("자녀명", "")).strip()
        hw_date = str(r.get("날짜", "")).strip()
        if name != child_name or hw_date != date_str:
            continue
        result.append({
            "과목": str(r.get("과목", "")).strip(),
            "내용": str(r.get("내용", "")).strip(),
            "페이지": str(r.get("페이지", "")).strip(),
            "완료여부": str(r.get("완료여부", "")).strip(),
            "row_index": idx,
        })
    return result


def get_incomplete_homework(child_name: str, target_date: date) -> list[dict]:
    """완료되지 않은 숙제만 반환."""
    return [hw for hw in get_homework(child_name, target_date) if hw["완료여부"] != "O"]


def mark_homework_done(child_name: str, target_date: date, subject: str) -> bool:
    """특정 과목 숙제를 완료 처리. 성공 시 True 반환."""
    ws = _get_spreadsheet().worksheet(SHEET_HOMEWORK)
    rows = ws.get_all_records()
    date_str = target_date.strftime("%Y-%m-%d")
    for idx, r in enumerate(rows, start=2):
        name = str(r.get("자녀명", "")).strip()
        hw_date = str(r.get("날짜", "")).strip()
        hw_subject = str(r.get("과목", "")).strip()
        if name == child_name and hw_date == date_str and hw_subject == subject:
            # 완료여부는 6번째 컬럼 (F열)
            ws.update_cell(idx, 6, "O")
            return True
    return False


def add_homework(child_name: str, target_date: date, subject: str, content: str, page: str) -> None:
    """숙제를 구글 시트에 추가."""
    ws = _get_spreadsheet().worksheet(SHEET_HOMEWORK)
    ws.append_row([
        target_date.strftime("%Y-%m-%d"),
        child_name,
        subject,
        content,
        page,
        "",  # 완료여부
    ])


# ── 휴일 ────────────────────────────────────────────────────


def get_holidays() -> list[dict]:
    """휴일 시트에서 [{날짜: str, 사유: str}, ...] 반환."""
    ws = _get_spreadsheet().worksheet(SHEET_HOLIDAYS)
    rows = ws.get_all_records()
    return [
        {"날짜": str(r.get("날짜", "")).strip(), "사유": str(r.get("사유", "")).strip()}
        for r in rows
    ]
