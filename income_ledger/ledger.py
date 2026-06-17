from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path

from income_ledger.schemas import (
    Direction,
    EventType,
    IncomeEvent,
    MatchQuality,
    MonthlySummary,
    SourceType,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS workers (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    label TEXT NOT NULL DEFAULT 'default_worker'
);

CREATE TABLE IF NOT EXISTS income_events (
    event_id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    amount REAL NOT NULL,
    direction TEXT NOT NULL,
    event_type TEXT NOT NULL,
    platform TEXT NOT NULL,
    source_type TEXT NOT NULL,
    match_quality TEXT NOT NULL,
    raw_description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monthly_summaries (
    month TEXT NOT NULL,
    platform TEXT NOT NULL,
    net_income REAL NOT NULL,
    PRIMARY KEY (month, platform)
);
"""


class Ledger:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO workers (id, label) VALUES (1, 'default_worker')"
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def add_events(self, events: list[IncomeEvent]) -> None:
        self._conn.executemany(
            """
            INSERT OR REPLACE INTO income_events
                (event_id, date, amount, direction, event_type, platform,
                 source_type, match_quality, raw_description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    e.event_id,
                    e.date.isoformat(),
                    e.amount,
                    e.direction.value,
                    e.event_type.value,
                    e.platform,
                    e.source_type.value,
                    e.match_quality.value,
                    e.raw_description,
                )
                for e in events
            ],
        )
        self._conn.commit()

    def get_events(self) -> list[IncomeEvent]:
        rows = self._conn.execute(
            """
            SELECT event_id, date, amount, direction, event_type, platform,
                   source_type, match_quality, raw_description
            FROM income_events
            ORDER BY date
            """
        ).fetchall()
        return [
            IncomeEvent(
                event_id=row[0],
                date=_parse_iso_date(row[1]),
                amount=row[2],
                direction=Direction(row[3]),
                event_type=EventType(row[4]),
                platform=row[5],
                source_type=SourceType(row[6]),
                match_quality=MatchQuality(row[7]),
                raw_description=row[8],
            )
            for row in rows
        ]

    def recompute_monthly_summaries(self) -> list[MonthlySummary]:
        events = self.get_events()
        net_by_month_platform: dict[tuple[str, str], float] = defaultdict(float)

        for event in events:
            if event.platform == "unknown":
                continue

            month = event.date.strftime("%Y-%m")
            key = (month, event.platform)

            if event.event_type == EventType.PAYOUT and event.direction == Direction.CREDIT:
                net_by_month_platform[key] += event.amount
            elif event.event_type == EventType.REVERSAL:
                net_by_month_platform[key] -= event.amount
            elif event.event_type == EventType.ADJUSTMENT:
                if event.direction == Direction.CREDIT:
                    net_by_month_platform[key] += event.amount
                else:
                    net_by_month_platform[key] -= event.amount

        summaries = [
            MonthlySummary(month=month, platform=platform, net_income=net_income)
            for (month, platform), net_income in sorted(net_by_month_platform.items())
        ]

        self._conn.execute("DELETE FROM monthly_summaries")
        self._conn.executemany(
            "INSERT INTO monthly_summaries (month, platform, net_income) VALUES (?, ?, ?)",
            [(s.month, s.platform, s.net_income) for s in summaries],
        )
        self._conn.commit()

        return summaries

    def get_monthly_summaries(self) -> list[MonthlySummary]:
        rows = self._conn.execute(
            "SELECT month, platform, net_income FROM monthly_summaries ORDER BY month, platform"
        ).fetchall()
        return [MonthlySummary(month=row[0], platform=row[1], net_income=row[2]) for row in rows]


def _parse_iso_date(value: str):
    from datetime import date

    year, month, day = value.split("-")
    return date(int(year), int(month), int(day))
