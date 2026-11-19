"""Small CSV reference-data loader, retaining every source occurrence."""

import csv
import io
from collections import Counter
from datetime import date
from zoneinfo import ZoneInfo


FIELDS = ["annotator_id", "display_name", "site", "active_from", "active_to"]


def validate_annotator(row):
    """Return typed values or a whole-row quarantine reason; no silent repairs."""
    if set(row) != set(FIELDS) or any(row[key] is None for key in FIELDS):
        return None, "INVALID_ANNOTATOR_ROW"
    if any(not row[key].strip() or row[key] != row[key].strip()
           for key in ("annotator_id", "display_name", "site")):
        return None, "INVALID_ANNOTATOR_IDENTITY"
    try:
        start = date.fromisoformat(row["active_from"])
        end = date.fromisoformat(row["active_to"]) if row["active_to"] else None
    except ValueError:
        return None, "INVALID_ANNOTATOR_DATES"
    if end is not None and end < start:
        return None, "INVALID_ANNOTATOR_DATES"
    return (row["annotator_id"], row["display_name"], row["site"], start, end), None


def annotator_reason(payload, known_ids):
    value = payload.get("annotator_id")
    if not isinstance(value, str) or not value.strip():
        return "INVALID_ANNOTATOR_ID"
    if value not in known_ids:
        return "UNKNOWN_ANNOTATOR"
    return None


def active_date_reason(saved_at_utc, active_from, active_to):
    """Date-only roster boundaries include the whole Lisbon local day."""
    local_day = saved_at_utc.astimezone(ZoneInfo("Europe/Lisbon")).date()
    if local_day < active_from or (active_to is not None and local_day > active_to):
        return "ANNOTATOR_OUTSIDE_ACTIVE_DATES"
    return None


def ingest_annotators(connection, path):
    # Local import avoids a module cycle when ingest.py is the CLI entry point.
    from pipeline.ingest import read_source

    file_id, raw = read_source(path)
    lines = raw.decode("utf-8").splitlines(keepends=True)
    reader = csv.DictReader(io.StringIO("".join(lines), newline=""))
    if reader.fieldnames != FIELDS:
        raise ValueError("Unexpected annotators CSV header; no database changes made")
    failures = Counter()
    inserted = 0
    input_rows = 0
    previous_line = reader.line_num
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("""INSERT INTO source_files VALUES (%s, %s, 'csv', %s)
                          ON CONFLICT DO NOTHING""", (file_id, path.name, raw))
        for number, row in enumerate(reader, 1):
            input_rows += 1
            text = "".join(lines[previous_line:reader.line_num])
            previous_line = reader.line_num
            cursor.execute("""INSERT INTO source_records (source_file_id,row_number,raw_text)
                              VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""", (file_id, number, text))
            values, reason = validate_annotator(row)
            if reason is None:
                cursor.execute("""SELECT annotator_id,display_name,site,active_from,active_to,
                                         source_file_id,row_number
                                  FROM annotators WHERE annotator_id=%s""", (values[0],))
                existing = cursor.fetchone()
                if existing is not None and tuple(existing[:5]) != values:
                    reason = "CONFLICTING_ANNOTATOR_ID"
                    cursor.execute("""INSERT INTO quarantine VALUES (%s,%s,%s)
                                      ON CONFLICT DO NOTHING""", (*existing[5:], reason))
                elif existing is None:
                    cursor.execute("""INSERT INTO annotators VALUES (%s,%s,%s,%s,%s,%s,%s)
                                      ON CONFLICT DO NOTHING""", (*values, file_id, number))
                    inserted += cursor.rowcount
            if reason:
                failures[reason] += 1
                cursor.execute("""INSERT INTO quarantine VALUES (%s,%s,%s)
                                  ON CONFLICT DO NOTHING""", (file_id, number, reason))
    return {"input_rows": input_rows,
            "new_annotators": inserted, "row_failures": dict(failures)}


def known_annotators(cursor):
    # A conflicting original row remains evidence, but cannot establish identity.
    cursor.execute("""SELECT a.annotator_id,a.active_from,a.active_to FROM annotators a
                      WHERE NOT EXISTS (
                          SELECT 1 FROM quarantine q
                          WHERE q.source_file_id=a.source_file_id AND q.row_number=a.row_number
                      )""")
    return {row[0]: (row[1], row[2]) for row in cursor.fetchall()}


def known_annotator_ids(cursor):
    return set(known_annotators(cursor))
