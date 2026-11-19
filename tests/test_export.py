import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import psycopg

from pipeline.export import build_release, read_snapshot, sha256, write_release
from pipeline.splitting import split_for_roll


def fixture():
    rolls = {}
    for number in range(100):
        roll = f'roll-{number}'
        rolls.setdefault(split_for_roll(roll), roll)
    samples = [dict(sample_id=split, event_id=f'event-{split}', payload_sha256='payload',
                    frames=[dict(frame_id=f'{split}-VIS', roll_id=roll),
                            dict(frame_id=f'{split}-IR', roll_id=roll)],
                    instances=[dict(label='Normal', geometry=None, mapping_status='direct')])
               for split, roll in sorted(rolls.items())]
    raw = b'original source\r\n'
    sources = [dict(source_file_id=sha256(raw), filename='source.csv', input_type='csv', raw_content=raw)]
    return samples, sources, []


class ExportTests(unittest.TestCase):
    def test_listing_permission_error_is_reported_instead_of_missing_files(self):
        manifest, files = build_release(*fixture())
        with tempfile.TemporaryDirectory() as temp:
            write_release(temp, manifest, files)

            def denied_walk(path, onerror):
                onerror(PermissionError('Cannot list release directory'))
                return iter(())

            with patch('pipeline.export.os.walk', side_effect=denied_walk):
                with self.assertRaisesRegex(PermissionError, 'Cannot list'):
                    write_release(temp, manifest, files)

    def test_order_independent_bytes_and_frozen_release_after_later_data(self):
        samples, sources, taxonomy = fixture()
        manifest, files = build_release(samples, sources, taxonomy)
        self.assertEqual((manifest, files), build_release(list(reversed(samples)), sources, taxonomy))
        with tempfile.TemporaryDirectory() as temp:
            path = write_release(temp, manifest, files)
            self.assertEqual(path, write_release(temp, manifest, files))
            later = copy.deepcopy(samples)
            later[0]['instances'][0]['label'] = 'Defect/Hole'
            new_manifest, new_files = build_release(later, sources, taxonomy)
            self.assertNotEqual(manifest['release_id'], new_manifest['release_id'])
            write_release(temp, new_manifest, new_files)
            self.assertEqual((path / 'train.jsonl').read_bytes(), files['train.jsonl'])
            (path / 'train.jsonl').write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError, "changed:.*train.jsonl"):
                write_release(temp, manifest, files)

    def test_multiple_instances_count_once_per_label_per_sample(self):
        samples, sources, taxonomy = fixture()
        samples[0]['instances'] *= 2
        manifest, _ = build_release(samples, sources, taxonomy)
        split = split_for_roll(samples[0]['frames'][0]['roll_id'])
        self.assertEqual(manifest['counts'][split]['samples_per_label']['Normal'], 1)
        self.assertEqual(manifest['counts'][split]['instances_per_label']['Normal'], 2)

    def test_reject_unsafe_mapping_source_corruption_and_roll_or_frame_leakage(self):
        for problem in ('mapping', 'source', 'roll', 'frame'):
            samples, sources, taxonomy = fixture()
            if problem == 'mapping':
                samples[0]['instances'][0]['label'] = None
            elif problem == 'source':
                sources[0]['raw_content'] = b'changed'
            elif problem == 'roll':
                samples[0]['frames'][1]['roll_id'] = 'another-roll'
            else:
                samples[1]['frames'][0]['frame_id'] = samples[0]['frames'][0]['frame_id']
            with self.subTest(problem=problem), self.assertRaises(ValueError):
                build_release(samples, sources, taxonomy)

    def test_manifest_checksums_cover_exported_bytes_and_source_evidence(self):
        manifest, files = build_release(*fixture())
        for name, metadata in manifest['files'].items():
            self.assertEqual(sha256(files[name]), metadata['sha256'])
        source = manifest['sources'][0]
        self.assertEqual(sha256(files[source['path']]), source['sha256'])


@unittest.skipUnless(os.environ.get('DATABASE_URL'), 'DATABASE_URL not set')
class DatabaseExportTests(unittest.TestCase):
    def test_live_snapshot_replay_membership_and_no_leakage(self):
        with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
            first = read_snapshot(connection)
            second = read_snapshot(connection)
        manifest, files = build_release(*first)
        self.assertEqual((manifest, files), build_release(*second))
        splits = {split: [json.loads(line) for line in files[f'{split}.jsonl'].splitlines()]
                  for split in ('train', 'test')}
        for field in ('sample_id', 'roll_id'):
            self.assertFalse({s[field] for s in splits['train']} & {s[field] for s in splits['test']})
        frames = {split: {f['frame_id'] for s in rows for f in s['frames']}
                  for split, rows in splits.items()}
        self.assertFalse(frames['train'] & frames['test'])
        self.assertEqual({s['sample_id'] for s in first[0]},
                         {s['sample_id'] for rows in splits.values() for s in rows})
        self.assertTrue(all(s['export_taxonomy_version'] == 2 and i['label'] is not None
                            for rows in splits.values() for s in rows for i in s['instances']))
