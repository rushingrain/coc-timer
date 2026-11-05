"""Small SQLite store for the single-user MVP dashboard."""

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .domain import BOOST_DURATION, BOOSTS, BoostSegment, SLOTS


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "coc_timer.sqlite3"
DB_PATH = Path(os.environ.get("COC_TIMER_DB", DEFAULT_DB_PATH))


@dataclass(frozen=True)
class TaskRecord:
    slot: str
    name: str
    remaining_seconds: int
    anchor_at: datetime


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                slot TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                remaining_seconds INTEGER NOT NULL CHECK (remaining_seconds >= 0),
                anchor_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS boost_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slot TEXT NOT NULL,
                kind TEXT NOT NULL,
                starts_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                CHECK (ends_at >= starts_at)
            );
            CREATE INDEX IF NOT EXISTS boost_segments_slot_end
                ON boost_segments (slot, ends_at);
            """
        )
        connection.commit()


def read_state(now: datetime) -> tuple[dict[str, TaskRecord], list[BoostSegment]]:
    with _connection() as connection:
        rows = connection.execute("SELECT * FROM tasks").fetchall()
        tasks = {
            row["slot"]: TaskRecord(
                slot=row["slot"],
                name=row["name"],
                remaining_seconds=row["remaining_seconds"],
                anchor_at=_datetime(row["anchor_at"]),
            )
            for row in rows
            if row["slot"] in SLOTS
        }
        earliest = min((task.anchor_at for task in tasks.values()), default=now)
        segment_rows = connection.execute(
            "SELECT slot, kind, starts_at, ends_at FROM boost_segments "
            "WHERE ends_at > ? ORDER BY starts_at, id",
            (_iso(earliest),),
        ).fetchall()

    segments = [
        BoostSegment(
            slot=row["slot"],
            kind=row["kind"],
            starts_at=_datetime(row["starts_at"]),
            ends_at=_datetime(row["ends_at"]),
        )
        for row in segment_rows
        if row["slot"] in SLOTS and row["kind"] in BOOSTS
    ]
    return tasks, segments


def save_task(slot: str, name: str, remaining_seconds: int, now: datetime) -> None:
    if slot not in SLOTS or remaining_seconds < 0:
        raise ValueError("invalid task")
    with _connection() as connection:
        connection.execute(
            "INSERT INTO tasks (slot, name, remaining_seconds, anchor_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(slot) DO UPDATE SET "
            "name=excluded.name, remaining_seconds=excluded.remaining_seconds, "
            "anchor_at=excluded.anchor_at",
            (slot, name, remaining_seconds, _iso(now)),
        )
        connection.commit()


def clear_task(slot: str) -> None:
    if slot not in SLOTS:
        raise ValueError("invalid slot")
    with _connection() as connection:
        connection.execute("DELETE FROM tasks WHERE slot = ?", (slot,))
        connection.commit()


def record_boost(kind: str, mode: str, remaining_seconds: int, now: datetime) -> None:
    if kind not in BOOSTS or mode not in ("use", "sync"):
        raise ValueError("invalid boost")
    if mode == "sync" and not 1 <= remaining_seconds <= 604_800:
        raise ValueError("remaining boost seconds must be between 1 and 604800")

    now_iso = _iso(now)
    new_end = now + (BOOST_DURATION if mode == "use" else timedelta(seconds=remaining_seconds))
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            for slot in BOOSTS[kind].slots:
                active = connection.execute(
                    "SELECT id, kind, ends_at FROM boost_segments "
                    "WHERE slot = ? AND starts_at <= ? AND ends_at > ? "
                    "ORDER BY starts_at DESC, id DESC LIMIT 1",
                    (slot, now_iso, now_iso),
                ).fetchone()

                if active is not None and mode == "use" and active["kind"] == kind:
                    extended_end = _datetime(active["ends_at"]) + BOOST_DURATION
                    connection.execute(
                        "UPDATE boost_segments SET ends_at = ? WHERE id = ?",
                        (_iso(extended_end), active["id"]),
                    )
                    continue

                if active is not None:
                    # Replacement cancels the old effect; it will not resume.
                    connection.execute(
                        "UPDATE boost_segments SET ends_at = ? WHERE id = ?",
                        (now_iso, active["id"]),
                    )
                connection.execute(
                    "INSERT INTO boost_segments (slot, kind, starts_at, ends_at) "
                    "VALUES (?, ?, ?, ?)",
                    (slot, kind, now_iso, _iso(new_end)),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def clear_active_boosts(now: datetime) -> None:
    now_iso = _iso(now)
    with _connection() as connection:
        connection.execute(
            "UPDATE boost_segments SET ends_at = ? "
            "WHERE starts_at <= ? AND ends_at > ?",
            (now_iso, now_iso, now_iso),
        )
        connection.commit()
