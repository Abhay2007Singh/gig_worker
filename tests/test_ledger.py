from datetime import date

import pytest

from income_ledger.ledger import Ledger
from income_ledger.schemas import (
    Direction,
    EventType,
    IncomeEvent,
    MatchQuality,
    SourceType,
)


@pytest.fixture
def ledger(tmp_path):
    db_path = tmp_path / "test_ledger.db"
    with Ledger(db_path) as l:
        yield l


def _event(
    day: int,
    month: int,
    amount: float,
    platform: str,
    event_type: EventType,
    direction: Direction = Direction.CREDIT,
    match_quality: MatchQuality = MatchQuality.EXACT,
    description: str = "test",
) -> IncomeEvent:
    return IncomeEvent(
        date=date(2026, month, day),
        amount=amount,
        direction=direction,
        event_type=event_type,
        platform=platform,
        source_type=SourceType.BANK_STATEMENT,
        match_quality=match_quality,
        raw_description=description,
    )


def test_ledger_creates_single_worker_row(ledger):
    rows = ledger._conn.execute("SELECT id, label FROM workers").fetchall()
    assert rows == [(1, "default_worker")]


def test_add_and_get_events_round_trip(ledger):
    events = [
        _event(1, 1, 1000.0, "swiggy", EventType.PAYOUT),
        _event(5, 1, 1200.0, "uber", EventType.PAYOUT),
    ]
    ledger.add_events(events)
    retrieved = ledger.get_events()
    assert len(retrieved) == 2
    assert {e.platform for e in retrieved} == {"swiggy", "uber"}


def test_net_income_is_not_naive_sum_of_credits(ledger):
    # 3 swiggy payouts of 1000 each = 3000 gross, but one is reversed.
    events = [
        _event(1, 1, 1000.0, "swiggy", EventType.PAYOUT),
        _event(8, 1, 1000.0, "swiggy", EventType.PAYOUT),
        _event(15, 1, 1000.0, "swiggy", EventType.PAYOUT),
        _event(20, 1, 1000.0, "swiggy", EventType.REVERSAL, direction=Direction.CREDIT),
    ]
    ledger.add_events(events)
    summaries = ledger.recompute_monthly_summaries()

    swiggy_jan = next(s for s in summaries if s.platform == "swiggy" and s.month == "2026-01")
    assert swiggy_jan.net_income == 2000.0  # 3000 gross - 1000 reversal, NOT 3000


def test_debit_side_reversal_reduces_net_income(ledger):
    events = [
        _event(1, 2, 1500.0, "zomato", EventType.PAYOUT),
        _event(8, 2, 1500.0, "zomato", EventType.PAYOUT),
        _event(
            15,
            2,
            500.0,
            "zomato",
            EventType.REVERSAL,
            direction=Direction.DEBIT,
            description="UPI/ZOMATO LTD/RVSL",
        ),
    ]
    ledger.add_events(events)
    summaries = ledger.recompute_monthly_summaries()

    zomato_feb = next(s for s in summaries if s.platform == "zomato" and s.month == "2026-02")
    assert zomato_feb.net_income == 2500.0  # 3000 - 500 clawback


def test_unknown_platform_excluded_from_monthly_summaries(ledger):
    events = [
        _event(1, 1, 1000.0, "swiggy", EventType.PAYOUT),
        _event(3, 1, 5000.0, "unknown", EventType.PAYOUT, match_quality=MatchQuality.UNMATCHED),
        _event(
            5,
            1,
            2000.0,
            "unknown",
            EventType.ADJUSTMENT,
            direction=Direction.DEBIT,
            match_quality=MatchQuality.UNMATCHED,
        ),
    ]
    ledger.add_events(events)
    summaries = ledger.recompute_monthly_summaries()

    platforms_in_summary = {s.platform for s in summaries}
    assert "unknown" not in platforms_in_summary
    assert summaries == [
        s for s in summaries if s.platform == "swiggy"
    ]


def test_monthly_summaries_split_by_platform_and_month(ledger):
    events = [
        _event(1, 1, 1000.0, "swiggy", EventType.PAYOUT),
        _event(1, 1, 800.0, "uber", EventType.PAYOUT),
        _event(1, 2, 1200.0, "swiggy", EventType.PAYOUT),
    ]
    ledger.add_events(events)
    summaries = ledger.recompute_monthly_summaries()

    by_key = {(s.month, s.platform): s.net_income for s in summaries}
    assert by_key[("2026-01", "swiggy")] == 1000.0
    assert by_key[("2026-01", "uber")] == 800.0
    assert by_key[("2026-02", "swiggy")] == 1200.0


def test_recompute_persists_and_get_monthly_summaries_returns_same_data(ledger):
    events = [_event(1, 1, 1000.0, "swiggy", EventType.PAYOUT)]
    ledger.add_events(events)
    computed = ledger.recompute_monthly_summaries()
    fetched = ledger.get_monthly_summaries()
    assert computed == fetched
