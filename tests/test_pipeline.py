"""End-to-end tests use a private schema rolled back after each test."""

import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

from pipeline.ingest import run_pipeline


@unittest.skipUnless(os.environ.get('DATABASE_URL'), 'DATABASE_URL not set')
class PipelineTests(unittest.TestCase):
    def test_full_pipeline_state_mapping_eligibility_and_replay(self):
        import psycopg
        from psycopg import sql

        with psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=5) as connection:
            with connection.transaction(force_rollback=True), tempfile.TemporaryDirectory() as directory:
                schema = 'test_' + uuid.uuid4().hex
                connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
                connection.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
                root = Path(directory)
                for version in (1, 2):
                    (root / f'label_tree_v{version}.yaml').write_bytes(Path(f'data/label_tree_v{version}.yaml').read_bytes())
                (root / 'annotators.csv').write_text('annotator_id,display_name,site,active_from,active_to\nA01,Ana,Porto,2026-01-01,\nA02,Bruno,Porto,2026-01-01,\nA03,Carla,Porto,2026-01-01,\n', encoding='utf-8')
                (root / 'frames.csv').write_text('frame_id,roll_id,machine_id,camera_position,light_type,captured_at,height_px,width_px\nf1,r1,m1,c1,VIS,2026-05-01T00:00:00Z,100,200\n', encoding='utf-8')
                (root / 'coverage_targets.csv').write_text('label_path,target_samples\nNormal,10\nDefect/Hole,10\n', encoding='utf-8')
                events = []
                def add(eid, sample, parent=None, pass_='first', author='A01', status='committed', label='Normal', version=2, geometry=None):
                    events.append(dict(event_id=eid, sample_id=sample, frame_ids=['f1'], annotator_id=author,
                        session_id='session', **{'pass': pass_}, status=status, supersedes_event_id=parent,
                        saved_at='2026-07-10T12:00:00Z', exporter_version='2.0', label_tree_version=version,
                        instances=[{'label': label, 'geometry': geometry}]))
                add('a','reviewed',status='draft')
                add('b','reviewed','a','second','A02')
                oil = {'type': 'polygon','coordinates': [[0,0],[0,5],[5,0]]}
                add('c','oil',label='Defect/Stain/Oil',version=1,geometry=oil)
                add('d','oil','c','second','A02',label='Defect/Stain/Oil',version=1,geometry=oil)
                add('e','bad_save')
                add('f','bad_save','e','second','A02',geometry={'type':'point','coordinates':[[1,1]]})
                add('g','branches')
                add('h','branches','g','second','A02')
                add('i','branches','g','second','A03',label='Defect/Hole',geometry={'type':'point','coordinates':[[1,1]]})
                add('j','self_review')
                add('k','self_review','j','second','A01')
                path = root / 'annotation_events.jsonl'
                path.write_text('\n'.join(json.dumps(e) for e in events) + '\n', encoding='utf-8')
                report = run_pipeline(connection, root)
                self.assertEqual(report['domain']['training_eligible_samples'], 1)
                self.assertEqual(connection.execute("SELECT status,representative_event_id,training_eligible FROM sample_state WHERE sample_id='reviewed'").fetchone(), ('resolved','b',True))
                self.assertEqual(connection.execute("SELECT representative_event_id FROM sample_state WHERE sample_id='bad_save'").fetchone()[0], 'e')
                self.assertEqual(connection.execute("SELECT status FROM sample_state WHERE sample_id='branches'").fetchone()[0], 'conflict')
                self.assertEqual(connection.execute("SELECT v2_label_path,mapping_status FROM instances WHERE event_id='d'").fetchone(), (None,'review_required'))
                self.assertEqual(connection.execute("SELECT count(*) FROM annotation_versions WHERE event_id IN ('f','k')").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT current_samples FROM current_coverage WHERE label_path='Normal'").fetchone()[0], 3)
                tables = [r[0] for r in connection.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE' ORDER BY table_name", (schema,))]
                def snapshot():
                    return [sorted(connection.execute(sql.SQL('SELECT * FROM {}').format(sql.Identifier(table))).fetchall(), key=repr) for table in tables]
                before = snapshot()
                run_pipeline(connection, root)
                self.assertEqual(snapshot(), before)
                # A later export conflicts with a previously accepted review ID.
                changed = dict(events[1], session_id='different-session')
                path.write_text(json.dumps(changed) + '\n', encoding='utf-8')
                run_pipeline(connection, root)
                self.assertEqual(connection.execute("SELECT count(*) FROM annotation_versions WHERE event_id='b'").fetchone()[0], 0)
                self.assertFalse(connection.execute("SELECT training_eligible FROM sample_state WHERE sample_id='reviewed'").fetchone()[0])
                # Conflicting/invalid target rows stay as evidence, not new targets.
                with (root / 'coverage_targets.csv').open('a', encoding='utf-8') as stream:
                    stream.write('Normal,11\nDefect/Hole,-1\n')
                run_pipeline(connection, root)
                self.assertEqual(connection.execute("SELECT count(*) FROM quarantine WHERE reason_code='CONFLICTING_COVERAGE_TARGET'").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT count(*) FROM quarantine WHERE reason_code='INVALID_COVERAGE_TARGET'").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT count(*) FROM current_coverage WHERE label_path='Normal'").fetchone()[0], 0)
                before_failure = snapshot()
                with (root / 'annotators.csv').open('a', encoding='utf-8') as stream:
                    stream.write('A04,New person,Porto,2026-01-01,\n')
                (root / 'label_tree_v2.yaml').unlink()
                with self.assertRaises(FileNotFoundError):
                    run_pipeline(connection, root)
                self.assertEqual(snapshot(), before_failure)
