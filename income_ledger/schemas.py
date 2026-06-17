from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class Direction(str, Enum):
    CREDIT = "credit"
    DEBIT = "debit"


class EventType(str, Enum):
    PAYOUT = "payout"
    REVERSAL = "reversal"
    ADJUSTMENT = "adjustment"


class MatchQuality(str, Enum):
    EXACT = "exact"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"


class SourceType(str, Enum):
    BANK_STATEMENT = "bank_statement"
    PLATFORM_EXPORT = "platform_export"


class Trend(str, Enum):
    GROWING = "growing"
    DECLINING = "declining"
    STABLE_OR_INCONCLUSIVE = "stable_or_inconclusive"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class IncomeEvent:
    date: date
    amount: float
    direction: Direction
    event_type: EventType
    platform: str
    source_type: SourceType
    match_quality: MatchQuality
    raw_description: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError("amount must always be positive; use direction/event_type for sign")

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "date": self.date.isoformat(),
            "amount": self.amount,
            "direction": self.direction.value,
            "event_type": self.event_type.value,
            "platform": self.platform,
            "source_type": self.source_type.value,
            "match_quality": self.match_quality.value,
            "raw_description": self.raw_description,
        }

    @staticmethod
    def from_dict(data: dict) -> "IncomeEvent":
        return IncomeEvent(
            event_id=data["event_id"],
            date=date.fromisoformat(data["date"]),
            amount=data["amount"],
            direction=Direction(data["direction"]),
            event_type=EventType(data["event_type"]),
            platform=data["platform"],
            source_type=SourceType(data["source_type"]),
            match_quality=MatchQuality(data["match_quality"]),
            raw_description=data["raw_description"],
        )


@dataclass(frozen=True)
class MonthlySummary:
    month: str
    platform: str
    net_income: float

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "platform": self.platform,
            "net_income": self.net_income,
        }

    @staticmethod
    def from_dict(data: dict) -> "MonthlySummary":
        return MonthlySummary(
            month=data["month"],
            platform=data["platform"],
            net_income=data["net_income"],
        )


@dataclass(frozen=True)
class WorkerSummary:
    avg_monthly_income: float
    volatility_abs: float
    volatility_cv: float | None
    trend: Trend
    longest_gap_days: int | None = None

    def to_dict(self) -> dict:
        return {
            "avg_monthly_income": self.avg_monthly_income,
            "volatility_abs": self.volatility_abs,
            "volatility_cv": self.volatility_cv,
            "trend": self.trend.value,
            "longest_gap_days": self.longest_gap_days,
        }

    @staticmethod
    def from_dict(data: dict) -> "WorkerSummary":
        return WorkerSummary(
            avg_monthly_income=data["avg_monthly_income"],
            volatility_abs=data["volatility_abs"],
            volatility_cv=data.get("volatility_cv"),
            trend=Trend(data["trend"]),
            longest_gap_days=data.get("longest_gap_days"),
        )
