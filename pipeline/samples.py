"""Sample membership is fixed; source ordering never selects a winning set."""

from collections import defaultdict


def sample_identity_reason(payload):
    value = payload.get("sample_id")
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        return "INVALID_SAMPLE_ID"
    return None


def conflicting_sample_ids(payloads):
    """Compare well-formed nonempty declarations, even on quarantined versions.

    Missing frames still constitute evidence of a different declared membership.
    Malformed/duplicate lists are handled by frame validation, not guessed here.
    """
    memberships = defaultdict(set)
    for payload in payloads:
        if sample_identity_reason(payload):
            continue
        ids = payload.get("frame_ids")
        if (not isinstance(ids, list) or not ids
                or any(not isinstance(value, str) or not value.strip() for value in ids)
                or len(set(ids)) != len(ids)):
            continue
        memberships[payload["sample_id"]].add(frozenset(ids))
    return {sample for sample, declarations in memberships.items() if len(declarations) > 1}


def reconcile_membership(cursor):
    """Recheck all preserved JSONL exports, including earlier occurrences."""
    from pipeline.ingest import parse_event

    cursor.execute("""SELECT r.source_file_id,r.row_number,r.raw_text
                      FROM source_records r JOIN source_files f USING (source_file_id)
                      WHERE f.input_type='jsonl'""")
    objects = []
    for file_id, number, text in cursor.fetchall():
        payload, reason = parse_event(text)
        if reason is None:
            objects.append((file_id, number, payload))
    conflicts = conflicting_sample_ids(payload for _, _, payload in objects)
    affected = 0
    for file_id, number, payload in objects:
        if sample_identity_reason(payload) is None and payload["sample_id"] in conflicts:
            cursor.execute("""INSERT INTO quarantine VALUES (%s,%s,'INCONSISTENT_SAMPLE_FRAMES')
                              ON CONFLICT DO NOTHING""", (file_id, number))
            affected += 1
    return {"conflicting_samples": len(conflicts), "affected_stored_event_lines": affected}
