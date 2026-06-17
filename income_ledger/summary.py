from __future__ import annotations

import os
import re
from dataclasses import dataclass

from income_ledger.analytics import AnalyticsReport
from income_ledger.schemas import Trend

NUMERIC_TOKEN_RE = re.compile(r"-?\d[\d,]*\.?\d*")
ROUNDING_TOLERANCE = 0.01


@dataclass(frozen=True)
class SummaryResult:
    text: str
    source: str
    rejected_gemini_output: str | None = None


def _trend_phrase(report: AnalyticsReport) -> str:
    trend = report.trend.trend
    if trend == Trend.INSUFFICIENT_DATA:
        return "There is not yet enough monthly history to determine a reliable trend."
    if trend == Trend.GROWING:
        return f"Income has been growing, by roughly Rs {report.trend.slope_per_month:.0f} per month."
    if trend == Trend.DECLINING:
        return f"Income has been declining, by roughly Rs {abs(report.trend.slope_per_month):.0f} per month."
    return "Income has stayed roughly stable, with no statistically clear upward or downward trend."


def _platform_phrase(report: AnalyticsReport) -> str:
    if not report.platform_contribution_pct:
        return "No platform breakdown is available."
    parts = [
        f"{platform.capitalize()} {pct:.0f}%"
        for platform, pct in sorted(report.platform_contribution_pct.items(), key=lambda kv: -kv[1])
    ]
    return "Platform contribution: " + ", ".join(parts) + "."


def _volatility_phrase(report: AnalyticsReport) -> str:
    combined = report.volatility_combined
    if combined.cv is not None:
        return (
            f"Combined month-to-month income volatility is Rs {combined.sd_abs:.0f} "
            f"(coefficient of variation {combined.cv:.2f})."
        )
    return f"Combined month-to-month income volatility is Rs {combined.sd_abs:.0f}."


def _gap_phrase(report: AnalyticsReport) -> str:
    if report.longest_zero_income_gap_days is None:
        return ""
    return f"The longest gap between income-generating days was {report.longest_zero_income_gap_days} days."


def render_template_summary(report: AnalyticsReport) -> str:
    sentences = [
        f"Average monthly income is Rs {report.avg_monthly_income:.0f}.",
        _platform_phrase(report),
        _trend_phrase(report),
        _volatility_phrase(report),
        _gap_phrase(report),
    ]
    return " ".join(s for s in sentences if s)


def _extract_numeric_tokens(text: str) -> set[float]:
    tokens = set()
    for match in NUMERIC_TOKEN_RE.findall(text):
        cleaned = match.replace(",", "")
        if cleaned in ("", "-", "."):
            continue
        try:
            tokens.add(float(cleaned))
        except ValueError:
            continue
    return tokens


def _allowed_numbers(report: AnalyticsReport) -> set[float]:
    allowed: set[float] = {round(report.avg_monthly_income), report.avg_monthly_income}

    for pct in report.platform_contribution_pct.values():
        allowed.add(round(pct))
        allowed.add(pct)

    for vol in list(report.volatility_per_platform.values()) + [report.volatility_combined]:
        allowed.add(round(vol.sd_abs))
        allowed.add(vol.sd_abs)
        if vol.cv is not None:
            allowed.add(round(vol.cv, 2))
            allowed.add(vol.cv)

    if report.trend.slope_per_month is not None:
        allowed.add(round(abs(report.trend.slope_per_month)))
        allowed.add(abs(report.trend.slope_per_month))
        allowed.add(round(report.trend.slope_per_month))
        allowed.add(report.trend.slope_per_month)

    if report.longest_zero_income_gap_days is not None:
        allowed.add(float(report.longest_zero_income_gap_days))

    allowed.update(float(i) for i in range(0, 13))

    return allowed


def validate_numbers_against_report(text: str, report: AnalyticsReport) -> bool:
    allowed = _allowed_numbers(report)
    found = _extract_numeric_tokens(text)

    for number in found:
        if any(abs(number - allowed_value) <= ROUNDING_TOLERANCE for allowed_value in allowed):
            continue
        return False
    return True


_FORBIDDEN_PHRASES = [
    "credit score",
    "loan",
    "eligible for",
    "eligibility",
    "we recommend",
    "you should borrow",
    "interest rate",
    "emi",
]


def _contains_forbidden_advice(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _FORBIDDEN_PHRASES)


def _call_gemini(template_text: str) -> str | None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    from google import genai

    client = genai.Client(api_key=api_key)
    prompt = (
        "Rewrite the following income summary in plain, friendly language for a "
        "gig worker. Keep every number EXACTLY as given -- do not add, remove, "
        "round differently, or recalculate any figure. Do not give financial "
        "advice, loan suggestions, or credit scoring language. Output only the "
        "rewritten summary text.\n\n"
        f"{template_text}"
    )
    response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
    return response.text


def generate_summary(report: AnalyticsReport, use_gemini: bool = True) -> SummaryResult:
    template_text = render_template_summary(report)

    if not use_gemini:
        return SummaryResult(text=template_text, source="template")

    gemini_text = None
    try:
        gemini_text = _call_gemini(template_text)
    except Exception:
        gemini_text = None

    if gemini_text is None:
        return SummaryResult(text=template_text, source="template")

    if _contains_forbidden_advice(gemini_text):
        return SummaryResult(
            text=template_text, source="template", rejected_gemini_output=gemini_text
        )

    if not validate_numbers_against_report(gemini_text, report):
        return SummaryResult(
            text=template_text, source="template", rejected_gemini_output=gemini_text
        )

    return SummaryResult(text=gemini_text, source="gemini")
