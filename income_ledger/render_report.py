from __future__ import annotations

import html
from pathlib import Path

from income_ledger.analytics import AnalyticsReport
from income_ledger.schemas import EventType, MonthlySummary, Trend
from income_ledger.summary import SummaryResult

CHART_WIDTH = 720
CHART_HEIGHT = 240
CHART_PADDING = 40


def _combined_monthly_totals(monthly_summaries: list[MonthlySummary]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for s in monthly_summaries:
        totals[s.month] = totals.get(s.month, 0.0) + s.net_income
    return totals


def _render_chart_svg(monthly_summaries: list[MonthlySummary]) -> str:
    totals = _combined_monthly_totals(monthly_summaries)
    months = sorted(totals.keys())

    if not months:
        return "<p>No monthly data available to chart.</p>"

    values = [totals[m] for m in months]
    max_value = max(values) if values else 1.0
    max_value = max_value if max_value > 0 else 1.0

    usable_width = CHART_WIDTH - 2 * CHART_PADDING
    usable_height = CHART_HEIGHT - 2 * CHART_PADDING
    n = len(months)
    step = usable_width / max(n - 1, 1)

    points = []
    for i, value in enumerate(values):
        x = CHART_PADDING + i * step
        y = CHART_PADDING + usable_height - (value / max_value) * usable_height
        points.append((x, y))

    polyline_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)

    circles = "\n".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#2563eb" />'
        f'<title>{html.escape(months[i])}: Rs {{values[i]:,.0f}}</title>'
        for i, (x, y) in enumerate(points)
    )

    labels = "\n".join(
        f'<text x="{x:.1f}" y="{CHART_HEIGHT - 10}" font-size="11" '
        f'text-anchor="middle" fill="#555">{html.escape(months[i])}</text>'
        for i, (x, _y) in enumerate(points)
    )

    baseline_y = CHART_PADDING + usable_height

    return f"""
<svg width="{CHART_WIDTH}" height="{CHART_HEIGHT}" viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}"
     xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Monthly income chart">
  <line x1="{CHART_PADDING}" y1="{baseline_y}" x2="{CHART_WIDTH - CHART_PADDING}" y2="{baseline_y}"
        stroke="#ccc" stroke-width="1" />
  <polyline points="{polyline_points}" fill="none" stroke="#2563eb" stroke-width="2" />
  {circles}
  {labels}
</svg>
""".strip()


def _platform_breakdown_html(report: AnalyticsReport) -> str:
    if not report.platform_contribution_pct:
        return "<p>No platform breakdown available.</p>"

    rows = "\n".join(
        f"<tr><td>{html.escape(platform.capitalize())}</td><td>{pct:.1f}%</td></tr>"
        for platform, pct in sorted(report.platform_contribution_pct.items(), key=lambda kv: -kv[1])
    )
    return f"""
<table>
  <thead><tr><th>Platform</th><th>Share of income</th></tr></thead>
  <tbody>
  {rows}
  </tbody>
</table>
""".strip()


def _volatility_html(report: AnalyticsReport) -> str:
    combined = report.volatility_combined
    cv_text = f"{combined.cv:.2f}" if combined.cv is not None else f"n/a ({combined.cv_note})"

    per_platform_rows = "\n".join(
        f"<tr><td>{html.escape(platform.capitalize())}</td>"
        f"<td>Rs {vol.sd_abs:,.0f}</td>"
        f"<td>{f'{vol.cv:.2f}' if vol.cv is not None else 'n/a'}</td></tr>"
        for platform, vol in report.volatility_per_platform.items()
    )

    return f"""
<p><strong>Combined volatility:</strong> Rs {combined.sd_abs:,.0f} (CV: {cv_text})</p>
<table>
  <thead><tr><th>Platform</th><th>Volatility (Rs SD)</th><th>CV</th></tr></thead>
  <tbody>
  {per_platform_rows}
  </tbody>
</table>
""".strip()


def _trend_text(report: AnalyticsReport) -> str:
    trend = report.trend.trend
    if trend == Trend.INSUFFICIENT_DATA:
        return "Insufficient data (fewer than 6 months of history)"
    label = trend.value.replace("_", " ")
    if report.trend.slope_per_month is not None:
        return f"{label} (slope: Rs {report.trend.slope_per_month:,.0f}/month)"
    return label


def render_html_report(
    report: AnalyticsReport,
    summary: SummaryResult,
    monthly_summaries: list[MonthlySummary],
    is_synthetic: bool,
) -> str:
    data_label = "SYNTHETIC TEST DATA" if is_synthetic else "REAL STATEMENT DATA"
    data_label_color = "#b45309" if is_synthetic else "#15803d"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Gig Income Ledger - Results</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; max-width: 800px; margin: 40px auto; color: #1f2937; }}
  h1 {{ font-size: 1.5rem; }}
  h2 {{ font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 8px; }}
  th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #e5e7eb; }}
  .badge {{ display: inline-block; padding: 4px 10px; border-radius: 4px; color: white;
            background: {data_label_color}; font-size: 0.8rem; font-weight: bold; }}
  .summary-box {{ background: #f3f4f6; padding: 16px; border-radius: 8px; margin-top: 8px; }}
  .disclaimer {{ font-size: 0.8rem; color: #6b7280; margin-top: 2rem; }}
</style>
</head>
<body>
  <span class="badge">{html.escape(data_label)}</span>
  <h1>Gig Income Ledger - Results</h1>

  <h2>Average Monthly Income</h2>
  <p>Rs {report.avg_monthly_income:,.0f}</p>

  <h2>Trend</h2>
  <p>{html.escape(_trend_text(report))}</p>

  <h2>Volatility</h2>
  {_volatility_html(report)}

  <h2>Platform Breakdown</h2>
  {_platform_breakdown_html(report)}

  <h2>Monthly Income Chart</h2>
  {_render_chart_svg(monthly_summaries)}

  <h2>Summary</h2>
  <div class="summary-box">
    <p>{html.escape(summary.text)}</p>
  </div>

  <p class="disclaimer">
    This tool reconstructs past income from available records. It is not a
    credit score, not a lending product, and does not provide financial
    advice or eligibility recommendations.
  </p>
</body>
</html>
"""


def write_html_report(
    report: AnalyticsReport,
    summary: SummaryResult,
    monthly_summaries: list[MonthlySummary],
    output_path: str | Path,
    is_synthetic: bool = True,
) -> Path:
    output_path = Path(output_path)
    html_content = render_html_report(report, summary, monthly_summaries, is_synthetic=is_synthetic)
    output_path.write_text(html_content, encoding="utf-8")
    return output_path


def render_results_fragment(
    report: AnalyticsReport,
    summary: SummaryResult,
    monthly_summaries: list[MonthlySummary],
    income_events: list,
) -> list[dict]:
    from income_ledger.schemas import EventType, MatchQuality

    def _confidence(ev) -> float:
        if ev.event_type == EventType.REVERSAL:
            return 0.90
        if ev.event_type == EventType.ADJUSTMENT:
            return 0.80
        return {
            MatchQuality.EXACT:     0.95,
            MatchQuality.AMBIGUOUS: 0.55,
            MatchQuality.UNMATCHED: 0.40,
        }.get(ev.match_quality, 0.50)

    return [
        {
            "event_id":        ev.event_id,
            "date":            ev.date.isoformat(),
            "amount":          round(ev.amount, 2),
            "direction":       ev.direction.value,
            "event_type":      ev.event_type.value,
            "platform":        ev.platform,
            "source_type":     ev.source_type.value,
            "match_quality":   ev.match_quality.value,
            "confidence":      _confidence(ev),
            "raw_description": ev.raw_description,
        }
        for ev in income_events
    ]
