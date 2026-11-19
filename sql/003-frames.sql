CREATE TABLE IF NOT EXISTS frames (
    frame_id text PRIMARY KEY CHECK (btrim(frame_id) <> ''),
    roll_id text NOT NULL CHECK (btrim(roll_id) <> ''),
    machine_id text NOT NULL CHECK (btrim(machine_id) <> ''),
    camera_position text NOT NULL CHECK (btrim(camera_position) <> ''),
    light_type text NOT NULL CHECK (light_type IN ('VIS', 'IR')),
    captured_at timestamptz NOT NULL,
    height_px integer NOT NULL CHECK (height_px > 0),
    width_px integer NOT NULL CHECK (width_px > 0),
    source_file_id text NOT NULL,
    row_number bigint NOT NULL,
    FOREIGN KEY (source_file_id, row_number)
        REFERENCES source_records (source_file_id, row_number)
);
