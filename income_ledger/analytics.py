from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from income_ledger.schemas import EventType, IncomeEvent, MonthlySummary, Trend

CV_FLOOR_RUPEES = 2000.0
MIN_MONTHS_FOR_TREND = 6


@dataclass(frozen=True)
class VolatilityResult:
    sd_abs: float
    cv: float | None
    cv_note: str | None = None


@dataclass(frozen=True)
class TrendResult:
    trend: Trend
    slope_per_month: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    note: str | None = None


@dataclass(frozen=True)
class AnalyticsReport:
    avg_monthly_income: float
    platform_contribution_pct: dict[str, float]
    volatility_per_platform: dict[str, VolatilityResult]
    volatility_combined: VolatilityResult
    trend: TrendResult
    longest_zero_income_gap_days: int | None


def _combined_monthly_totals(monthly_summaries: list[MonthlySummary]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for s in monthly_summaries:
        totals[s.month] = totals.get(s.month, 0.0) + s.net_income
    return totals


def average_monthly_income(monthly_summaries: list[MonthlySummary]) -> float:
    totals = _combined_monthly_totals(monthly_summaries)
    if not totals:
        return 0.0
    return sum(totals.values()) / len(totals)


def platform_contribution(monthly_summaries: list[MonthlySummary]) -> dict[str, float]:
    by_platform: dict[str, float] = {}
    for s in monthly_summaries:
        by_platform[s.platform] = by_platform.get(s.platform, 0.0) + s.net_income

    total = sum(by_platform.values())
    if total <= 0:
        return {platform: 0.0 for platform in by_platform}

    return {platform: round(100.0 * amount / total, 2) for platform, amount in by_platform.items()}


def _std_dev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def compute_volatility(values: list[float]) -> VolatilityResult:
    if not values:
        return VolatilityResult(sd_abs=0.0, cv=None, cv_note="no data")

    mean = sum(values) / len(values)
    sd_abs = _std_dev(values)

    if mean < CV_FLOOR_RUPEES:
        return VolatilityResult(
            sd_abs=sd_abs,
            cv=None,
            cv_note=f"mean monthly income below Rs {CV_FLOOR_RUPEES:.0f} floor; CV omitted as unstable",
        )

    cv = sd_abs / mean
    return VolatilityResult(sd_abs=sd_abs, cv=round(cv, 4))


def volatility_per_platform(monthly_summaries: list[MonthlySummary]) -> dict[str, VolatilityResult]:
    by_platform: dict[str, list[float]] = {}
    for s in monthly_summaries:
        by_platform.setdefault(s.platform, []).append(s.net_income)

    return {platform: compute_volatility(values) for platform, values in by_platform.items()}


def volatility_combined(monthly_summaries: list[MonthlySummary]) -> VolatilityResult:
    totals = _combined_monthly_totals(monthly_summaries)
    return compute_volatility(list(totals.values()))


def _ols_slope_with_ci(y_values: list[float]) -> tuple[float, float, float]:
    n = len(y_values)
    x_values = list(range(n))
    x_mean = sum(x_values) / n
    y_mean = sum(y_values) / n

    sxx = sum((x - x_mean) ** 2 for x in x_values)
    sxy = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))

    slope = sxy / sxx if sxx != 0 else 0.0
    intercept = y_mean - slope * x_mean

    residuals = [y - (intercept + slope * x) for x, y in zip(x_values, y_values)]
    if n > 2:
        residual_variance = sum(r**2 for r in residuals) / (n - 2)
    else:
        residual_variance = 0.0

    se_slope = math.sqrt(residual_variance / sxx) if sxx != 0 else 0.0

    z = 1.96
    margin = z * se_slope
    return slope, slope - margin, slope + margin


def detect_trend(monthly_summaries: list[MonthlySummary]) -> TrendResult:
    totals = _combined_monthly_totals(monthly_summaries)
    months_sorted = sorted(totals.keys())

    if len(months_sorted) < MIN_MONTHS_FOR_TREND:
        return TrendResult(
            trend=Trend.INSUFFICIENT_DATA,
            note=f"only {len(months_sorted)} month(s) of data; need >= {MIN_MONTHS_FOR_TREND}",
        )

    y_values = [totals[m] for m in months_sorted]
    slope, ci_low, ci_high = _ols_slope_with_ci(y_values)

    if ci_low > 0:
        label = Trend.GROWING
    elif ci_high < 0:
        label = Trend.DECLINING
    else:
        label = Trend.STABLE_OR_INCONCLUSIVE

    return TrendResult(trend=label, slope_per_month=round(slope, 2), ci_low=round(ci_low, 2), ci_high=round(ci_high, 2))


def longest_zero_income_gap_days(events: list[IncomeEvent]) -> int | None:
    payout_dates = sorted({e.date for e in events if e.event_type == EventType.PAYOUT})

    if len(payout_dates) < 2:
        return None

    longest_gap = 0
    for earlier, later in zip(payout_dates, payout_dates[1:]):
        gap = (later - earlier).days
        longest_gap = max(longest_gap, gap)

    return longest_gap


def generate_analytics_report(
    events: list[IncomeEvent], monthly_summaries: list[MonthlySummary]
) -> AnalyticsReport:
    return AnalyticsReport(
        avg_monthly_income=round(average_monthly_income(monthly_summaries), 2),
        platform_contribution_pct=platform_contribution(monthly_summaries),
        volatility_per_platform=volatility_per_platform(monthly_summaries),
        volatility_combined=volatility_combined(monthly_summaries),
        trend=detect_trend(monthly_summaries),
        longest_zero_income_gap_days=longest_zero_income_gap_days(events),
    )
