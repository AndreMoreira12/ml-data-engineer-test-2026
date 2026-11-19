"""Load the small version-2 coverage target reference file, preserving evidence."""

import csv
import io

from pipeline.taxonomy import known_taxonomies, normalize_label


def ingest_coverage(connection, path):
    from pipeline.ingest import read_source

    file_id, raw = read_source(path)
    lines = raw.decode("utf-8").splitlines(keepends=True)
    reader = csv.DictReader(io.StringIO(''.join(lines), newline=''))
    if reader.fieldnames != ["label_path", "target_samples"]:
        raise ValueError("Unexpected coverage target header")
    inserted = failed = rows = 0
    previous = reader.line_num
    with connection.transaction(), connection.cursor() as cursor:
        labels = known_taxonomies(cursor).get(2, {})
        cursor.execute("INSERT INTO source_files VALUES (%s,%s,'csv',%s) ON CONFLICT DO NOTHING", (file_id, path.name, raw))
        for number, row in enumerate(reader, 1):
            rows += 1
            text = ''.join(lines[previous:reader.line_num])
            previous = reader.line_num
            cursor.execute("""INSERT INTO source_records (source_file_id,row_number,raw_text)
                              VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""", (file_id, number, text))
            reason = None
            label = normalize_label(row.get('label_path'), labels)
            target = row.get('target_samples')
            if (set(row) != {'label_path', 'target_samples'} or label is None
                    or not isinstance(target, str) or not target.isascii() or not target.isdigit()
                    or len(target) > 10 or int(target) > 2147483647):
                reason = 'INVALID_COVERAGE_TARGET'
            else:
                target = int(target)
                cursor.execute("SELECT target_samples,source_file_id,row_number FROM coverage_targets WHERE label_path=%s", (label,))
                existing = cursor.fetchone()
                if existing and existing[0] != target:
                    reason = 'CONFLICTING_COVERAGE_TARGET'
                    cursor.execute('INSERT INTO quarantine VALUES (%s,%s,%s) ON CONFLICT DO NOTHING', (*existing[1:], reason))
                elif existing is None:
                    cursor.execute('INSERT INTO coverage_targets VALUES (%s,2,%s,%s,%s)', (label, target, file_id, number))
                    inserted += 1
            if reason:
                failed += 1
                cursor.execute('INSERT INTO quarantine VALUES (%s,%s,%s) ON CONFLICT DO NOTHING', (file_id, number, reason))
    return {'input_rows': rows, 'new_targets': inserted, 'failed_rows': failed}
