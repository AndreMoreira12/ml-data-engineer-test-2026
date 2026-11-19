"""Frame metadata ingestion and event-reference checks; no inferred dimensions."""

import csv
import io
from collections import Counter

from pipeline.timestamps import TimestampError, normalize_saved_at


FIELDS = ["frame_id", "roll_id", "machine_id", "camera_position", "light_type",
          "captured_at", "height_px", "width_px"]


def validate_frame(row):
    if set(row) != set(FIELDS) or any(row[key] is None for key in FIELDS):
        return None, "INVALID_FRAME_ROW"
    if any(not row[key].strip() or row[key] != row[key].strip() for key in FIELDS[:4]):
        return None, "INVALID_FRAME_IDENTITY"
    light = row["light_type"].strip().upper()
    if light not in ("VIS", "IR"):
        return None, "INVALID_LIGHT_TYPE"
    try:
        height, width = int(row["height_px"]), int(row["width_px"])
        if not (0 < height <= 2147483647 and 0 < width <= 2147483647):
            raise ValueError
    except ValueError:
        return None, "INVALID_FRAME_DIMENSIONS"
    text = row["captured_at"]
    try:
        # Frame CSV has no exporter field: observed digit strings are milliseconds;
        # naive strings use the same plant-local interpretation as exporter 1.4.
        if text.isascii() and text.isdigit():
            captured = normalize_saved_at(int(text), "2.1")
        else:
            try:
                captured = normalize_saved_at(text, "2.0")
            except TimestampError as exc:
                if str(exc) != "MISSING_TIMESTAMP_OFFSET":
                    raise
                captured = normalize_saved_at(text, "1.4")
    except TimestampError as exc:
        return None, "FRAME_" + str(exc)
    return (*[row[key] for key in FIELDS[:4]], light, captured, height, width), None


def frame_reference_reasons(payload, known_frames):
    ids = payload.get("frame_ids")
    if not isinstance(ids, list):
        return ["INVALID_FRAME_IDS"]
    reasons = []
    if len(ids) not in (1, 2):
        reasons.append("INVALID_FRAME_COUNT")
    if any(not isinstance(value, str) or not value.strip() for value in ids):
        return reasons + ["INVALID_FRAME_IDS"]
    if len(set(ids)) != len(ids):
        reasons.append("DUPLICATE_FRAME_REFERENCE")
    if any(value not in known_frames for value in ids):
        reasons.append("UNKNOWN_OR_INVALID_FRAME")
    return reasons


def ingest_frames(connection, path):
    from pipeline.ingest import read_source

    file_id, raw = read_source(path)
    lines = raw.decode("utf-8").splitlines(keepends=True)
    reader = csv.DictReader(io.StringIO("".join(lines), newline=""))
    if reader.fieldnames != FIELDS:
        raise ValueError("Unexpected frames CSV header; no database changes made")
    failures = Counter()
    inserted = input_rows = normalized_lights = 0
    previous_line = reader.line_num
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("""INSERT INTO source_files VALUES (%s,%s,'csv',%s)
                          ON CONFLICT DO NOTHING""", (file_id, path.name, raw))
        for number, row in enumerate(reader, 1):
            input_rows += 1
            text = "".join(lines[previous_line:reader.line_num])
            previous_line = reader.line_num
            cursor.execute("""INSERT INTO source_records (source_file_id,row_number,raw_text)
                              VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""", (file_id, number, text))
            values, reason = validate_frame(row)
            if reason is None:
                normalized_lights += row["light_type"] != values[4]
                cursor.execute("""SELECT frame_id,roll_id,machine_id,camera_position,light_type,
                                         captured_at,height_px,width_px,source_file_id,row_number
                                  FROM frames WHERE frame_id=%s""", (values[0],))
                existing = cursor.fetchone()
                if existing is not None and tuple(existing[:8]) != values:
                    reason = "CONFLICTING_FRAME_ID"
                    cursor.execute("""INSERT INTO quarantine VALUES (%s,%s,%s)
                                      ON CONFLICT DO NOTHING""", (*existing[8:], reason))
                elif existing is None:
                    cursor.execute("""INSERT INTO frames VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                      ON CONFLICT DO NOTHING""", (*values, file_id, number))
                    inserted += cursor.rowcount
            if reason:
                failures[reason] += 1
                cursor.execute("""INSERT INTO quarantine VALUES (%s,%s,%s)
                                  ON CONFLICT DO NOTHING""", (file_id, number, reason))
    return {"input_rows": input_rows, "new_frames": inserted,
            "normalized_light_rows": normalized_lights, "row_failures": dict(failures)}


def known_frames(cursor):
    cursor.execute("""SELECT f.frame_id,f.roll_id,f.machine_id,f.camera_position,
                             f.light_type,f.height_px,f.width_px,f.captured_at FROM frames f WHERE NOT EXISTS (
                      SELECT 1 FROM quarantine q
                      WHERE q.source_file_id=f.source_file_id AND q.row_number=f.row_number)""")
    return {row[0]: dict(zip(("roll_id", "machine_id", "camera_position", "light_type",
                             "height_px", "width_px", "captured_at"), row[1:])) for row in cursor.fetchall()}


def known_frame_ids(cursor):
    return set(known_frames(cursor))
