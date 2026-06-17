from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from income_ledger.parser import RawTransaction
from income_ledger.schemas import (
    Direction,
    EventType,
    IncomeEvent,
    MatchQuality,
    SourceType,
)

PLATFORM_PATTERNS: dict[str, list[str]] = {
    "swiggy": ["SWIGGY", "SWGY"],
    "zomato": ["ZOMATO", "ZMT"],
    "uber": ["UBER"],
    "ola": ["OLA"],
}

REFUND_MARKERS = ["REFUND", "REVERSAL", "RFND", "RVSL"]


@dataclass(frozen=True)
class ClassificationResult:
    platform: str | None
    event_type: EventType
    match_quality: MatchQuality


def _match_platform(description: str) -> str | None:
    upper_desc = description.upper()
    for platform, patterns in PLATFORM_PATTERNS.items():
        if any(pattern in upper_desc for pattern in patterns):
            return platform
    return None


def _has_refund_marker(description: str) -> bool:
    upper_desc = description.upper()
    return any(marker in upper_desc for marker in REFUND_MARKERS)


def classify_transaction(
    transaction: RawTransaction,
    platform_payout_counts: dict[str, int] | None = None,
) -> ClassificationResult:
    platform = _match_platform(transaction.description)
    has_refund_marker = _has_refund_marker(transaction.description)

    if transaction.credit is None:
        if platform is not None and has_refund_marker:
            return ClassificationResult(
                platform=platform, event_type=EventType.REVERSAL, match_quality=MatchQuality.EXACT
            )
        return ClassificationResult(
            platform=None, event_type=EventType.ADJUSTMENT, match_quality=MatchQuality.UNMATCHED
        )

    if platform is None:
        return ClassificationResult(
            platform=None, event_type=EventType.PAYOUT, match_quality=MatchQuality.UNMATCHED
        )

    if has_refund_marker:
        return ClassificationResult(
            platform=platform, event_type=EventType.REVERSAL, match_quality=MatchQuality.EXACT
        )

    counts = platform_payout_counts or {}
    if counts.get(platform, 0) <= 1:
        return ClassificationResult(
            platform=platform, event_type=EventType.PAYOUT, match_quality=MatchQuality.AMBIGUOUS
        )

    return ClassificationResult(
        platform=platform, event_type=EventType.PAYOUT, match_quality=MatchQuality.EXACT
    )


def _count_clean_payouts_per_platform(transactions: list[RawTransaction]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for txn in transactions:
        if txn.credit is None:
            continue
        platform = _match_platform(txn.description)
        if platform is None:
            continue
        if _has_refund_marker(txn.description):
            continue
        counts[platform] += 1
    return dict(counts)


def classify_statement(
    transactions: list[RawTransaction], source_type: SourceType = SourceType.BANK_STATEMENT
) -> list[IncomeEvent]:
    payout_counts = _count_clean_payouts_per_platform(transactions)

    events: list[IncomeEvent] = []
    for txn in transactions:
        if txn.credit is not None:
            result = classify_transaction(txn, payout_counts)
            events.append(
                IncomeEvent(
                    date=txn.date,
                    amount=txn.credit,
                    direction=Direction.CREDIT,
                    event_type=result.event_type,
                    platform=result.platform or "unknown",
                    source_type=source_type,
                    match_quality=result.match_quality,
                    raw_description=txn.description,
                )
            )
        elif txn.debit is not None:
            result = classify_transaction(txn, payout_counts)
            events.append(
                IncomeEvent(
                    date=txn.date,
                    amount=txn.debit,
                    direction=Direction.DEBIT,
                    event_type=result.event_type,
                    platform=result.platform or "unknown",
                    source_type=source_type,
                    match_quality=result.match_quality,
                    raw_description=txn.description,
                )
            )

    return events


def needs_confirmation(event: IncomeEvent) -> bool:
    return event.match_quality in (MatchQuality.AMBIGUOUS, MatchQuality.UNMATCHED)
