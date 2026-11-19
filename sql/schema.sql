-- Raw evidence only. Validated domain tables follow in later increments.
BEGIN;

CREATE TABLE source_files (
    -- Lowercase SHA-256 of exact original bytes, calculated by Python.
    source_file_id text PRIMARY KEY
        CHECK (source_file_id ~ '^[0-9a-f]{64}$'),
    filename text NOT NULL CHECK (filename <> ''),
    input_type text NOT NULL CHECK (input_type IN ('csv', 'jsonl', 'yaml')),
    raw_content bytea NOT NULL
);

CREATE TABLE source_records (
    source_file_id text NOT NULL REFERENCES source_files (source_file_id),
    -- One-based data-record position: CSV header excluded; JSONL line position.
    -- A YAML document is one record. Original formatting remains in raw_content.
    row_number bigint NOT NULL CHECK (row_number > 0),
    raw_text text NOT NULL,
    -- Optional evidence identifiers, not validated-domain foreign keys.
    event_id text,
    sample_id text,
    PRIMARY KEY (source_file_id, row_number)
);

-- Multiple reasons may reference the same raw record; each reason occurs once.
CREATE TABLE quarantine (
    source_file_id text NOT NULL,
    row_number bigint NOT NULL,
    reason_code text NOT NULL CHECK (reason_code <> ''),
    PRIMARY KEY (source_file_id, row_number, reason_code),
    FOREIGN KEY (source_file_id, row_number)
        REFERENCES source_records (source_file_id, row_number)
);

COMMIT;
