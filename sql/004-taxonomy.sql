CREATE TABLE IF NOT EXISTS taxonomy_versions (
    version integer PRIMARY KEY CHECK (version > 0),
    released date NOT NULL,
    source_file_id text NOT NULL,
    row_number bigint NOT NULL DEFAULT 1 CHECK (row_number = 1),
    FOREIGN KEY (source_file_id,row_number)
        REFERENCES source_records (source_file_id,row_number)
);

CREATE TABLE IF NOT EXISTS taxonomy_labels (
    version integer NOT NULL REFERENCES taxonomy_versions(version),
    label_path text NOT NULL CHECK (label_path <> ''),
    geometry_type text NOT NULL CHECK (geometry_type IN ('none','point','polygon')),
    description text,
    deprecated boolean NOT NULL,
    replaces text,
    PRIMARY KEY (version,label_path)
);
