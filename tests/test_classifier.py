from datetime import date

from income_ledger.classifier import (
    ClassificationResult,
    classify_statement,
    classify_transaction,
    needs_confirmation,
)
from income_ledger.parser import RawTransaction
from income_ledger.schemas import EventType, MatchQuality

# All narrations below are SYNTHETIC test fixtures, not real transactions.


def _txn(description: str, credit: float | None = None, debit: float | None = None) -> RawTransaction:
    return RawTransaction(date=date(2026, 1, 1), description=description, credit=credit, debit=debit)


def test_refund_marker_takes_priority_over_platform_match():
    txn = _txn("UPI/SWIGGY PVT LTD/REFUND/000789", credit=250.0)
    result = classify_transaction(txn, platform_payout_counts={"swiggy": 10})
    assert result == ClassificationResult(
        platform="swiggy", event_type=EventType.REVERSAL, match_quality=MatchQuality.EXACT
    )


def test_debit_side_reversal_keeps_platform_tag():
    txn = _txn("UPI/ZOMATO LTD/RVSL/002099", debit=980.0)
    result = classify_transaction(txn, platform_payout_counts={"zomato": 5})
    assert result.platform == "zomato"
    assert result.event_type == EventType.REVERSAL
    assert result.match_quality == MatchQuality.EXACT


def test_one_off_platform_match_is_ambiguous():
    txn = _txn("UPI/OLA CABS PAYOUT", credit=1100.0)
    result = classify_transaction(txn, platform_payout_counts={"ola": 1})
    assert result.platform == "ola"
    assert result.event_type == EventType.PAYOUT
    assert result.match_quality == MatchQuality.AMBIGUOUS


def test_clean_repeated_platform_match_is_exact():
    txn = _txn("UPI/SWIGGY PVT LTD/PAYOUT/000123", credit=1450.0)
    result = classify_transaction(txn, platform_payout_counts={"swiggy": 4})
    assert result.platform == "swiggy"
    assert result.event_type == EventType.PAYOUT
    assert result.match_quality == MatchQuality.EXACT


def test_no_platform_match_is_unmatched():
    txn = _txn("NEFT CR SALARY XYZ CORP", credit=5000.0)
    result = classify_transaction(txn)
    assert result.platform is None
    assert result.match_quality == MatchQuality.UNMATCHED


def test_debit_with_no_platform_match_is_unmatched_adjustment():
    txn = _txn("ATM WDL CASH", debit=2000.0)
    result = classify_transaction(txn)
    assert result.platform is None
    assert result.event_type == EventType.ADJUSTMENT
    assert result.match_quality == MatchQuality.UNMATCHED


def test_debit_with_platform_match_but_no_refund_marker_is_unmatched():
    # A debit that happens to mention a platform name with no refund
    # marker is NOT proof of anything -- must not be guessed at.
    txn = _txn("UBER EATS SUBSCRIPTION FEE", debit=199.0)
    result = classify_transaction(txn, platform_payout_counts={"uber": 5})
    assert result.platform is None
    assert result.match_quality == MatchQuality.UNMATCHED


def test_needs_confirmation_flags_ambiguous_and_unmatched():
    ambiguous = ClassificationResult(
        platform="ola", event_type=EventType.PAYOUT, match_quality=MatchQuality.AMBIGUOUS
    )
    unmatched = ClassificationResult(
        platform=None, event_type=EventType.PAYOUT, match_quality=MatchQuality.UNMATCHED
    )
    exact = ClassificationResult(
        platform="swiggy", event_type=EventType.PAYOUT, match_quality=MatchQuality.EXACT
    )

    from income_ledger.schemas import IncomeEvent, Direction, SourceType

    def make_event(result: ClassificationResult) -> IncomeEvent:
        return IncomeEvent(
            date=date(2026, 1, 1),
            amount=100.0,
            direction=Direction.CREDIT,
            event_type=result.event_type,
            platform=result.platform or "unknown",
            source_type=SourceType.BANK_STATEMENT,
            match_quality=result.match_quality,
            raw_description="test",
        )

    assert needs_confirmation(make_event(ambiguous)) is True
    assert needs_confirmation(make_event(unmatched)) is True
    assert needs_confirmation(make_event(exact)) is False


def test_classify_statement_on_synthetic_fixture_separates_payouts_from_reversals():
    transactions = [
        _txn("UPI/SWIGGY PVT LTD/PAYOUT/1", credit=1000.0),
        _txn("UPI/SWIGGY PVT LTD/PAYOUT/2", credit=1100.0),
        _txn("UPI/SWIGGY PVT LTD/PAYOUT/3", credit=1200.0),
        _txn("UPI/SWIGGY PVT LTD/REFUND/4", credit=200.0),
        _txn("UPI/ZOMATO LTD/RVSL/5", debit=500.0),
        _txn("ATM WDL CASH", debit=2000.0),
    ]
    events = classify_statement(transactions)

    swiggy_payouts = [e for e in events if e.platform == "swiggy" and e.event_type == EventType.PAYOUT]
    swiggy_reversals = [e for e in events if e.platform == "swiggy" and e.event_type == EventType.REVERSAL]
    zomato_reversals = [e for e in events if e.platform == "zomato" and e.event_type == EventType.REVERSAL]

    assert len(swiggy_payouts) == 3
    assert all(e.match_quality == MatchQuality.EXACT for e in swiggy_payouts)
    assert len(swiggy_reversals) == 1
    assert len(zomato_reversals) == 1
    assert zomato_reversals[0].amount == 500.0

    flagged = [e for e in events if needs_confirmation(e)]
    assert len(flagged) == 1
    assert flagged[0].raw_description == "ATM WDL CASH"


def test_classify_statement_never_silently_classifies_unmatched_as_exact():
    transactions = [_txn("RANDOM MERCHANT XYZ", credit=999.0)]
    events = classify_statement(transactions)
    assert len(events) == 1
    assert events[0].match_quality != MatchQuality.EXACT
    assert needs_confirmation(events[0]) is True
