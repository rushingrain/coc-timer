"""Pure rules for game-clock work and timed boosts."""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Slot:
    key: str
    label: str
    group: str


@dataclass(frozen=True)
class Boost:
    key: str
    label: str
    multiplier: int
    slots: tuple[str, ...]


@dataclass(frozen=True)
class BoostSegment:
    slot: str
    kind: str
    starts_at: datetime
    ends_at: datetime


SLOT_LIST = tuple(
    Slot(f"builder_{number}", f"建筑工人 {number}", "builder")
    for number in range(1, 7)
) + (
    Slot("skill", "技能研究", "research"),
    Slot("pet", "战宠研究", "research"),
)
SLOTS = {slot.key: slot for slot in SLOT_LIST}
BUILDER_SLOTS = tuple(slot.key for slot in SLOT_LIST if slot.group == "builder")
RESEARCH_SLOTS = ("skill", "pet")

BOOST_LIST = (
    Boost("builder_feast", "建筑工人大餐", 2, BUILDER_SLOTS),
    Boost("super_builder_feast", "超级建筑工人大餐", 24, BUILDER_SLOTS),
    Boost("builder_potion", "建筑工人药水", 10, BUILDER_SLOTS),
    Boost("super_builder_potion", "超级建筑工人药水", 24, BUILDER_SLOTS),
    Boost("research_soup", "研究浓汤", 4, RESEARCH_SLOTS),
    Boost("super_research_soup", "超级研究浓汤", 24, RESEARCH_SLOTS),
    Boost("research_potion", "研究药水", 24, ("skill",)),
    Boost("pet_potion", "战宠药水", 24, ("pet",)),
)
BOOSTS = {boost.key: boost for boost in BOOST_LIST}
BOOST_DURATION = timedelta(hours=1)


def _microseconds(duration: timedelta) -> int:
    return (
        (duration.days * 86_400 + duration.seconds) * 1_000_000
        + duration.microseconds
    )


def _advance(cursor: datetime, work_microseconds: int, multiplier: int) -> datetime:
    # Round up to the next microsecond; a completion time must not be early.
    wall_microseconds = (work_microseconds + multiplier - 1) // multiplier
    return cursor + timedelta(microseconds=wall_microseconds)


def calculate_finish(
    anchor_at: datetime,
    remaining_seconds: int,
    segments: list[BoostSegment],
) -> datetime:
    """Consume the game's displayed remaining time along non-overlapping boosts.

    Segments must belong to one slot. A segment active at anchor_at is clipped
    to the anchor; work completed before the user entered the timer is ignored.
    """
    if anchor_at.tzinfo is None:
        raise ValueError("anchor_at must have a timezone")
    if remaining_seconds < 0:
        raise ValueError("remaining_seconds must not be negative")

    work_left = remaining_seconds * 1_000_000
    cursor = anchor_at
    previous_end: datetime | None = None
    for segment in sorted(segments, key=lambda item: item.starts_at):
        if segment.starts_at.tzinfo is None or segment.ends_at.tzinfo is None:
            raise ValueError("boost times must have timezones")
        if segment.ends_at <= anchor_at:
            continue
        if previous_end is not None and segment.starts_at < previous_end:
            raise ValueError("boost segments must not overlap for one slot")
        previous_end = segment.ends_at
        if segment.ends_at <= cursor:
            continue

        boost_start = max(segment.starts_at, cursor)
        if boost_start > cursor:
            normal_capacity = _microseconds(boost_start - cursor)
            if work_left <= normal_capacity:
                return _advance(cursor, work_left, 1)
            work_left -= normal_capacity
            cursor = boost_start

        multiplier = BOOSTS[segment.kind].multiplier
        capacity = _microseconds(segment.ends_at - cursor) * multiplier
        if work_left <= capacity:
            return _advance(cursor, work_left, multiplier)
        work_left -= capacity
        cursor = segment.ends_at

    return _advance(cursor, work_left, 1)
