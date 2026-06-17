from datetime import date
from pathlib import Path

import pytest

from income_ledger.parser import (
    RawTransaction,
    ScannedPdfError,
    is_text_based,
    parse_sbi_statement,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
SYNTHETIC_SBI_PDF = FIXTURES / "synthetic_sbi_statement.pdf"
SCANNED_LIKE_PDF = FIXTURES / "synthetic_scanned_like.pdf"


def test_synthetic_statement_is_text_based():
    assert is_text_based(SYNTHETIC_SBI_PDF) is True


def test_scanned_like_pdf_is_not_text_based():
    assert is_text_based(SCANNED_LIKE_PDF) is False


def test_parse_sbi_statement_raises_on_scanned_pdf():
    with pytest.raises(ScannedPdfError):
        parse_sbi_statement(SCANNED_LIKE_PDF)


def test_parse_sbi_statement_returns_transactions():
    transactions = parse_sbi_statement(SYNTHETIC_SBI_PDF)
    assert len(transactions) == 19


def test_parse_sbi_statement_first_row_is_correct():
    transactions = parse_sbi_statement(SYNTHETIC_SBI_PDF)
    first = transactions[0]
    assert first == RawTransaction(
        date=date(2026, 1, 1),
        description="UPI/SWIGGY PVT LTD/PAYOUT/000123",
        credit=1450.00,
        debit=None,
    )


def test_parse_sbi_statement_debit_row_is_correct():
    transactions = parse_sbi_statement(SYNTHETIC_SBI_PDF)
    atm_row = next(t for t in transactions if "ATM WDL CASH" in t.description)
    assert atm_row.debit == 2000.00
    assert atm_row.credit is None


def test_parse_sbi_statement_all_rows_have_date_and_description():
    transactions = parse_sbi_statement(SYNTHETIC_SBI_PDF)
    for txn in transactions:
        assert txn.date is not None
        assert txn.description != ""
        assert txn.debit is not None or txn.credit is not None
