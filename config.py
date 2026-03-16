import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")

# 구글 시트 이름
SHEET_ACADEMY = "학원_고정스케줄"
SHEET_HOMEWORK = "숙제_주간계획"
SHEET_CHILDREN = "자녀목록"
SHEET_SETTINGS = "설정"
SHEET_HOLIDAYS = "휴일"
SHEET_REMINDER_TIMES = "알림시간"
SHEET_WORKBOOK = "문제집_진도"
SHEET_ONE_TIME_SCHEDULE = "1회성_스케줄"

# 요일 매핑 (한글 → 숫자)
DAY_MAP = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
DAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]
