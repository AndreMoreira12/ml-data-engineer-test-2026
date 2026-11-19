CREATE TABLE IF NOT EXISTS samples (
    sample_id text PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS sample_frames (
    sample_id text NOT NULL REFERENCES samples(sample_id),
    frame_id text NOT NULL REFERENCES frames(frame_id),
    PRIMARY KEY (sample_id,frame_id)
);
CREATE TABLE IF NOT EXISTS annotation_versions (
    event_id text PRIMARY KEY,
    payload_sha256 text NOT NULL,
    sample_id text NOT NULL REFERENCES samples(sample_id),
    annotator_id text NOT NULL REFERENCES annotators(annotator_id),
    session_id text NOT NULL,
    pass text NOT NULL CHECK (pass IN ('first','second')),
    status text NOT NULL CHECK (status IN ('draft','committed')),
    saved_at timestamptz NOT NULL,
    label_tree_version integer NOT NULL REFERENCES taxonomy_versions(version),
    supersedes_event_id text,
    baseline_first_event_id text,
    FOREIGN KEY (event_id,payload_sha256) REFERENCES event_payloads(event_id,payload_sha256)
);
-- Parent/baseline IDs deliberately aren't FKs to accepted versions: evidence may
-- exist only in quarantine. History validation checks references against evidence.
CREATE TABLE IF NOT EXISTS instances (
    event_id text NOT NULL REFERENCES annotation_versions(event_id),
    instance_index integer NOT NULL CHECK (instance_index >= 0),
    taxonomy_version integer NOT NULL,
    original_label text NOT NULL,
    label_path text NOT NULL,
    geometry jsonb,
    v2_label_path text,
    mapping_status text NOT NULL CHECK (mapping_status IN ('direct','safe','review_required')),
    mapping_rule text NOT NULL,
    PRIMARY KEY (event_id,instance_index),
    FOREIGN KEY (taxonomy_version,label_path) REFERENCES taxonomy_labels(version,label_path)
);
CREATE TABLE IF NOT EXISTS sample_state (
    sample_id text PRIMARY KEY REFERENCES samples(sample_id),
    status text NOT NULL CHECK (status IN ('resolved','conflict','no_current')),
    representative_event_id text REFERENCES annotation_versions(event_id),
    training_eligible boolean NOT NULL,
    CHECK ((status='resolved') = (representative_event_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS current_contributors (
    sample_id text NOT NULL REFERENCES sample_state(sample_id),
    event_id text NOT NULL REFERENCES annotation_versions(event_id),
    PRIMARY KEY (sample_id,event_id)
);
CREATE TABLE IF NOT EXISTS quality_flags (
    sample_id text NOT NULL REFERENCES samples(sample_id),
    reason_code text NOT NULL,
    detail jsonb NOT NULL,
    PRIMARY KEY (sample_id,reason_code)
);
CREATE TABLE IF NOT EXISTS coverage_targets (
    label_path text PRIMARY KEY,
    taxonomy_version integer NOT NULL DEFAULT 2 CHECK (taxonomy_version=2),
    target_samples integer NOT NULL CHECK (target_samples >= 0),
    source_file_id text NOT NULL,
    row_number bigint NOT NULL,
    FOREIGN KEY (taxonomy_version,label_path) REFERENCES taxonomy_labels(version,label_path),
    FOREIGN KEY (source_file_id,row_number) REFERENCES source_records(source_file_id,row_number)
);
CREATE TABLE IF NOT EXISTS validation_details (
    source_file_id text NOT NULL,
    row_number bigint NOT NULL,
    reason_code text NOT NULL,
    instance_index integer NOT NULL DEFAULT -1,
    detail jsonb NOT NULL,
    PRIMARY KEY (source_file_id,row_number,reason_code,instance_index),
    FOREIGN KEY (source_file_id,row_number,reason_code)
        REFERENCES quarantine(source_file_id,row_number,reason_code)
);
CREATE OR REPLACE VIEW current_coverage AS
SELECT t.label_path,t.target_samples,count(DISTINCT s.sample_id) AS current_samples,
       round(100.0*count(DISTINCT s.sample_id)/nullif(t.target_samples,0),2) AS percentage
FROM coverage_targets t
LEFT JOIN instances i ON i.v2_label_path=t.label_path
LEFT JOIN sample_state s ON s.representative_event_id=i.event_id AND s.status='resolved'
WHERE NOT EXISTS (SELECT 1 FROM quarantine q
                  WHERE q.source_file_id=t.source_file_id AND q.row_number=t.row_number)
GROUP BY t.label_path,t.target_samples;
