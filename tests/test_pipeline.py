from pathlib import Path

from income_ledger.pipeline import run_pipeline

FIXTURES = Path(__file__).parent.parent / "fixtures"
SYNTHETIC_SBI_PDF = FIXTURES / "synthetic_sbi_statement.pdf"


def test_run_pipeline_end_to_end_on_synthetic_fixture(tmp_path):
    db_path = tmp_path / "pipeline_test.db"
    report, summary, monthly_summaries, events = run_pipeline(SYNTHETIC_SBI_PDF, db_path, use_gemini=False)

    assert report.avg_monthly_income > 0
    assert len(monthly_summaries) > 0
    assert summary.source == "template"
    assert "Rs" in summary.text
    assert len(events) > 0


def test_run_pipeline_without_gemini_never_calls_api(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    db_path = tmp_path / "pipeline_test_no_gemini.db"
    report, summary, monthly_summaries, events = run_pipeline(SYNTHETIC_SBI_PDF, db_path, use_gemini=False)
    assert summary.source == "template"
    assert summary.rejected_gemini_output is None
