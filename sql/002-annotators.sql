-- Also safe to apply to an existing raw-ingestion database.
CREATE TABLE IF NOT EXISTS annotators (
    annotator_id text PRIMARY KEY CHECK (btrim(annotator_id) <> ''),
    display_name text NOT NULL CHECK (btrim(display_name) <> ''),
    site text NOT NULL CHECK (btrim(site) <> ''),
    active_from date NOT NULL,
    active_to date,
    source_file_id text NOT NULL,
    row_number bigint NOT NULL,
    CHECK (active_to IS NULL OR active_to >= active_from),
    FOREIGN KEY (source_file_id, row_number)
        REFERENCES source_records (source_file_id, row_number)
);
