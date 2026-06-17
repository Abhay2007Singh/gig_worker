from datetime import date

import pytest

from income_ledger.schemas import (
    Direction,
    EventType,
    IncomeEvent,
    MatchQuality,
    MonthlySummary,
    SourceType,
    Trend,
    WorkerSummary,
)


def test_income_event_round_trip():
    event = IncomeEvent(
        date=date(2026, 6, 15),
        amount=1250.0,
        direction=Direction.CREDIT,
        event_type=EventType.PAYOUT,
        platform="swiggy",
        source_type=SourceType.BANK_STATEMENT,
        match_quality=MatchQuality.EXACT,
        raw_description="SWIGGY PVT LTD",
    )
    data = event.to_dict()
    restored = IncomeEvent.from_dict(data)
    assert restored == event


def test_income_event_rejects_negative_amount():
    with pytest.raises(ValueError):
        IncomeEvent(
            date=date(2026, 6, 15),
            amount=-100.0,
            direction=Direction.CREDIT,
            event_type=EventType.PAYOUT,
            platform="swiggy",
            source_type=SourceType.BANK_STATEMENT,
            match_quality=MatchQuality.EXACT,
            raw_description="SWIGGY PVT LTD",
        )


def test_monthly_summary_round_trip():
    summary = MonthlySummary(month="2026-06", platform="swiggy", net_income=25000.0)
    data = summary.to_dict()
    restored = MonthlySummary.from_dict(data)
    assert restored == summary


def test_worker_summary_round_trip():
    summary = WorkerSummary(
        avg_monthly_income=28000.0,
        volatility_abs=3200.0,
        volatility_cv=0.18,
        trend=Trend.STABLE_OR_INCONCLUSIVE,
        longest_gap_days=8,
    )
    data = summary.to_dict()
    restored = WorkerSummary.from_dict(data)
    assert restored == summary


def test_worker_summary_insufficient_data_trend():
    summary = WorkerSummary(
        avg_monthly_income=15000.0,
        volatility_abs=0.0,
        volatility_cv=None,
        trend=Trend.INSUFFICIENT_DATA,
    )
    data = summary.to_dict()
    restored = WorkerSummary.from_dict(data)
    assert restored.trend == Trend.INSUFFICIENT_DATA
    assert restored.volatility_cv is None
