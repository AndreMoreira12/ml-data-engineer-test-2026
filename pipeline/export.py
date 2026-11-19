"""Freeze eligible current annotations without changing the ingestion database."""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

import psycopg
from psycopg.rows import dict_row

from pipeline.splitting import SPLIT_SEED, split_for_roll


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                       allow_nan=False) + '\n').encode('utf-8')


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def read_snapshot(connection):
    """One repeatable-read snapshot prevents mixing states during ingestion."""
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cur:
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cur.execute("SET LOCAL TIME ZONE 'UTC'")
        cur.execute('SELECT source_file_id,filename,input_type,raw_content FROM source_files ORDER BY source_file_id')
        sources = cur.fetchall()
        cur.execute('''SELECT s.sample_id,v.event_id,v.payload_sha256,v.label_tree_version
                       FROM sample_state s JOIN annotation_versions v
                       ON v.event_id=s.representative_event_id
                       WHERE s.training_eligible ORDER BY s.sample_id''')
        samples = cur.fetchall()
        for sample in samples:
            cur.execute('''SELECT f.frame_id,f.roll_id,f.machine_id,f.camera_position,
                           f.light_type,f.height_px,f.width_px,f.captured_at
                           FROM sample_frames sf JOIN frames f USING(frame_id)
                           WHERE sf.sample_id=%s ORDER BY f.frame_id''', (sample['sample_id'],))
            sample['frames'] = cur.fetchall()
            for frame in sample['frames']:
                frame['captured_at'] = frame['captured_at'].isoformat()
            cur.execute('''SELECT instance_index,v2_label_path AS label,geometry,
                           original_label,label_path AS source_label,mapping_status,mapping_rule
                           FROM instances WHERE event_id=%s ORDER BY instance_index''', (sample['event_id'],))
            sample['instances'] = cur.fetchall()
            cur.execute('''SELECT v.event_id,v.payload_sha256,v.baseline_first_event_id
                           FROM current_contributors cc JOIN annotation_versions v USING(event_id)
                           WHERE cc.sample_id=%s ORDER BY v.event_id''', (sample['sample_id'],))
            sample['contributors'] = cur.fetchall()
        cur.execute('''SELECT label_path,geometry_type,description,deprecated,replaces
                       FROM taxonomy_labels WHERE version=2 ORDER BY label_path''')
        taxonomy = cur.fetchall()
    return samples, sources, taxonomy


def build_release(samples, sources, taxonomy):
    files = {}
    source_manifest = []
    for source in sorted(sources, key=lambda s: s['source_file_id']):
        raw = bytes(source['raw_content'])
        digest = source['source_file_id']
        if sha256(raw) != digest:
            raise ValueError('Source fingerprint does not match preserved bytes')
        path = f'sources/{digest}.bin'
        files[path] = raw
        source_manifest.append(dict(filename=source['filename'], input_type=source['input_type'],
                                    sha256=digest, path=path))
    rows = {'train': [], 'test': []}
    membership = []
    label_samples = {split: Counter() for split in rows}
    label_instances = {split: Counter() for split in rows}
    roll_splits, frame_splits = {}, {}
    seen_samples = set()
    for sample in sorted(samples, key=lambda s: s['sample_id']):
        if sample['sample_id'] in seen_samples:
            raise ValueError('Duplicate sample in release')
        seen_samples.add(sample['sample_id'])
        rolls = {f['roll_id'] for f in sample['frames']}
        if len(rolls) != 1:
            raise ValueError('Each sample must have frames from exactly one roll')
        roll = next(iter(rolls))
        split = split_for_roll(roll)
        roll_splits[roll] = split
        for frame in sample['frames']:
            previous = frame_splits.setdefault(frame['frame_id'], split)
            if previous != split:
                raise ValueError('Frame leakage between splits')
        if not sample['instances'] or any(i['label'] is None or i['mapping_status'] not in ('direct', 'safe')
                                          for i in sample['instances']):
            raise ValueError('Export requires nonempty, safely mapped v2 annotations')
        rows[split].append(encoded(dict(sample, split=split, roll_id=roll, export_taxonomy_version=2)))
        membership.append(dict(sample_id=sample['sample_id'], event_id=sample['event_id'],
                               payload_sha256=sample['payload_sha256'], roll_id=roll, split=split))
        labels = [i['label'] for i in sample['instances']]
        label_samples[split].update(set(labels))
        label_instances[split].update(labels)
    if not all(rows.values()):
        raise ValueError('Release needs nonempty train and test; inspect roll distribution')
    files.update({f'{split}.jsonl': b''.join(content) for split, content in rows.items()})
    files['taxonomy-v2.json'] = encoded(taxonomy)
    manifest = dict(format_version=1, sources=source_manifest, membership=membership,
                    rules=dict(eligibility='sample_state.training_eligible; resolved, independent review, '
                               'safe v2 mapping, no quarantined sample history',
                               coordinates='[row,column] pixels; paired frames share geometry',
                               split='SHA-256(seed + ":" + roll_id) < floor(2**256 / 5) => test',
                               seed=SPLIT_SEED, target_test_fraction=0.2,
                               label_count_unit='distinct samples per label; also report instances'),
                    counts={split: dict(samples=len(rows[split]),
                                        rolls=sum(s == split for s in roll_splits.values()),
                                        samples_per_label=dict(sorted(label_samples[split].items())),
                                        instances_per_label=dict(sorted(label_instances[split].items())))
                            for split in rows},
                    files={path: dict(sha256=sha256(content), bytes=len(content))
                           for path, content in sorted(files.items())})
    # Hash everything except the identifier itself. No wall-clock timestamp changes replay bytes.
    manifest['release_id'] = sha256(encoded(manifest))
    files['manifest.json'] = encoded(manifest)
    return manifest, files


def write_release(output_root, manifest, files):
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / manifest['release_id']
    if destination.exists():
        # Path.rglob can silently suppress permission errors on recent Python.
        def raise_walk_error(error):
            raise error

        existing = {}
        for directory, _, filenames in os.walk(destination, onerror=raise_walk_error):
            for filename in filenames:
                path = Path(directory) / filename
                existing[path.relative_to(destination).as_posix()] = path.read_bytes()
        if existing != files:
            missing = sorted(files.keys() - existing.keys())
            extra = sorted(existing.keys() - files.keys())
            changed = sorted(path for path in files.keys() & existing.keys()
                             if files[path] != existing[path])
            raise ValueError(f'Existing release differs at {destination.resolve()}; '
                             f'refusing to overwrite. Missing: {missing}; '
                             f'extra: {extra}; changed: {changed}. '
                             'Use --output-dir exports-check to create a separate copy for comparison.')
        return destination
    # Publish a complete directory only after every file has been written.
    # TemporaryDirectory uses mode 0700, which creates a restrictive Windows ACL.
    # A normal sibling directory inherits the output root's permissions instead.
    staging = root / f'.export-{uuid.uuid4().hex}'
    staging.mkdir()
    try:
        for path, content in files.items():
            target = staging / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        staging.rename(destination)
    finally:
        if staging.exists():
            if staging.resolve().parent != root.resolve():
                raise ValueError('Staging cleanup must remain inside output root')
            shutil.rmtree(staging)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('exports'))
    args = parser.parse_args()
    url = os.environ.get('DATABASE_URL')
    if not url:
        parser.error('Set DATABASE_URL before exporting')
    with psycopg.connect(url, connect_timeout=5, autocommit=True) as connection:
        samples, sources, taxonomy = read_snapshot(connection)
    manifest, files = build_release(samples, sources, taxonomy)
    destination = write_release(args.output_dir, manifest, files)
    print(json.dumps(dict(release_id=manifest['release_id'], path=str(destination), counts=manifest['counts']), indent=2))


if __name__ == '__main__':
    main()
