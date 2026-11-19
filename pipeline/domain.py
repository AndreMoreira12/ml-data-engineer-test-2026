"""Rebuild small derived domain tables from preserved evidence in one transaction."""

import json
from collections import defaultdict

from psycopg.types.json import Jsonb

from pipeline.annotators import known_annotators
from pipeline.frames import known_frames
from pipeline.history import resolve_current, validate_history
from pipeline.migration import migrate_label
from pipeline.samples import sample_identity_reason
from pipeline.taxonomy import known_taxonomies, normalize_label
from pipeline.timestamps import normalize_saved_at
from pipeline.validation import event_issues


def rebuild_domain(connection):
    from pipeline.ingest import parse_event

    with connection.transaction(), connection.cursor() as cursor:
        people, frames, taxonomies = known_annotators(cursor), known_frames(cursor), known_taxonomies(cursor)
        cursor.execute("""SELECT r.source_file_id,r.row_number,r.raw_text FROM source_records r
                          JOIN source_files f USING (source_file_id) WHERE f.input_type='jsonl'""")
        evidence = []
        for file_id, number, text in cursor.fetchall():
            payload, parse_reason = parse_event(text)
            issues = [{'reason': parse_reason}] if parse_reason else event_issues(payload, people, frames, taxonomies)
            evidence.append((file_id, number, payload))
            for issue in issues:
                reason = issue['reason']
                cursor.execute('INSERT INTO quarantine VALUES (%s,%s,%s) ON CONFLICT DO NOTHING', (file_id, number, reason))
                cursor.execute("""INSERT INTO validation_details VALUES (%s,%s,%s,%s,%s)
                                  ON CONFLICT DO NOTHING""", (file_id, number, reason, issue.get('instance_index', -1), Jsonb(issue)))
        cursor.execute("""SELECT event_id,canonical_payload,payload_sha256 FROM event_payloads p
                          WHERE NOT EXISTS (SELECT 1 FROM event_payloads other
                            WHERE other.event_id=p.event_id AND other.payload_sha256<>p.payload_sha256)""")
        rows = cursor.fetchall()
        events = {event_id: json.loads(text) for event_id, text, _ in rows}
        digests = {event_id: digest for event_id, _, digest in rows}
        cursor.execute('SELECT event_id FROM event_payloads GROUP BY event_id HAVING count(*)>1')
        conflicts = {r[0] for r in cursor.fetchall()}
        history_reasons, baselines = validate_history(events, conflicts)
        for event_id, reasons in history_reasons.items():
            for reason in reasons:
                cursor.execute("""INSERT INTO quarantine SELECT source_file_id,row_number,%s
                                  FROM event_occurrences WHERE event_id=%s ON CONFLICT DO NOTHING""", (reason, event_id))
        cursor.execute('SELECT event_id FROM event_candidates')
        valid = {r[0] for r in cursor.fetchall()}
        # Only derived tables are replaced. All original evidence/issues remain.
        for table in ('current_contributors', 'quality_flags', 'sample_state', 'instances', 'annotation_versions', 'sample_frames', 'samples'):
            cursor.execute('DELETE FROM ' + table)
        samples = {e['sample_id'] for _, _, e in evidence if e is not None and sample_identity_reason(e) is None}
        if samples:
            cursor.executemany('INSERT INTO samples VALUES (%s)', [(s,) for s in sorted(samples)])
        versions, instance_rows, memberships = [], [], set()
        canonical_events = {}
        for event_id in sorted(valid):
            event = events[event_id]
            saved = normalize_saved_at(event['saved_at'], event['exporter_version'])
            versions.append((event_id, digests[event_id], event['sample_id'], event['annotator_id'], event['session_id'],
                             event['pass'], event['status'], saved, event['label_tree_version'], event['supersedes_event_id'], baselines.get(event_id)))
            for frame in event['frame_ids']:
                memberships.add((event['sample_id'], frame))
            normalized = dict(event, instances=[])
            for index, instance in enumerate(event['instances']):
                path = normalize_label(instance['label'], taxonomies[event['label_tree_version']])
                target, status, rule = migrate_label(event['label_tree_version'], path)
                if target is not None and target not in taxonomies.get(2, {}):
                    target, status, rule = None, 'review_required', 'unavailable-v2-target'
                instance_rows.append((event_id, index, event['label_tree_version'], instance['label'], path,
                                      Jsonb(instance['geometry']) if instance['geometry'] is not None else None, target, status, rule))
                normalized['instances'].append(dict(instance, label=path))
            canonical_events[event_id] = normalized
        if versions:
            cursor.executemany('INSERT INTO annotation_versions VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', versions)
        if instance_rows:
            cursor.executemany('INSERT INTO instances VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)', instance_rows)
        if memberships:
            cursor.executemany('INSERT INTO sample_frames VALUES (%s,%s)', sorted(memberships))
        # Keep evidence ancestors for traversal, normalized valid leaves for content comparison.
        graph = dict(events)
        graph.update(canonical_events)
        states = resolve_current(graph, valid)
        cursor.execute("SELECT DISTINCT source_file_id,row_number FROM quarantine")
        bad_sources = set(cursor.fetchall())
        affected_samples = {e['sample_id'] for file_id, number, e in evidence
                            if (file_id, number) in bad_sources and e is not None and sample_identity_reason(e) is None}
        mappings = defaultdict(list)
        for row in instance_rows:
            mappings[row[0]].append(row[7])
        state_rows, contributor_rows, flags = [], [], []
        for sample in sorted(samples):
            state = states.get(sample, {'status': 'no_current', 'representative': None, 'contributors': [], 'leaves': []})
            reviewed = any(events[e]['pass'] == 'second' and e in baselines for e in state['contributors'])
            migration_review = any(status == 'review_required' for status in mappings[state['representative']])
            eligible = state['status'] == 'resolved' and reviewed and not migration_review and sample not in affected_samples
            state_rows.append((sample, state['status'], state['representative'], eligible))
            contributor_rows.extend((sample, event_id) for event_id in state['contributors'])
            if sample in affected_samples:
                flags.append((sample, 'UNRESOLVED_QUARANTINE', Jsonb({'message': 'Source history contains quarantined versions'})))
            if state['status'] == 'conflict':
                flags.append((sample, 'CONFLICTING_CURRENT_BRANCHES', Jsonb({'event_ids': state['leaves']})))
            if migration_review:
                flags.append((sample, 'MIGRATION_REVIEW_REQUIRED', Jsonb({'event_id': state['representative']})))
        if state_rows:
            cursor.executemany('INSERT INTO sample_state VALUES (%s,%s,%s,%s)', state_rows)
        if contributor_rows:
            cursor.executemany('INSERT INTO current_contributors VALUES (%s,%s)', contributor_rows)
        if flags:
            cursor.executemany('INSERT INTO quality_flags VALUES (%s,%s,%s)', flags)
        return {'valid_versions': len(versions), 'instances': len(instance_rows), 'samples': len(samples),
                'training_eligible_samples': sum(row[3] for row in state_rows)}


def validation_report(connection):
    with connection.cursor() as cursor:
        cursor.execute("""SELECT f.input_type,count(*),count(*) FILTER (WHERE EXISTS (
                          SELECT 1 FROM quarantine q WHERE q.source_file_id=r.source_file_id AND q.row_number=r.row_number))
                          FROM source_records r JOIN source_files f USING (source_file_id) GROUP BY f.input_type ORDER BY 1""")
        inputs = [{'type': kind, 'records': total, 'passed': total-failed, 'quarantined': failed}
                  for kind, total, failed in cursor.fetchall()]
        cursor.execute('SELECT reason_code,count(*) FROM quarantine GROUP BY reason_code ORDER BY reason_code')
        reasons = dict(cursor.fetchall())
        cursor.execute('SELECT status,count(*) FROM sample_state GROUP BY status ORDER BY status')
        return {'source_records': inputs, 'quarantine_occurrences_by_reason': reasons,
                'sample_states': dict(cursor.fetchall())}
