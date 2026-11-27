"""Raw input to records: one dict per applicant. Nothing here interprets meaning; that is the mapper's job.

- CSV: one record per row, header row required, delimiter detected (comma, semicolon, tab, pipe).
- JSON: an object, a list of objects, or {"records": [...]} / {"data": [...]}.
- PDF: form fields if the PDF is a fillable form, otherwise its text as notes.
- Text: notes.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any

MAX_RECORDS = 500
MAX_BYTES = 5 * 1024 * 1024


class ParseError(ValueError):
    """The file cannot be read. Messages describe the file, never its contents."""


@dataclass
class Parsed:
    source: str                     # csv | json | pdf | notes
    records: list[dict[str, Any]]
    warnings: list[str]


def _text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ParseError("the file is not text in a known encoding")


def parse_csv(data: bytes) -> Parsed:
    text = _text(data)
    if not text.strip():
        raise ParseError("the CSV file is empty")
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames or all(not (h or "").strip() for h in reader.fieldnames):
        raise ParseError("the CSV file has no header row")
    headers = [(h or "").strip() for h in reader.fieldnames]
    warnings: list[str] = []
    if len(set(headers)) != len(headers):
        warnings.append("Some column names appear twice; the last one of each was used.")
    records: list[dict[str, Any]] = []
    for n, row in enumerate(reader, start=2):
        clean = {(k or "").strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
        clean = {k: v for k, v in clean.items() if k and v not in (None, "")}
        if None in row:
            warnings.append(f"Row {n} has more values than there are columns; the extra values were ignored.")
        if clean:
            records.append(clean)
        if len(records) > MAX_RECORDS:
            raise ParseError(f"the CSV file has more than {MAX_RECORDS} rows; split it into smaller files")
    if not records:
        raise ParseError("the CSV file has a header but no rows")
    return Parsed("csv", records, warnings)


def parse_json(data: bytes | str | Any) -> Parsed:
    if isinstance(data, (bytes, str)):
        try:
            data = json.loads(_text(data) if isinstance(data, bytes) else data)
        except json.JSONDecodeError:
            raise ParseError("the file is not valid JSON") from None
    if isinstance(data, dict):
        for key in ("records", "data", "applicants", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    items = data if isinstance(data, list) else [data]
    records = [r for r in items if isinstance(r, dict) and r]
    if not records:
        raise ParseError("the JSON holds no records (objects)")
    if len(records) > MAX_RECORDS:
        raise ParseError(f"more than {MAX_RECORDS} records; split them into smaller files")
    skipped = len(items) - len(records)
    return Parsed("json", records, [f"{skipped} item(s) that are not objects were skipped."] if skipped else [])


def parse_pdf(data: bytes) -> Parsed:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ParseError("the PDF is password-protected")
        fields = reader.get_fields() or {}
        values = {}
        for name, f in fields.items():
            v = f.get("/V")
            if v is None or str(v).strip() in ("", "/Off"):
                continue
            values[str(name)] = "yes" if str(v) in ("/Yes", "/On", "/1") else str(v).lstrip("/")
        if values:
            return Parsed("pdf", [values], [])
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:20]).strip()
    except PdfReadError:
        raise ParseError("the PDF could not be read") from None
    if not text:
        return Parsed("pdf", [{"notes": ""}],
                      ["The PDF has no text layer (it may be a scan); a person needs to read it."])
    return Parsed("pdf", [{"notes": text}], [])


def parse_notes(text: str) -> Parsed:
    if not text.strip():
        raise ParseError("the notes are empty")
    return Parsed("notes", [{"notes": text.strip()}], [])


def parse_file(filename: str, content_type: str, data: bytes) -> Parsed:
    if len(data) > MAX_BYTES:
        raise ParseError(f"the file is larger than {MAX_BYTES // (1024 * 1024)} MB")
    name = filename.lower()
    if name.endswith(".csv") or content_type in ("text/csv", "application/vnd.ms-excel"):
        return parse_csv(data)
    if name.endswith(".json") or content_type == "application/json":
        return parse_json(data)
    if name.endswith(".pdf") or content_type == "application/pdf" or data[:5] == b"%PDF-":
        return parse_pdf(data)
    if name.endswith((".txt", ".md", ".eml")) or content_type.startswith("text/"):
        return parse_notes(_text(data))
    raise ParseError("unsupported file type: send CSV, JSON, PDF or plain text")
