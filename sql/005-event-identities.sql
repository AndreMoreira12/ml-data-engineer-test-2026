-- Identity/evidence tables, not resolved annotation versions.
CREATE TABLE IF NOT EXISTS event_payloads (
    event_id text NOT NULL CHECK (btrim(event_id) <> ''),
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    canonical_payload text NOT NULL,
    PRIMARY KEY (event_id,payload_sha256)
);

CREATE TABLE IF NOT EXISTS event_occurrences (
    source_file_id text NOT NULL,
    row_number bigint NOT NULL,
    event_id text NOT NULL,
    payload_sha256 text NOT NULL,
    PRIMARY KEY (source_file_id,row_number),
    FOREIGN KEY (source_file_id,row_number)
        REFERENCES source_records(source_file_id,row_number),
    FOREIGN KEY (event_id,payload_sha256)
        REFERENCES event_payloads(event_id,payload_sha256)
);

-- One row per nonconflicted event ID, excluding any quarantined occurrence.
-- Passing today's checks does not imply resolved current state/training eligibility.
CREATE OR REPLACE VIEW event_candidates AS
SELECT p.event_id,p.payload_sha256,p.canonical_payload
FROM event_payloads p
WHERE NOT EXISTS (SELECT 1 FROM event_payloads other
                  WHERE other.event_id=p.event_id AND other.payload_sha256<>p.payload_sha256)
  AND NOT EXISTS (SELECT 1 FROM event_occurrences o JOIN quarantine q
                  USING (source_file_id,row_number) WHERE o.event_id=p.event_id);
