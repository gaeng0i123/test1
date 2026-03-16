import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)


def is_holiday(target_date: date, holiday_data: list[dict]) -> bool:
    """해당 날짜가 휴일인지 확인.

    방학 처리: '여름방학시작' 같은 사유가 있으면 '여름방학끝'을 찾아서
    범위 내에 있는지 확인.
    """
    single_dates = []
    vacation_ranges = []

    for h in holiday_data:
        try:
            h_date = datetime.strptime(h["날짜"], "%Y-%m-%d").date()
        except ValueError:
            logger.warning("휴일 날짜 파싱 오류: %s", h["날짜"])
            continue

        reason = h["사유"]

        if "방학시작" in reason:
            # 같은 종류의 방학끝을 찾음
            prefix = reason.replace("시작", "")  # 예: "여름방학"
            end_entry = _find_vacation_end(prefix, holiday_data)
            if end_entry:
                vacation_ranges.append((h_date, end_entry))
            else:
                single_dates.append(h_date)
        elif "방학끝" not in reason:
            single_dates.append(h_date)

    if target_date in single_dates:
        return True

    for start, end in vacation_ranges:
        if start <= target_date <= end:
            return True

    return False


def _find_vacation_end(prefix: str, holiday_data: list[dict]) -> date | None:
    """방학끝 날짜를 찾아 반환."""
    for h in holiday_data:
        if prefix + "끝" == h["사유"].replace(" ", ""):
            try:
                return datetime.strptime(h["날짜"], "%Y-%m-%d").date()
            except ValueError:
                return None
    return None
