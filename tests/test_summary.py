from unittest.mock import patch

from income_ledger.analytics import AnalyticsReport, TrendResult, VolatilityResult
from income_ledger.schemas import Trend
from income_ledger.summary import (
    generate_summary,
    render_template_summary,
    validate_numbers_against_report,
)


def _report(
    avg_monthly_income=28000.0,
    platform_contribution_pct=None,
    trend=None,
    longest_gap=8,
) -> AnalyticsReport:
    if platform_contribution_pct is None:
        platform_contribution_pct = {"swiggy": 70.0, "uber": 30.0}
    if trend is None:
        trend = TrendResult(trend=Trend.GROWING, slope_per_month=500.0, ci_low=100.0, ci_high=900.0)

    combined_vol = VolatilityResult(sd_abs=3200.0, cv=0.18)
    return AnalyticsReport(
        avg_monthly_income=avg_monthly_income,
        platform_contribution_pct=platform_contribution_pct,
        volatility_per_platform={"swiggy": combined_vol},
        volatility_combined=combined_vol,
        trend=trend,
        longest_zero_income_gap_days=longest_gap,
    )


def test_template_summary_contains_avg_income():
    report = _report()
    text = render_template_summary(report)
    assert "28000" in text


def test_template_summary_no_financial_advice_language():
    report = _report()
    text = render_template_summary(report).lower()
    for forbidden in ["loan", "credit score", "eligible", "interest rate", "emi"]:
        assert forbidden not in text


def test_validate_numbers_accepts_template_output():
    report = _report()
    text = render_template_summary(report)
    assert validate_numbers_against_report(text, report) is True


def test_validate_numbers_rejects_fabricated_number():
    report = _report()
    bad_text = "Average monthly income is Rs 99999. Swiggy contributed 70%."
    assert validate_numbers_against_report(bad_text, report) is False


def test_validate_numbers_accepts_rounded_percentages():
    report = _report()
    text = "Swiggy contributed 70% and Uber 30% of income."
    assert validate_numbers_against_report(text, report) is True


def test_generate_summary_falls_back_to_template_without_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    report = _report()
    result = generate_summary(report)
    assert result.source == "template"
    assert "28000" in result.text


def test_generate_summary_uses_gemini_when_numbers_are_valid(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    report = _report()

    with patch("income_ledger.summary._call_gemini") as mock_call:
        mock_call.return_value = (
            "Your average monthly income is Rs 28000. Swiggy contributed 70% "
            "and Uber 30% of your earnings. Income has been growing steadily."
        )
        result = generate_summary(report)

    assert result.source == "gemini"
    assert result.rejected_gemini_output is None


def test_generate_summary_rejects_gemini_output_with_wrong_number(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    report = _report()

    with patch("income_ledger.summary._call_gemini") as mock_call:
        # Deliberately wrong number: real avg is 28000, this says 50000.
        mock_call.return_value = (
            "Your average monthly income is Rs 50000, which is excellent."
        )
        result = generate_summary(report)

    assert result.source == "template"
    assert result.rejected_gemini_output is not None
    assert "50000" in result.rejected_gemini_output
    assert "28000" in result.text  # the user-facing text is the safe template fallback


def test_generate_summary_rejects_gemini_output_with_financial_advice(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    report = _report()

    with patch("income_ledger.summary._call_gemini") as mock_call:
        mock_call.return_value = (
            "Your average monthly income is Rs 28000. You are eligible for a loan."
        )
        result = generate_summary(report)

    assert result.source == "template"
    assert result.rejected_gemini_output is not None


def test_generate_summary_falls_back_when_gemini_call_raises(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    report = _report()

    with patch("income_ledger.summary._call_gemini", side_effect=RuntimeError("network error")):
        result = generate_summary(report)

    assert result.source == "template"


def test_insufficient_data_trend_produces_no_trend_claim():
    report = _report(trend=TrendResult(trend=Trend.INSUFFICIENT_DATA))
    text = render_template_summary(report)
    assert "not yet enough" in text.lower()
    assert validate_numbers_against_report(text, report) is True
