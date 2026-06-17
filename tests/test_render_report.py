from pathlib import Path

from income_ledger.analytics import AnalyticsReport, TrendResult, VolatilityResult
from income_ledger.render_report import render_html_report, write_html_report
from income_ledger.schemas import MonthlySummary, Trend
from income_ledger.summary import SummaryResult


def _report() -> AnalyticsReport:
    combined_vol = VolatilityResult(sd_abs=590.0, cv=0.07)
    return AnalyticsReport(
        avg_monthly_income=8540.0,
        platform_contribution_pct={"swiggy": 47.2, "uber": 26.3},
        volatility_per_platform={"swiggy": combined_vol, "uber": combined_vol},
        volatility_combined=combined_vol,
        trend=TrendResult(trend=Trend.INSUFFICIENT_DATA),
        longest_zero_income_gap_days=7,
    )


def _monthly_summaries() -> list[MonthlySummary]:
    return [
        MonthlySummary(month="2026-01", platform="swiggy", net_income=5000.0),
        MonthlySummary(month="2026-01", platform="uber", net_income=4130.0),
        MonthlySummary(month="2026-02", platform="swiggy", net_income=4500.0),
        MonthlySummary(month="2026-02", platform="uber", net_income=3450.0),
    ]


def test_render_html_report_contains_no_framework_script_tags():
    report = _report()
    summary = SummaryResult(text="Test summary text.", source="template")
    output = render_html_report(report, summary, _monthly_summaries(), is_synthetic=True)
    assert "<script" not in output.lower()
    assert "react" not in output.lower()
    assert "cdn" not in output.lower()


def test_render_html_report_is_single_self_contained_document():
    report = _report()
    summary = SummaryResult(text="Test summary text.", source="template")
    output = render_html_report(report, summary, _monthly_summaries(), is_synthetic=True)
    assert output.strip().startswith("<!DOCTYPE html>")
    assert "</html>" in output


def test_render_html_report_shows_synthetic_badge_when_synthetic():
    report = _report()
    summary = SummaryResult(text="Test summary text.", source="template")
    output = render_html_report(report, summary, _monthly_summaries(), is_synthetic=True)
    assert "SYNTHETIC TEST DATA" in output


def test_render_html_report_shows_real_badge_when_not_synthetic():
    report = _report()
    summary = SummaryResult(text="Test summary text.", source="template")
    output = render_html_report(report, summary, _monthly_summaries(), is_synthetic=False)
    assert "REAL STATEMENT DATA" in output
    assert "SYNTHETIC TEST DATA" not in output


def test_render_html_report_contains_avg_income_and_summary_text():
    report = _report()
    summary = SummaryResult(text="Average monthly income is Rs 8540.", source="template")
    output = render_html_report(report, summary, _monthly_summaries(), is_synthetic=True)
    assert "8,540" in output
    assert "Average monthly income is Rs 8540." in output


def test_render_html_report_contains_insufficient_data_trend_text():
    report = _report()
    summary = SummaryResult(text="x", source="template")
    output = render_html_report(report, summary, _monthly_summaries(), is_synthetic=True)
    assert "Insufficient data" in output


def test_render_html_report_contains_svg_chart_with_month_labels():
    report = _report()
    summary = SummaryResult(text="x", source="template")
    output = render_html_report(report, summary, _monthly_summaries(), is_synthetic=True)
    assert "<svg" in output
    assert "2026-01" in output
    assert "2026-02" in output


def test_render_html_report_contains_platform_breakdown_table():
    report = _report()
    summary = SummaryResult(text="x", source="template")
    output = render_html_report(report, summary, _monthly_summaries(), is_synthetic=True)
    assert "Swiggy" in output
    assert "47.2%" in output


def test_render_html_report_escapes_summary_text_html():
    report = _report()
    summary = SummaryResult(text="<script>alert(1)</script>", source="template")
    output = render_html_report(report, summary, _monthly_summaries(), is_synthetic=True)
    assert "<script>alert(1)</script>" not in output
    assert "&lt;script&gt;" in output


def test_render_html_report_disclaimer_present():
    report = _report()
    summary = SummaryResult(text="x", source="template")
    output = render_html_report(report, summary, _monthly_summaries(), is_synthetic=True)
    normalized = " ".join(output.lower().split())
    assert "not a credit score" in normalized
    assert "not a lending product" in normalized


def test_write_html_report_writes_file(tmp_path):
    report = _report()
    summary = SummaryResult(text="x", source="template")
    output_path = tmp_path / "results.html"
    result_path = write_html_report(report, summary, _monthly_summaries(), output_path, is_synthetic=True)
    assert result_path == output_path
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content


def test_render_html_report_handles_empty_monthly_summaries():
    report = _report()
    summary = SummaryResult(text="x", source="template")
    output = render_html_report(report, summary, [], is_synthetic=True)
    assert "No monthly data available to chart." in output
