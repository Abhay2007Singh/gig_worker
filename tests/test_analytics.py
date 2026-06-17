from datetime import date

from income_ledger.analytics import (
    average_monthly_income,
    compute_volatility,
    detect_trend,
    generate_analytics_report,
    longest_zero_income_gap_days,
    platform_contribution,
    volatility_combined,
    volatility_per_platform,
)
from income_ledger.schemas import (
    Direction,
    EventType,
    IncomeEvent,
    MatchQuality,
    MonthlySummary,
    SourceType,
    Trend,
)


def _ms(month: str, platform: str, net_income: float) -> MonthlySummary:
    return MonthlySummary(month=month, platform=platform, net_income=net_income)


def _event(d: date, amount: float, platform: str, event_type: EventType = EventType.PAYOUT) -> IncomeEvent:
    return IncomeEvent(
        date=d,
        amount=amount,
        direction=Direction.CREDIT,
        event_type=event_type,
        platform=platform,
        source_type=SourceType.BANK_STATEMENT,
        match_quality=MatchQuality.EXACT,
        raw_description="test",
    )


# --- average_monthly_income ---


def test_average_monthly_income_combines_platforms_per_month():
    summaries = [
        _ms("2026-01", "swiggy", 1000.0),
        _ms("2026-01", "uber", 500.0),
        _ms("2026-02", "swiggy", 1500.0),
    ]
    # Jan total = 1500, Feb total = 1500 -> avg = 1500
    assert average_monthly_income(summaries) == 1500.0


def test_average_monthly_income_empty_returns_zero():
    assert average_monthly_income([]) == 0.0


# --- platform_contribution ---


def test_platform_contribution_percentages():
    summaries = [
        _ms("2026-01", "swiggy", 600.0),
        _ms("2026-01", "uber", 400.0),
    ]
    pct = platform_contribution(summaries)
    assert pct == {"swiggy": 60.0, "uber": 40.0}


def test_platform_contribution_zero_total_returns_zeros():
    summaries = [_ms("2026-01", "swiggy", 0.0)]
    pct = platform_contribution(summaries)
    assert pct == {"swiggy": 0.0}


# --- CV floor edge cases (explicitly required) ---


def test_cv_omitted_below_floor():
    # mean = 1000, well below Rs 2000 floor
    result = compute_volatility([900.0, 1100.0, 1000.0])
    assert result.cv is None
    assert result.cv_note is not None
    assert result.sd_abs > 0


def test_cv_present_at_or_above_floor():
    # mean = 3000, above floor
    result = compute_volatility([2500.0, 3500.0, 3000.0])
    assert result.cv is not None
    assert result.cv_note is None


def test_cv_floor_boundary_exactly_at_floor():
    # mean exactly 2000 -- spec says floor is ">= Rs 2000", so this should compute CV
    result = compute_volatility([2000.0, 2000.0, 2000.0])
    assert result.cv is not None


def test_volatility_no_data_returns_zero_and_none():
    result = compute_volatility([])
    assert result.sd_abs == 0.0
    assert result.cv is None


# --- volatility per-platform AND combined (explicitly required) ---


def test_volatility_per_platform_and_combined_can_diverge():
    # Swiggy drops while Uber compensates -- combined should look calmer
    # than either platform alone.
    summaries = [
        _ms("2026-01", "swiggy", 3000.0),
        _ms("2026-01", "uber", 1000.0),
        _ms("2026-02", "swiggy", 1000.0),
        _ms("2026-02", "uber", 3000.0),
    ]
    per_platform = volatility_per_platform(summaries)
    combined = volatility_combined(summaries)

    assert per_platform["swiggy"].sd_abs > 0
    assert per_platform["uber"].sd_abs > 0
    # combined totals are 4000 and 4000 each month -> zero volatility
    assert combined.sd_abs == 0.0


# --- trend gating (explicitly required) ---


def test_trend_insufficient_data_below_six_months():
    summaries = [_ms(f"2026-0{i}", "swiggy", 1000.0 * i) for i in range(1, 5)]  # 4 months
    result = detect_trend(summaries)
    assert result.trend == Trend.INSUFFICIENT_DATA
    assert result.slope_per_month is None


def test_trend_growing_with_six_months_clear_upward_slope():
    summaries = [_ms(f"2026-{i:02d}", "swiggy", 1000.0 * i) for i in range(1, 7)]  # 6 months, strong growth
    result = detect_trend(summaries)
    assert result.trend == Trend.GROWING
    assert result.ci_low > 0


def test_trend_declining_with_six_months_clear_downward_slope():
    summaries = [_ms(f"2026-{i:02d}", "swiggy", 7000.0 - 1000.0 * i) for i in range(1, 7)]
    result = detect_trend(summaries)
    assert result.trend == Trend.DECLINING
    assert result.ci_high < 0


def test_trend_stable_or_inconclusive_with_six_months_flat_noise():
    values = [3000.0, 3050.0, 2950.0, 3010.0, 2990.0, 3005.0]
    summaries = [_ms(f"2026-{i:02d}", "swiggy", v) for i, v in enumerate(values, start=1)]
    result = detect_trend(summaries)
    assert result.trend == Trend.STABLE_OR_INCONCLUSIVE


def test_trend_never_fabricated_from_five_points():
    # Even a sharp-looking trend with only 5 points must be insufficient_data.
    summaries = [_ms(f"2026-{i:02d}", "swiggy", 1000.0 * i) for i in range(1, 6)]
    result = detect_trend(summaries)
    assert result.trend == Trend.INSUFFICIENT_DATA


# --- longest zero-income gap ---


def test_longest_gap_days():
    events = [
        _event(date(2026, 1, 1), 1000.0, "swiggy"),
        _event(date(2026, 1, 9), 1000.0, "swiggy"),  # 8 day gap
        _event(date(2026, 1, 12), 1000.0, "swiggy"),  # 3 day gap
    ]
    assert longest_zero_income_gap_days(events) == 8


def test_longest_gap_ignores_reversals_and_adjustments():
    events = [
        _event(date(2026, 1, 1), 1000.0, "swiggy", EventType.PAYOUT),
        _event(date(2026, 1, 2), 100.0, "swiggy", EventType.REVERSAL),
        _event(date(2026, 1, 20), 1000.0, "swiggy", EventType.PAYOUT),
    ]
    # gap should be measured between the two PAYOUTs (19 days), ignoring the reversal date
    assert longest_zero_income_gap_days(events) == 19


def test_longest_gap_none_with_fewer_than_two_payouts():
    events = [_event(date(2026, 1, 1), 1000.0, "swiggy")]
    assert longest_zero_income_gap_days(events) is None


# --- full report ---


def test_generate_analytics_report_end_to_end():
    events = [_event(date(2026, 1, i), 1000.0, "swiggy") for i in (1, 10, 20)]
    summaries = [_ms("2026-01", "swiggy", 3000.0)]
    report = generate_analytics_report(events, summaries)

    assert report.avg_monthly_income == 3000.0
    assert report.platform_contribution_pct == {"swiggy": 100.0}
    assert report.trend.trend == Trend.INSUFFICIENT_DATA
    assert report.longest_zero_income_gap_days == 10
