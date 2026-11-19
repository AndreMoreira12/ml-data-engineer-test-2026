"""Deduplicate parsed event evidence without choosing winners for conflicts."""

import hashlib
import json


def event_identity_reason(payload):
    value = payload.get("event_id")
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        return "INVALID_EVENT_ID"
    return None


def canonical_event(payload):
    """Ignore object-key order and JSON formatting; retain arrays and JSON types.

    Do not apply domain normalization: different source timestamps or label strings
    remain different evidence even when a later rule could normalize them alike.
    """
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), text


def reconcile_event_ids(cursor):
    """Backfill every stored export, then quarantine all occurrences of conflicts."""
    from pipeline.ingest import parse_event

    cursor.execute("""SELECT r.source_file_id,r.row_number,r.raw_text
                      FROM source_records r JOIN source_files f USING (source_file_id)
                      LEFT JOIN event_occurrences o USING (source_file_id,row_number)
                      WHERE f.input_type='jsonl' AND o.source_file_id IS NULL""")
    variants_to_store = {}
    occurrences_to_store = []
    identifiers_to_store = []
    for file_id, number, text in cursor.fetchall():
        payload, reason = parse_event(text)
        if reason is not None or event_identity_reason(payload):
            continue
        event_id = payload["event_id"]
        digest, canonical = canonical_event(payload)
        variants_to_store[(event_id, digest)] = (event_id, digest, canonical)
        occurrences_to_store.append((file_id, number, event_id, digest))
        sample_id = payload.get("sample_id") if isinstance(payload.get("sample_id"), str) else None
        identifiers_to_store.append((event_id, sample_id, file_id, number, event_id, sample_id))
    if occurrences_to_store:
        cursor.executemany("""INSERT INTO event_payloads VALUES (%s,%s,%s)
                              ON CONFLICT DO NOTHING""", list(variants_to_store.values()))
        cursor.executemany("""INSERT INTO event_occurrences VALUES (%s,%s,%s,%s)
                              ON CONFLICT DO NOTHING""", occurrences_to_store)
        cursor.executemany("""UPDATE source_records SET event_id=%s,sample_id=%s
                          WHERE source_file_id=%s AND row_number=%s
                            AND (event_id IS DISTINCT FROM %s OR sample_id IS DISTINCT FROM %s)""",
                           identifiers_to_store)
    cursor.execute("""INSERT INTO quarantine (source_file_id,row_number,reason_code)
                      SELECT o.source_file_id,o.row_number,'CONFLICTING_EVENT_ID'
                      FROM event_occurrences o JOIN (
                          SELECT event_id FROM event_payloads GROUP BY event_id HAVING count(*)>1
                      ) conflicts USING (event_id) ON CONFLICT DO NOTHING""")
    cursor.execute("""SELECT count(*),count(DISTINCT event_id) FROM event_payloads""")
    variants, ids = cursor.fetchone()
    cursor.execute("SELECT count(*) FROM event_occurrences")
    occurrences = cursor.fetchone()[0]
    cursor.execute("""SELECT count(*) FROM (SELECT event_id FROM event_payloads
                      GROUP BY event_id HAVING count(*)>1) conflicts""")
    conflicts = cursor.fetchone()[0]
    return {"stored_occurrences": occurrences, "distinct_event_ids": ids,
            "distinct_payload_variants": variants, "repeated_payload_occurrences": occurrences - variants,
            "conflicting_event_ids": conflicts}
