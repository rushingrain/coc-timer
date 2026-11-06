"""FastAPI and HTMX interface for the completion-time calculator."""

import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .domain import (
    BOOST_LIST,
    BOOSTS,
    BUILDER_SLOTS,
    SLOT_LIST,
    SLOTS,
    BoostSegment,
    calculate_finish,
    calculate_remaining,
)
from .repository import (
    clear_active_boosts,
    clear_task,
    check_db,
    init_db,
    read_builder_order,
    read_state,
    record_boost,
    save_builder_order,
    save_task,
)


BASE_DIR = Path(__file__).resolve().parent
DISPLAY_ZONE = ZoneInfo("Asia/Shanghai")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="部落冲突时间计算器", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def local_time(value: datetime) -> str:
    return value.astimezone(DISPLAY_ZONE).strftime("%Y-%m-%d %H:%M:%S")


def short_time(value: datetime) -> str:
    return value.astimezone(DISPLAY_ZONE).strftime("%m-%d %H:%M:%S")


def game_duration(seconds: int) -> str:
    days, rem = divmod(seconds, 86_400)
    hours, rem = divmod(rem, 3_600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} 天")
    if hours:
        parts.append(f"{hours} 小时")
    if minutes:
        parts.append(f"{minutes} 分钟")
    if seconds or not parts:
        parts.append(f"{seconds} 秒")
    return " ".join(parts)


def game_display_duration(seconds: float) -> str:
    if seconds <= 0:
        return "已完成"
    minutes = int(seconds // 60)
    return game_duration(minutes * 60) if minutes else "1 分钟"


templates.env.filters["local_time"] = local_time
templates.env.filters["short_time"] = short_time
templates.env.filters["game_duration"] = game_duration
templates.env.filters["game_display_duration"] = game_display_duration


def dashboard_context(
    now: datetime,
    *,
    slot_errors: dict[str, str] | None = None,
    boost_error: str | None = None,
    message: str | None = None,
) -> dict:
    tasks, segments = read_state(now)
    by_slot: dict[str, list[BoostSegment]] = {slot.key: [] for slot in SLOT_LIST}
    for segment in segments:
        by_slot[segment.slot].append(segment)

    views = []
    for definition in SLOT_LIST:
        task = tasks.get(definition.key)
        slot_segments = by_slot[definition.key]
        active_boost = next(
            (
                item
                for item in slot_segments
                if item.starts_at <= now < item.ends_at
            ),
            None,
        )
        finish_at = (
            calculate_finish(task.anchor_at, task.remaining_seconds, slot_segments)
            if task is not None
            else None
        )
        game_remaining = (
            calculate_remaining(task.anchor_at, task.remaining_seconds, slot_segments, now)
            if task is not None
            else 0
        )
        views.append(
            {
                "definition": definition,
                "task": task,
                "finish_at": finish_at,
                "game_remaining_seconds": game_remaining,
                "game_clock": {
                    "remaining_ms": game_remaining * 1000,
                    "boosts": [
                        {
                            "starts_at": max(now, segment.starts_at).isoformat(),
                            "ends_at": segment.ends_at.isoformat(),
                            "multiplier": BOOSTS[segment.kind].multiplier,
                        }
                        for segment in slot_segments
                        if segment.ends_at > now
                    ],
                },
                "active_boost": active_boost,
                "active_boost_name": BOOSTS[active_boost.kind].label
                if active_boost
                else None,
                "active_boost_multiplier": BOOSTS[active_boost.kind].multiplier
                if active_boost
                else None,
                "completed": finish_at is not None and finish_at <= now,
            }
        )

    upcoming = [
        view["finish_at"]
        for view in views
        if view["finish_at"] is not None and view["finish_at"] > now
    ]
    views_by_slot = {view["definition"].key: view for view in views}
    return {
        "now": now,
        "builder_slots": [
            views_by_slot[slot] for slot in read_builder_order()
        ],
        "research_slots": [view for view in views if view["definition"].group == "research"],
        "boosts": BOOST_LIST,
        "has_active_boost": any(view["active_boost"] for view in views),
        "active_count": len(upcoming),
        "next_finish": min(upcoming, default=None),
        "slot_errors": slot_errors or {},
        "boost_error": boost_error,
        "message": message,
    }


def render_dashboard(
    request: Request,
    *,
    slot_errors: dict[str, str] | None = None,
    boost_error: str | None = None,
    message: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    now = datetime.now(timezone.utc)
    context = dashboard_context(
        now,
        slot_errors=slot_errors,
        boost_error=boost_error,
        message=message,
    )
    template_name = (
        "_dashboard.html"
        if request.headers.get("HX-Request", "").lower() == "true"
        else "index.html"
    )
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=context,
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def after_change(request: Request, message: str | None = None) -> Response:
    if request.headers.get("HX-Request", "").lower() == "true":
        return render_dashboard(request, message=message)
    return RedirectResponse(url="/", status_code=303)


def parse_duration(days: str, hours: str, minutes: str, seconds: str) -> int:
    values = [days.strip(), hours.strip(), minutes.strip(), seconds.strip()]
    if not any(values):
        raise ValueError("请输入游戏中显示的剩余时间。")
    parsed = []
    for value in values:
        if value and not value.isdecimal():
            raise ValueError("时间只能填写非负整数。")
        parsed.append(int(value or "0"))
    day_count, hour_count, minute_count, second_count = parsed
    if day_count > 3650 or hour_count > 23 or minute_count > 59 or second_count > 59:
        raise ValueError("天数不得超过 3650，小时为 0–23，分和秒为 0–59。")
    duration_seconds = day_count * 86_400 + hour_count * 3_600 + minute_count * 60 + second_count
    if duration_seconds == 0:
        raise ValueError("剩余时间必须大于 0。")
    return duration_seconds


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return render_dashboard(request)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    try:
        check_db()
    except sqlite3.Error as error:
        raise HTTPException(status_code=503, detail="database unavailable") from error
    return {"status": "ok"}


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    now = datetime.now(timezone.utc)
    return templates.TemplateResponse(
        request=request,
        name="_dashboard.html",
        context=dashboard_context(now),
        headers={"Cache-Control": "no-store"},
    )


@app.post("/builders/sort", response_class=HTMLResponse)
def sort_builders(request: Request) -> Response:
    now = datetime.now(timezone.utc)
    tasks, segments = read_state(now)
    by_slot: dict[str, list[BoostSegment]] = {slot: [] for slot in BUILDER_SLOTS}
    for segment in segments:
        if segment.slot in by_slot:
            by_slot[segment.slot].append(segment)

    def finish_key(slot: str) -> tuple[bool, datetime, str]:
        task = tasks.get(slot)
        finish_at = (
            calculate_finish(task.anchor_at, task.remaining_seconds, by_slot[slot])
            if task is not None
            else None
        )
        return finish_at is None, finish_at or datetime.max.replace(tzinfo=timezone.utc), slot

    save_builder_order(sorted(BUILDER_SLOTS, key=finish_key))
    return after_change(request)


@app.post("/tasks/{slot}", response_class=HTMLResponse)
def update_task(
    request: Request,
    slot: str,
    name: str = Form(""),
    days: str = Form(""),
    hours: str = Form(""),
    minutes: str = Form(""),
    seconds: str = Form(""),
) -> Response:
    if slot not in SLOTS:
        raise HTTPException(status_code=404, detail="未知位置")
    try:
        remaining_seconds = parse_duration(days, hours, minutes, seconds)
        if len(name.strip()) > 60:
            raise ValueError("名称最多 60 个字符。")
    except ValueError as error:
        return render_dashboard(request, slot_errors={slot: str(error)})

    save_task(slot, name.strip(), remaining_seconds, datetime.now(timezone.utc))
    return after_change(request)


@app.post("/tasks/{slot}/clear", response_class=HTMLResponse)
def remove_task(request: Request, slot: str) -> Response:
    if slot not in SLOTS:
        raise HTTPException(status_code=404, detail="未知位置")
    clear_task(slot)
    return after_change(request, f"已清空{SLOTS[slot].label}。")


@app.post("/boosts", response_class=HTMLResponse)
def add_boost(
    request: Request,
    kind: str = Form(""),
    mode: str = Form("use"),
    remaining_minutes: str = Form("60"),
    remaining_seconds: str = Form("0"),
) -> Response:
    if kind not in BOOSTS:
        return render_dashboard(request, boost_error="请选择一种加速道具。")
    if mode not in ("use", "sync"):
        return render_dashboard(request, boost_error="请选择正确的操作。")
    try:
        if mode == "sync":
            minutes = int(remaining_minutes.strip())
            seconds = int(remaining_seconds.strip())
            if minutes < 0 or seconds < 0 or seconds > 59:
                raise ValueError("invalid remaining boost time")
            duration = minutes * 60 + seconds
        else:
            duration = 3_600
        record_boost(kind, mode, duration, datetime.now(timezone.utc))
    except ValueError:
        return render_dashboard(request, boost_error="同步时请填写 1 秒至 7 天的剩余生效时间。")

    action = "已使用" if mode == "use" else "已同步"
    return after_change(request, f"{action}{BOOSTS[kind].label}，完成时刻已重新计算。")


@app.post("/boosts/clear", response_class=HTMLResponse)
def remove_active_boosts(request: Request) -> Response:
    clear_active_boosts(datetime.now(timezone.utc))
    return after_change(request, "已停止记录当前加速；请按游戏画面更新受影响任务的倒计时。")
