"""Small ingestion steps, starting with preserving source evidence."""

import hashlib
import json
import math
import os
from collections import Counter
from pathlib import Path

from pipeline.timestamps import TimestampError, normalize_saved_at
from pipeline.annotators import active_date_reason, annotator_reason, ingest_annotators, known_annotators
from pipeline.frames import frame_reference_reasons, ingest_frames, known_frames
from pipeline.geometry import validate_event_geometry
from pipeline.samples import reconcile_membership, sample_identity_reason
from pipeline.taxonomy import ingest_taxonomy, known_taxonomies, validate_event_labels
from pipeline.events import event_identity_reason, reconcile_event_ids


def read_source(path: Path) -> tuple[str, bytes]:
    """Return the SHA-256 identity and exact bytes of a source file."""
    raw_content = path.read_bytes()
    source_file_id = hashlib.sha256(raw_content).hexdigest()
    return source_file_id, raw_content


def parse_event(raw_text: str) -> tuple[dict | None, str | None]:
    """Parse an event object; field and domain validation happens later."""
    def reject_nonfinite(value):
        raise ValueError("Nonfinite JSON number")

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Nonfinite JSON number")
        return number

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON object key")
            result[key] = value
        return result

    try:
        payload = json.loads(raw_text, object_pairs_hook=unique_object,
                             parse_constant=reject_nonfinite, parse_float=finite_float)
    except ValueError:
        return None, "INVALID_JSON"
    if not isinstance(payload, dict):
        return None, "EVENT_NOT_OBJECT"
    return payload, None


def ingest_events(connection, path: Path) -> dict:
    """Preserve evidence; quarantine whole versions failing the implemented checks."""
    source_file_id, raw_content = read_source(path)
    # Keep line endings. Even blank or malformed lines remain source evidence.
    lines = raw_content.decode("utf-8").splitlines(keepends=True)
    inserted = 0
    failures = Counter()
    timestamp_failures = Counter()
    annotator_failures = Counter()
    frame_failures = Counter()
    sample_failures = Counter()
    event_failures = Counter()
    label_failures = Counter()
    geometry_failures = Counter()
    normalized_labels = deprecated_labels = 0
    with connection.transaction():
        with connection.cursor() as cursor:
            people = known_annotators(cursor)
            frames = known_frames(cursor)
            taxonomies = known_taxonomies(cursor)
            cursor.execute(
                """INSERT INTO source_files
                   (source_file_id, filename, input_type, raw_content)
                   VALUES (%s, %s, 'jsonl', %s)
                   ON CONFLICT (source_file_id) DO NOTHING""",
                (source_file_id, path.name, raw_content),
            )
            for row_number, raw_text in enumerate(lines, start=1):
                cursor.execute(
                    """INSERT INTO source_records
                       (source_file_id, row_number, raw_text)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (source_file_id, row_number) DO NOTHING""",
                    (source_file_id, row_number, raw_text),
                )
                inserted += cursor.rowcount
                payload, reason = parse_event(raw_text)
                reasons = []
                if reason is None:
                    event_reason = event_identity_reason(payload)
                    if event_reason:
                        event_failures[event_reason] += 1
                        reasons.append(event_reason)
                    sample_reason = sample_identity_reason(payload)
                    if sample_reason:
                        sample_failures[sample_reason] += 1
                        reasons.append(sample_reason)
                    saved_at_utc = None
                    try:
                        saved_at_utc = normalize_saved_at(payload.get("saved_at"), payload.get("exporter_version"))
                    except TimestampError as exc:
                        timestamp_reason = str(exc)
                        timestamp_failures[timestamp_reason] += 1
                        reasons.append(timestamp_reason)
                    identity_reason = annotator_reason(payload, people)
                    if identity_reason is None and saved_at_utc is not None:
                        identity_reason = active_date_reason(saved_at_utc, *people[payload["annotator_id"]])
                    if identity_reason:
                        annotator_failures[identity_reason] += 1
                        reasons.append(identity_reason)
                    for frame_reason in frame_reference_reasons(payload, frames):
                        frame_failures[frame_reason] += 1
                        reasons.append(frame_reason)
                    label_issues, normalized, deprecated = validate_event_labels(payload, taxonomies)
                    normalized_labels += normalized
                    deprecated_labels += deprecated
                    # Quarantine reasons count versions/occurrences, not failed instances.
                    for label_reason in sorted({issue["reason"] for issue in label_issues}):
                        label_failures[label_reason] += 1
                        reasons.append(label_reason)
                    geometry_issues = validate_event_geometry(payload, taxonomies, frames)
                    for geometry_reason in sorted({issue["reason"] for issue in geometry_issues}):
                        geometry_failures[geometry_reason] += 1
                        reasons.append(geometry_reason)
                else:
                    failures[reason] += 1
                    reasons.append(reason)
                for reason in reasons:
                    cursor.execute(
                        """INSERT INTO quarantine
                           (source_file_id, row_number, reason_code)
                           VALUES (%s, %s, %s)
                           ON CONFLICT (source_file_id, row_number, reason_code)
                           DO NOTHING""",
                        (source_file_id, row_number, reason),
                    )
            membership_report = reconcile_membership(cursor)
            identity_report = reconcile_event_ids(cursor)
    return {
        "new_raw_lines": inserted,
        "input_lines": len(lines),
        "parsed_objects": len(lines) - sum(failures.values()),
        "parse_failures": dict(failures),
        "timestamp_checked_objects": len(lines) - sum(failures.values()),
        "timestamp_failures": dict(timestamp_failures),
        "annotator_failures": dict(annotator_failures),
        "frame_failures": dict(frame_failures),
        "sample_failures": dict(sample_failures),
        "event_identity_failures": dict(event_failures),
        "event_identity_across_stored_exports": identity_report,
        "label_failures": dict(label_failures),
        "geometry_failures": dict(geometry_failures),
        "normalized_label_instances": normalized_labels,
        "deprecated_label_instances": deprecated_labels,
        "membership_across_stored_exports": membership_report,
    }


def apply_schema(connection):
    sql_dir = Path(__file__).resolve().parent.parent / 'sql'
    if connection.execute("SELECT to_regclass('source_files')").fetchone()[0] is None:
        text = (sql_dir / 'schema.sql').read_text(encoding='utf-8')
        connection.execute(text.replace('BEGIN;', '').replace('COMMIT;', ''))
    for path in sorted(sql_dir.glob('0*.sql')):
        connection.execute(path.read_text(encoding='utf-8'))


def run_pipeline(connection, data_dir):
    from pipeline.coverage import ingest_coverage
    from pipeline.domain import rebuild_domain, validation_report

    with connection.transaction():
        apply_schema(connection)
        report = {
            'annotators': ingest_annotators(connection, data_dir / 'annotators.csv'),
            'frames': ingest_frames(connection, data_dir / 'frames.csv'),
            'taxonomy_v1': ingest_taxonomy(connection, data_dir / 'label_tree_v1.yaml'),
            'taxonomy_v2': ingest_taxonomy(connection, data_dir / 'label_tree_v2.yaml'),
            'coverage_targets': ingest_coverage(connection, data_dir / 'coverage_targets.csv'),
            'events': ingest_events(connection, data_dir / 'annotation_events.jsonl'),
        }
        report['domain'] = rebuild_domain(connection)
        report['validation'] = validation_report(connection)
        return report


def main():
    import argparse
    import psycopg

    parser = argparse.ArgumentParser(description='Load and validate all six source files.')
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).resolve().parent.parent / 'data')
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("Set DATABASE_URL before running ingestion.")
    with psycopg.connect(database_url, connect_timeout=5) as connection:
        report = run_pipeline(connection, args.data_dir)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
