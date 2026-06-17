from __future__ import annotations

from pathlib import Path

from income_ledger.analytics import AnalyticsReport, generate_analytics_report
from income_ledger.classifier import classify_statement
from income_ledger.ledger import Ledger
from income_ledger.parser import parse_sbi_statement
from income_ledger.schemas import IncomeEvent, MonthlySummary
from income_ledger.summary import SummaryResult, generate_summary


def run_pipeline(
    pdf_path: str | Path, db_path: str | Path, use_gemini: bool = True
) -> tuple[AnalyticsReport, SummaryResult, list[MonthlySummary], list[IncomeEvent]]:
    transactions = parse_sbi_statement(pdf_path)
    events = classify_statement(transactions)

    with Ledger(db_path) as ledger:
        ledger.add_events(events)
        monthly_summaries = ledger.recompute_monthly_summaries()
        all_events = ledger.get_events()

    report = generate_analytics_report(all_events, monthly_summaries)
    summary = generate_summary(report, use_gemini=use_gemini)

    return report, summary, monthly_summaries, all_events
