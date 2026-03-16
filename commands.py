import logging
from datetime import date, datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

import sheets
from message_builder import (
    build_morning_summary,
    build_done_response,
)

logger = logging.getLogger(__name__)


def _resolve_date(date_text: str) -> date:
    """'오늘', '내일', '모레' 또는 날짜 문자열을 date로 변환."""
    today = date.today()
    if date_text == "오늘":
        return today
    if date_text == "내일":
        return today + timedelta(days=1)
    if date_text == "모레":
        return today + timedelta(days=2)
    return datetime.strptime(date_text, "%Y-%m-%d").date()


def _get_child_chat_id(children: list[dict], name: str) -> int | None:
    for c in children:
        if c["name"] == name:
            return c["chat_id"]
    return None


def _get_child_name_by_chat_id(children: list[dict], chat_id: int) -> str | None:
    for c in children:
        if c["chat_id"] == chat_id:
            return c["name"]
    return None


def _get_parent_chat_id() -> int | None:
    try:
        settings = sheets.get_settings()
        return int(settings.get("부모_텔레그램_chat_id", 0))
    except Exception:
        return None


def _is_parent(chat_id: int) -> bool:
    parent_id = _get_parent_chat_id()
    return parent_id is not None and chat_id == parent_id


# ── 자녀 명령어: /done ──────────────────────────────────────


async def handle_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/done [과목] - 자녀가 숙제 완료 체크."""
    chat_id = update.effective_chat.id
    children = sheets.get_children()
    child_name = _get_child_name_by_chat_id(children, chat_id)

    if not child_name:
        await update.message.reply_text("등록된 사용자가 아닙니다.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("사용법: /done [과목]\n예: /done 수학")
        return

    subject = args[0]
    today = date.today()
    success = sheets.mark_homework_done(child_name, today, subject)

    if success:
        await update.message.reply_text(build_done_response(child_name, subject))
    else:
        await update.message.reply_text(f"'{subject}' 숙제를 찾을 수 없어요. 과목명을 확인해주세요.")


# ── 부모 명령어: /add ────────────────────────────────────────


async def handle_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/add [자녀명] [날짜] [과목] [내용] [페이지] - 숙제 추가."""
    chat_id = update.effective_chat.id
    if not _is_parent(chat_id):
        await update.message.reply_text("부모 계정만 사용 가능합니다.")
        return

    args = context.args
    if not args or len(args) < 4:
        await update.message.reply_text(
            "사용법: /add [자녀명] [날짜] [과목] [내용] [페이지]\n"
            "예: /add 민준 내일 수학 문제집 p.30~35"
        )
        return

    child_name = args[0]
    try:
        target_date = _resolve_date(args[1])
    except ValueError:
        await update.message.reply_text("날짜 형식 오류. '오늘', '내일', '모레' 또는 YYYY-MM-DD 형식을 사용하세요.")
        return

    subject = args[2]
    content = args[3]
    page = args[4] if len(args) > 4 else ""

    sheets.add_homework(child_name, target_date, subject, content, page)
    await update.message.reply_text(
        f"✅ 숙제 추가 완료!\n"
        f"  • {child_name} | {target_date} | {subject}: {content} {page}"
    )


# ── 부모 명령어: /today ──────────────────────────────────────


async def handle_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/today [자녀명] - 오늘 일정 조회."""
    chat_id = update.effective_chat.id
    if not _is_parent(chat_id):
        await update.message.reply_text("부모 계정만 사용 가능합니다.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("사용법: /today [자녀명]\n예: /today 민준")
        return

    child_name = args[0]
    today = date.today()
    academies = sheets.get_academy_schedule(child_name, today.weekday())
    homework = sheets.get_homework(child_name, today)

    msg = build_morning_summary(child_name, today, academies, homework)
    if msg:
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text(f"{child_name}의 오늘 일정이 없습니다.")


# ── 부모 명령어: /send ───────────────────────────────────────


async def handle_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/send [자녀명] [메시지] - 자녀에게 즉시 메시지 전송."""
    chat_id = update.effective_chat.id
    if not _is_parent(chat_id):
        await update.message.reply_text("부모 계정만 사용 가능합니다.")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text("사용법: /send [자녀명] [메시지]\n예: /send 민준 도시락 챙겨!")
        return

    child_name = args[0]
    message = " ".join(args[1:])
    children = sheets.get_children()
    child_chat_id = _get_child_chat_id(children, child_name)

    if not child_chat_id:
        await update.message.reply_text(f"'{child_name}'을 찾을 수 없습니다.")
        return

    from telegram_bot import send_message
    success = await send_message(child_chat_id, f"📩 엄마/아빠가 보낸 메시지:\n\n{message}")
    if success:
        await update.message.reply_text(f"✅ {child_name}에게 메시지를 보냈습니다.")
    else:
        await update.message.reply_text(f"❌ 메시지 발송에 실패했습니다.")


# ── 부모 명령어: /status ─────────────────────────────────────


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/status - 오늘 숙제 완료 현황."""
    chat_id = update.effective_chat.id
    if not _is_parent(chat_id):
        await update.message.reply_text("부모 계정만 사용 가능합니다.")
        return

    children = sheets.get_children()
    today = date.today()
    lines = [f"📋 오늘({today.month}/{today.day}) 숙제 현황", ""]

    for child in children:
        name = child["name"]
        homework = sheets.get_homework(name, today)
        if not homework:
            lines.append(f"👤 {name}: 오늘 숙제 없음")
        else:
            done = sum(1 for hw in homework if hw["완료여부"] == "O")
            total = len(homework)
            lines.append(f"👤 {name}: {done}/{total} 완료")
            for hw in homework:
                status = "✅" if hw["완료여부"] == "O" else "⬜"
                page = f" {hw['페이지']}" if hw["페이지"] else ""
                lines.append(f"  {status} {hw['과목']}: {hw['내용']}{page}")
        lines.append("")

    await update.message.reply_text("\n".join(lines))
