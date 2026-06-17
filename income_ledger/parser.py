from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pdfplumber


def _log(msg: str) -> None:
    print(f"[parser] {msg}", file=sys.stderr, flush=True)

EXPECTED_HEADER = ["Date", "Description", "Debit", "Credit"]

_LLM_TEXT_CHAR_LIMIT = 28_000

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ScannedPdfError(Exception):
    pass


@dataclass(frozen=True)
class RawTransaction:
    date: date
    description: str
    credit: float | None
    debit: float | None


def _parse_amount(raw: str) -> float | None:
    raw = raw.strip().replace(",", "")
    if not raw:
        return None
    return float(raw)


def _parse_date(raw: str) -> date:
    day, month, year = raw.strip().split("/")
    return date(int(year), int(month), int(day))


def is_text_based(pdf_path: str | Path) -> bool:
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text and text.strip():
                return True
    return False


def _extract_raw_text(pdf_path: Path) -> str:
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                parts.append(text)
    return "\n".join(parts)


_LLM_PROMPT = """\
You are a bank statement parser. Extract every transaction from the bank \
statement text below and return them as a JSON array.

Rules:
- Return ONLY a valid JSON array, no explanation, no markdown, no code fences.
- Each element must have exactly these fields:
    "date"        : transaction date in YYYY-MM-DD format
    "description" : narration / description text exactly as it appears
    "debit"       : debit amount as a number, or null if no debit
    "credit"      : credit amount as a number, or null if no credit
- Do NOT include header rows, balance rows, opening/closing balance lines, \
or summary rows.
- Do NOT invent or alter any amounts or dates.
- If a row has both debit and credit blank, skip it.
- Amounts must be plain numbers (no currency symbols, no commas).

Bank statement text:
"""


def _parse_with_llm(raw_text: str) -> list[RawTransaction] | None:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        _log("No GEMINI_API_KEY — skipping LLM parser, using table fallback")
        return None

    _log(f"Sending {min(len(raw_text), _LLM_TEXT_CHAR_LIMIT)} chars to Gemini for parsing...")
    try:
        from google import genai

        text_to_send = raw_text[:_LLM_TEXT_CHAR_LIMIT]
        prompt = _LLM_PROMPT + text_to_send

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        raw_response = response.text.strip()
        _log(f"Gemini responded ({len(raw_response)} chars): {raw_response[:200]!r}...")
    except Exception as exc:
        _log(f"Gemini call failed: {exc} — falling back to table parser")
        return None

    result = _validate_llm_response(raw_response)
    if result is None:
        _log("LLM response failed validation — falling back to table parser")
    else:
        _log(f"LLM parsed {len(result)} transactions successfully")
    return result


def _validate_llm_response(raw_response: str) -> list[RawTransaction] | None:
    text = raw_response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    try:
        rows = json.loads(text)
    except json.JSONDecodeError as exc:
        _log(f"JSON decode failed: {exc} — raw: {text[:300]!r}")
        return None

    if not isinstance(rows, list):
        _log(f"LLM returned non-list type: {type(rows)}")
        return None

    _log(f"JSON parsed OK — {len(rows)} raw rows from LLM")

    transactions: list[RawTransaction] = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        date_raw = str(row.get("date", "")).strip()
        if not _ISO_DATE_RE.match(date_raw):
            continue
        try:
            txn_date = date.fromisoformat(date_raw)
        except ValueError:
            continue

        desc = str(row.get("description", "")).strip()
        if not desc:
            continue

        def _coerce_amount(val) -> float | None:
            if val is None or val == "" or val == "null":
                return None
            try:
                cleaned = str(val).replace(",", "").strip()
                if not cleaned:
                    return None
                return float(cleaned)
            except (ValueError, TypeError):
                return None

        debit = _coerce_amount(row.get("debit"))
        credit = _coerce_amount(row.get("credit"))

        if debit is None and credit is None:
            continue

        if (debit is not None and debit < 0) or (credit is not None and credit < 0):
            continue

        transactions.append(
            RawTransaction(date=txn_date, description=desc, debit=debit, credit=credit)
        )

    return transactions if transactions else None


_DATE_PATTERNS = [
    re.compile(r"(\d{2}/\d{2}/\d{4})"),
    re.compile(r"(\d{2}-\d{2}-\d{4})"),
    re.compile(r"(\d{2}-[A-Za-z]{3}-\d{4})"),
    re.compile(r"(\d{4}-\d{2}-\d{2})"),
]

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_AMOUNT_RE = re.compile(r"(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)")


def _parse_date_flexible(raw: str) -> date | None:
    raw = raw.strip()
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", raw)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})", raw)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.fullmatch(r"(\d{2})-([A-Za-z]{3})-(\d{4})", raw)
    if m:
        mon = _MONTH_MAP.get(m.group(2).lower())
        if mon:
            return date(int(m.group(3)), mon, int(m.group(1)))
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _parse_table_based(pdf_path: Path) -> list[RawTransaction]:
    transactions: list[RawTransaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue

            rows = list(table)
            if not rows:
                continue

            header_idx = None
            date_col = desc_col = debit_col = credit_col = None

            for i, row in enumerate(rows):
                if not row:
                    continue
                cells = [str(c).strip().lower() if c else "" for c in row]
                if any("date" in c for c in cells) and (
                    any("debit" in c or "withdrawal" in c or "dr" == c for c in cells) or
                    any("credit" in c or "deposit" in c or "cr" == c for c in cells)
                ):
                    header_idx = i
                    for j, c in enumerate(cells):
                        if "date" in c and date_col is None:
                            date_col = j
                        if ("narration" in c or "description" in c or
                                "particulars" in c or "details" in c or
                                "remarks" in c) and desc_col is None:
                            desc_col = j
                        if ("debit" in c or "withdrawal" in c or
                                "dr" == c or "dr." in c) and debit_col is None:
                            debit_col = j
                        if ("credit" in c or "deposit" in c or
                                "cr" == c or "cr." in c) and credit_col is None:
                            credit_col = j
                    break

            if date_col is None:
                date_col, desc_col, debit_col, credit_col = 0, 1, 2, 3

            data_rows = rows[(header_idx + 1) if header_idx is not None else 0:]

            for row in data_rows:
                if not row or len(row) <= max(
                    c for c in [date_col, desc_col, debit_col, credit_col]
                    if c is not None
                ):
                    continue

                date_raw = str(row[date_col]).strip() if row[date_col] else ""
                if not date_raw:
                    continue

                txn_date = _parse_date_flexible(date_raw)
                if txn_date is None:
                    continue

                desc_raw = str(row[desc_col]).strip() if desc_col is not None and row[desc_col] else ""
                debit_raw = str(row[debit_col]).strip() if debit_col is not None and row[debit_col] else ""
                credit_raw = str(row[credit_col]).strip() if credit_col is not None and row[credit_col] else ""

                debit = _parse_amount(debit_raw) if debit_raw else None
                credit = _parse_amount(credit_raw) if credit_raw else None

                if debit is None and credit is None:
                    continue

                transactions.append(
                    RawTransaction(
                        date=txn_date,
                        description=desc_raw,
                        debit=debit,
                        credit=credit,
                    )
                )

    if transactions:
        return transactions

    return _parse_text_lines(pdf_path)


def _parse_text_lines(pdf_path: Path) -> list[RawTransaction]:
    transactions: list[RawTransaction] = []
    _log("Trying line-by-line text scanner as last resort...")

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                txn_date = None
                for pat in _DATE_PATTERNS:
                    m = pat.match(line)
                    if m:
                        txn_date = _parse_date_flexible(m.group(1))
                        if txn_date:
                            remainder = line[m.end():].strip()
                            break
                if not txn_date:
                    continue

                amounts = [
                    float(a.replace(",", ""))
                    for a in _AMOUNT_RE.findall(remainder)
                    if float(a.replace(",", "")) > 0
                ]
                if not amounts:
                    continue

                txn_amount = amounts[0]

                first_amt_match = _AMOUNT_RE.search(remainder)
                desc = remainder[:first_amt_match.start()].strip() if first_amt_match else remainder

                if not desc:
                    continue

                line_upper = line.upper()
                is_debit = any(k in line_upper for k in ["DR", "DEBIT", "WDL", "WITHDRAW", "PAID"])
                is_credit = any(k in line_upper for k in ["CR", "CREDIT", "DEPOSIT", "RECD"])

                if is_debit and not is_credit:
                    transactions.append(RawTransaction(date=txn_date, description=desc, debit=txn_amount, credit=None))
                else:
                    transactions.append(RawTransaction(date=txn_date, description=desc, debit=None, credit=txn_amount))

    _log(f"Line scanner found {len(transactions)} transactions")
    return transactions


def parse_sbi_statement(pdf_path: str | Path) -> list[RawTransaction]:
    pdf_path = Path(pdf_path)

    if not is_text_based(pdf_path):
        raise ScannedPdfError(
            f"{pdf_path} has no extractable text — looks like a scanned "
            "image PDF. OCR is out of scope; cannot parse."
        )

    raw_text = _extract_raw_text(pdf_path)
    _log(f"Extracted {len(raw_text)} chars of raw text from PDF")

    llm_result = _parse_with_llm(raw_text)
    if llm_result is not None:
        _log(f"Using LLM result: {len(llm_result)} transactions")
        return llm_result

    _log("Trying table-based fallback parser...")
    table_result = _parse_table_based(pdf_path)
    _log(f"Table parser found {len(table_result)} transactions")
    return table_result
