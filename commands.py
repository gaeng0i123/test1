from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import sheets
from message_builder import (
    build_morning_summary,
    build_done_response,
    build_status_message,
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


def _get_child_chat_id(children: List[Dict], name: str) -> Optional[int]:
    for c in children:
        if c["name"] == name:
            return c["chat_id"]
    return None


def _get_child_name_by_chat_id(children: List[Dict], chat_id: int) -> Optional[str]:
    for c in children:
        if c["chat_id"] == chat_id:
            return c["name"]
    return None


def _get_parent_chat_id() -> Optional[int]:
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
    if not update.message:
        return
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


# ── 자녀: 숙제 완료 버튼 콜백 ──────────────────────────────


async def handle_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """인라인 버튼 클릭 시 숙제 완료 처리."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    # callback_data 형식: "done:자녀명:과목"
    data = query.data
    if not data or not data.startswith("done:"):
        return

    parts = data.split(":", 2)
    if len(parts) < 3:
        return

    child_name = parts[1]
    subject = parts[2]
    today = date.today()

    success = sheets.mark_homework_done(child_name, today, subject)
    if success:
        await query.edit_message_text(
            text=query.message.text.replace(
                f"⬜ {subject}", f"✅ {subject}"
            ),
            reply_markup=_rebuild_homework_buttons(child_name, today)
        )
        # 부모에게 알림
        parent_id = _get_parent_chat_id()
        if parent_id:
            from telegram_bot import send_message
            await send_message(parent_id, f"✅ {child_name}이(가) {subject} 숙제를 완료했어요!")
    else:
        await query.answer(f"'{subject}' 숙제를 찾을 수 없어요.", show_alert=True)


def _rebuild_homework_buttons(child_name: str, target_date: date) -> InlineKeyboardMarkup:
    """미완료 숙제만 버튼으로 다시 구성."""
    homework = sheets.get_homework(child_name, target_date)
    buttons = []
    for hw in homework:
        if hw["완료여부"] != "O":
            buttons.append([InlineKeyboardButton(
                text=f"✅ {hw['과목']} 완료!",
                callback_data=f"done:{child_name}:{hw['과목']}"
            )])
    return InlineKeyboardMarkup(buttons)


# ── 자녀: 학원 탑승완료 버튼 콜백 ─────────────────────────────


async def handle_ride_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """학원 탑승완료 버튼 클릭 시 처리."""
    query = update.callback_query
    if not query:
        return
    await query.answer("탑승 확인! 👍")

    data = query.data
    if not data or not data.startswith("ride:"):
        return

    parts = data.split(":", 2)
    if len(parts) < 3:
        return

    child_name = parts[1]
    academy_name = parts[2]
    now = datetime.now().strftime("%H:%M")

    # 버튼을 "탑승완료" 텍스트로 교체
    await query.edit_message_text(
        text=query.message.text + f"\n\n🚌 {now} 탑승완료! ✅"
    )

    # 부모에게 알림
    parent_id = _get_parent_chat_id()
    if parent_id:
        from telegram_bot import send_message
        await send_message(parent_id, f"🚌 {child_name}이(가) {academy_name} 탑승완료! ({now})")


# ── 부모 명령어: /add ────────────────────────────────────────


async def handle_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/add [자녀명] [날짜] [과목] [내용] [페이지] - 숙제 추가."""
    if not update.message:
        return
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
    if not update.message:
        return
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
    if not update.message:
        return
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


def _build_status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 새로고침", callback_data="status:refresh")
    ]])


async def _send_status(chat_id: int, context) -> str:
    """현황 메시지 생성 (공통 로직)."""
    children = sheets.get_children()
    today = date.today()
    child_statuses = []
    for child in children:
        status = sheets.get_status_today(child["name"], today)
        child_statuses.append({"name": child["name"], **status})
    return build_status_message(today, child_statuses)


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/status - 오늘 숙제 완료 현황 (새로고침 버튼 포함)."""
    if not update.message:
        return
    chat_id = update.effective_chat.id
    if not _is_parent(chat_id):
        await update.message.reply_text("부모 계정만 사용 가능합니다.")
        return

    msg = await _send_status(chat_id, context)
    await update.message.reply_text(msg, reply_markup=_build_status_keyboard())


async def handle_status_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """현황 새로고침 버튼 콜백."""
    query = update.callback_query
    if not query:
        return
    await query.answer("새로고침 중...")

    chat_id = update.effective_chat.id
    msg = await _send_status(chat_id, context)
    await query.edit_message_text(msg, reply_markup=_build_status_keyboard())


# ── 부모 명령어: /menu ────────────────────────────────────────


async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/menu - 부모 메뉴 (인라인 버튼)."""
    if not update.message:
        return
    chat_id = update.effective_chat.id
    if not _is_parent(chat_id):
        await update.message.reply_text("부모 계정만 사용 가능합니다.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 현황조회", callback_data="status:refresh")],
        [InlineKeyboardButton("📅 오늘 일정 조회", callback_data="menu:today_all")],
    ])
    await update.message.reply_text("📋 부모 메뉴", reply_markup=keyboard)


async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """부모 메뉴 버튼 콜백."""
    query = update.callback_query
    if not query:
        return

    data = query.data

    if data == "status:refresh":
        await query.answer("현황 조회 중...")
        msg = await _send_status(update.effective_chat.id, context)
        await query.edit_message_text(msg, reply_markup=_build_status_keyboard())

    elif data == "menu:today_all":
        await query.answer()
        children = sheets.get_children()
        today = date.today()
        lines = []
        for child in children:
            name = child["name"]
            academies = sheets.get_academy_schedule(name, today.weekday())
            homework = sheets.get_homework(name, today)
            msg = build_morning_summary(name, today, academies, homework)
            if msg:
                lines.append(msg)
        result = "\n\n---\n\n".join(lines) if lines else "오늘 일정이 없습니다."
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("◀ 메뉴로", callback_data="menu:back")
        ]])
        await query.edit_message_text(result, reply_markup=keyboard)

    elif data == "menu:back":
        await query.answer()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 현황조회", callback_data="status:refresh")],
            [InlineKeyboardButton("📅 오늘 일정 조회", callback_data="menu:today_all")],
        ])
        await query.edit_message_text("📋 부모 메뉴", reply_markup=keyboard)
