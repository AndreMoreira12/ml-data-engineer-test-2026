"""Optional PostgreSQL checks: set DATABASE_URL after applying all schema files."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from pipeline.annotators import ingest_annotators, known_annotator_ids
from pipeline.ingest import ingest_events
from pipeline.frames import ingest_frames, known_frame_ids
from pipeline.taxonomy import ingest_taxonomy, known_taxonomies


@unittest.skipUnless(os.environ.get("DATABASE_URL"), "DATABASE_URL not set")
class DatabaseTests(unittest.TestCase):
    def test_event_duplicates_conflicts_and_replay_across_exports(self):
        import psycopg
        from pipeline.ingest import read_source

        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5) as connection:
            with connection.transaction(force_rollback=True), tempfile.TemporaryDirectory() as directory:
                a, b, changed = (Path(directory) / name for name in ("a.jsonl", "b.jsonl", "changed.jsonl"))
                base = dict(event_id="fixture_event_identity", sample_id="fixture_identity_sample",
                            frame_ids=["fixture_unknown_frame"], annotator_id="fixture_unknown_person",
                            exporter_version="2.0", saved_at="2026-05-19T07:00:00Z",
                            label_tree_version=1, instances=[{"label": "Normal", "geometry": None}])
                a.write_text(json.dumps(base) + "\n", encoding="utf-8")
                b.write_text(json.dumps(dict(reversed(list(base.items()))), indent=2).replace('\n', ' ') + "\n", encoding="utf-8")
                for path in (a, b):
                    ingest_events(connection, path)
                self.assertEqual(connection.execute("SELECT count(*) FROM event_payloads WHERE event_id=%s", (base['event_id'],)).fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT count(*) FROM event_occurrences WHERE event_id=%s", (base['event_id'],)).fetchone()[0], 2)
                # Remove only unrelated fixture reasons to exercise candidate visibility.
                connection.execute("""DELETE FROM quarantine WHERE source_file_id IN
                                    (SELECT source_file_id FROM event_occurrences WHERE event_id=%s)""", (base['event_id'],))
                self.assertEqual(connection.execute("SELECT count(*) FROM event_candidates WHERE event_id=%s", (base['event_id'],)).fetchone()[0], 1)
                changed.write_text(json.dumps(dict(base, status="draft")) + "\n", encoding="utf-8")
                ingest_events(connection, changed)
                self.assertEqual(connection.execute("SELECT count(*) FROM event_candidates WHERE event_id=%s", (base['event_id'],)).fetchone()[0], 0)
                for path in (a, b, changed):
                    file_id, _ = read_source(path)
                    self.assertEqual(connection.execute("SELECT count(*) FROM quarantine WHERE source_file_id=%s AND reason_code='CONFLICTING_EVENT_ID'", (file_id,)).fetchone()[0], 1)
                # Restore unrelated fixture reasons before checking exact replay.
                ingest_events(connection, a)
                ingest_events(connection, b)
                def snapshot():
                    return [connection.execute('SELECT * FROM '+table+' ORDER BY 1,2').fetchall()
                            for table in ('event_payloads','event_occurrences','source_records','quarantine')]
                before = snapshot()
                for path in (changed, b, a):
                    ingest_events(connection, path)
                self.assertEqual(snapshot(), before)

    def test_invalid_geometry_quarantines_whole_source_version(self):
        import psycopg

        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5) as connection:
            with connection.transaction(force_rollback=True), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "geometry.jsonl"
                payload = dict(sample_id="fixture_geometry", frame_ids=["missing_fixture_frame"],
                               annotator_id="missing_fixture_person", exporter_version="2.0",
                               saved_at="2026-05-19T07:00:00Z", label_tree_version=1, instances=[
                    {"label": "Normal", "geometry": None},
                    {"label": "Defect/Hole", "geometry": {"type": "point", "coordinates": [[-1, 5]]}}])
                path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
                report = ingest_events(connection, path)
                self.assertEqual(report["geometry_failures"]["GEOMETRY_OUT_OF_BOUNDS"], 1)
                # A single raw source version remains complete, including its valid instance.
                from pipeline.ingest import read_source
                file_id, raw = read_source(path)
                self.assertEqual(connection.execute("SELECT raw_content FROM source_files WHERE source_file_id=%s", (file_id,)).fetchone()[0], raw)
                self.assertEqual(connection.execute(
                    "SELECT count(*) FROM quarantine WHERE source_file_id=%s AND reason_code='GEOMETRY_OUT_OF_BOUNDS'", (file_id,)
                ).fetchone()[0], 1)
                before = connection.execute("SELECT * FROM quarantine WHERE source_file_id=%s ORDER BY reason_code", (file_id,)).fetchall()
                ingest_events(connection, path)
                self.assertEqual(connection.execute("SELECT * FROM quarantine WHERE source_file_id=%s ORDER BY reason_code", (file_id,)).fetchall(), before)

    def test_taxonomy_replay_and_changed_meaning_are_not_overwritten(self):
        import psycopg

        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5) as connection:
            with connection.transaction(force_rollback=True), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "tree.yaml"
                text = ("version: 9876\nreleased: 2026-01-01\nlabels:\n"
                        "  - name: Normal\n    geometry: none\n    description: First meaning.\n")
                path.write_text(text, encoding="utf-8")
                self.assertEqual(ingest_taxonomy(connection, path)["new_labels"], 1)
                self.assertEqual(ingest_taxonomy(connection, path)["new_labels"], 0)
                bad_event = path.with_name("event.jsonl")
                bad_event.write_text(json.dumps({"label_tree_version": 9876,
                    "instances": [{"label": "Normal"}, {"label": "Typo"}]}) + "\n", encoding="utf-8")
                self.assertEqual(ingest_events(connection, bad_event)["label_failures"], {"UNKNOWN_LABEL": 1})
                before = connection.execute('SELECT count(*) FROM quarantine').fetchone()
                ingest_events(connection, bad_event)
                self.assertEqual(connection.execute('SELECT count(*) FROM quarantine').fetchone(), before)
                changed = path.with_name("changed.yaml")
                changed.write_text(text.replace("First meaning.", "Changed meaning."), encoding="utf-8")
                self.assertEqual(ingest_taxonomy(connection, changed)["document_failures"],
                                 ["CONFLICTING_TAXONOMY_VERSION"])
                self.assertEqual(connection.execute(
                    "SELECT description FROM taxonomy_labels WHERE version=9876"
                ).fetchone()[0], "First meaning.")
                with connection.cursor() as cursor:
                    self.assertNotIn(9876, known_taxonomies(cursor))
                invalid = path.with_name("invalid.yaml")
                invalid.write_text("{broken", encoding="utf-8")
                self.assertEqual(ingest_taxonomy(connection, invalid)["document_failures"],
                                 ["INVALID_TAXONOMY_DOCUMENT"])

    def test_later_export_quarantines_both_membership_declarations(self):
        import psycopg

        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5) as connection:
            with connection.transaction(force_rollback=True), tempfile.TemporaryDirectory() as directory:
                a, b = Path(directory) / "a.jsonl", Path(directory) / "b.jsonl"
                base = dict(sample_id="fixture_membership", annotator_id="fixture_unknown",
                            saved_at="2026-05-19T07:00:00Z", exporter_version="2.0")
                a.write_text(json.dumps(dict(base, frame_ids=["fixture_f1"])) + "\n", encoding="utf-8")
                b.write_text(json.dumps(dict(base, frame_ids=["fixture_f1", "fixture_f2"])) + "\n", encoding="utf-8")
                ingest_events(connection, a)
                ingest_events(connection, b)
                def issues():
                    return connection.execute(
                        """SELECT q.* FROM quarantine q JOIN source_records r USING (source_file_id,row_number)
                           WHERE q.reason_code='INCONSISTENT_SAMPLE_FRAMES'
                             AND r.raw_text LIKE '%fixture_membership%' ORDER BY 1,2"""
                    ).fetchall()
                before = issues()
                self.assertEqual(len(before), 2)
                ingest_events(connection, b)
                ingest_events(connection, a)
                self.assertEqual(issues(), before)

    def test_evidence_conflicts_multiple_reasons_and_rerun(self):
        import psycopg

        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5) as connection:
            # All fixtures, including raw evidence, are rolled back after the test.
            with connection.transaction(force_rollback=True), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "annotators.csv"
                path.write_text(
                    "annotator_id,display_name,site,active_from,active_to\n"
                    "test_identity,Inês,Porto,2026-01-01,\n"
                    "test_identity,Inês,Porto,2026-01-01,\n"
                    "test_bad_dates,Name,Porto,2026-02-01,2026-01-01\n", encoding="utf-8")
                first = ingest_annotators(connection, path)
                self.assertEqual(first["new_annotators"], 1)
                self.assertEqual(first["row_failures"], {"INVALID_ANNOTATOR_DATES": 1})
                event_path = path.with_name("events.jsonl")
                event_path.write_text(json.dumps({"annotator_id": "test_missing", "saved_at": "bad",
                                                 "exporter_version": "2.0"}) + "\n{broken\n" +
                                      json.dumps({"annotator_id": "test_identity",
                                                  "saved_at": "2025-12-31T12:00:00Z",
                                                  "exporter_version": "2.0"}) + "\n", encoding="utf-8")
                report = ingest_events(connection, event_path)
                self.assertEqual(report["annotator_failures"],
                                 {"UNKNOWN_ANNOTATOR": 1, "ANNOTATOR_OUTSIDE_ACTIVE_DATES": 1})
                self.assertEqual(connection.execute(
                    "SELECT count(*) FROM quarantine WHERE reason_code='ANNOTATOR_OUTSIDE_ACTIVE_DATES'"
                ).fetchone()[0], 1)
                self.assertEqual(report["timestamp_failures"], {"INVALID_SAVED_AT": 1})
                self.assertEqual(report["parse_failures"], {"INVALID_JSON": 1})

                def snapshot():
                    return [connection.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall()
                            for table in ("source_files", "source_records", "quarantine", "annotators", "frames")]

                before = snapshot()
                self.assertEqual(ingest_annotators(connection, path)["new_annotators"], 0)
                self.assertEqual(ingest_events(connection, event_path)["new_raw_lines"], 0)
                self.assertEqual(snapshot(), before)
                conflict = path.with_name("conflict.csv")
                conflict.write_text(
                    "annotator_id,display_name,site,active_from,active_to\n"
                    "test_identity,Other name,Porto,2026-01-01,\n", encoding="utf-8")
                self.assertEqual(ingest_annotators(connection, conflict)["row_failures"],
                                 {"CONFLICTING_ANNOTATOR_ID": 1})
                with connection.cursor() as cursor:
                    self.assertNotIn("test_identity", known_annotator_ids(cursor))
                self.assertEqual(connection.execute(
                    "SELECT count(*) FROM quarantine WHERE reason_code='CONFLICTING_ANNOTATOR_ID'"
                ).fetchone()[0], 2)

    def test_frame_evidence_conflicts_and_event_quarantine(self):
        import psycopg

        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5) as connection:
            with connection.transaction(force_rollback=True), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "frames.csv"
                header = "frame_id,roll_id,machine_id,camera_position,light_type,captured_at,height_px,width_px\n"
                first = "fixture_frame,r1,m1,c1, vis,2026-05-19 08:04:00,1024,2448\n"
                path.write_text(header + first + first +
                                "fixture_bad,r1,m1,c1,VIS,2026-05-19 08:04:00,,2448\n", encoding="utf-8")
                report = ingest_frames(connection, path)
                self.assertEqual(report["new_frames"], 1)
                self.assertEqual(report["row_failures"], {"INVALID_FRAME_DIMENSIONS": 1})
                file_id = connection.execute("SELECT source_file_id FROM frames WHERE frame_id='fixture_frame'").fetchone()[0]
                self.assertEqual(connection.execute(
                    "SELECT raw_text FROM source_records WHERE source_file_id=%s AND row_number=1", (file_id,)
                ).fetchone()[0], path.read_bytes().decode("utf-8").splitlines(keepends=True)[1])
                conflict = path.with_name("conflict.csv")
                conflict.write_text(header + first.replace("1024,2448", "2448,1024"), encoding="utf-8")
                self.assertEqual(ingest_frames(connection, conflict)["row_failures"], {"CONFLICTING_FRAME_ID": 1})
                self.assertEqual(connection.execute(
                    """SELECT count(*) FROM quarantine q JOIN source_files s USING (source_file_id)
                       WHERE q.reason_code='CONFLICTING_FRAME_ID' AND s.filename IN ('frames.csv','conflict.csv')
                         AND q.source_file_id IN (SELECT source_file_id FROM source_records
                                                 WHERE raw_text LIKE 'fixture_frame,%')"""
                ).fetchone()[0], 2)
                # The conflict must not replace the original stored dimensions.
                self.assertEqual(connection.execute(
                    "SELECT height_px,width_px FROM frames WHERE frame_id='fixture_frame'"
                ).fetchone(), (1024, 2448))
                with connection.cursor() as cursor:
                    self.assertNotIn("fixture_frame", known_frame_ids(cursor))
                event = path.with_name("events.jsonl")
                event.write_text(json.dumps({"frame_ids": ["fixture_frame"], "annotator_id": "missing_fixture",
                                             "saved_at": "bad", "exporter_version": "2.0"}) + "\n", encoding="utf-8")
                self.assertEqual(ingest_events(connection, event)["frame_failures"], {"UNKNOWN_OR_INVALID_FRAME": 1})
                self.assertEqual(connection.execute(
                    """SELECT count(*) FROM quarantine q JOIN source_records r
                       USING (source_file_id,row_number)
                       WHERE q.reason_code='UNKNOWN_OR_INVALID_FRAME'
                         AND r.raw_text LIKE '%fixture_frame%'"""
                ).fetchone()[0], 1)
                def snapshot():
                    return [connection.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall()
                            for table in ("source_files", "source_records", "quarantine", "frames")]
                before = snapshot()
                self.assertEqual(ingest_frames(connection, path)["new_frames"], 0)
                ingest_frames(connection, conflict)
                ingest_events(connection, event)
                self.assertEqual(snapshot(), before)


if __name__ == "__main__":
    unittest.main()
