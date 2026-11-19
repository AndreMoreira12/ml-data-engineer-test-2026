"""Version-specific taxonomy evidence and conservative label normalization."""

from datetime import date

import yaml


def parse_taxonomy(text):
    """Flatten leaf labels while preserving version-specific meaning metadata."""
    try:
        tree = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError("INVALID_TAXONOMY_DOCUMENT") from exc
    if not isinstance(tree, dict) or type(tree.get("version")) is not int or tree["version"] <= 0:
        raise ValueError("INVALID_TAXONOMY_DOCUMENT")
    released = tree.get("released")
    if type(released) is not date:
        raise ValueError("INVALID_TAXONOMY_DOCUMENT")
    labels = []
    seen = set()

    def walk(nodes, prefix=""):
        if not isinstance(nodes, list) or not nodes:
            raise ValueError("INVALID_TAXONOMY_DOCUMENT")
        for node in nodes:
            if not isinstance(node, dict):
                raise ValueError("INVALID_TAXONOMY_DOCUMENT")
            name = node.get("name")
            if not isinstance(name, str) or not name.strip() or name != name.strip() or '/' in name:
                raise ValueError("INVALID_TAXONOMY_DOCUMENT")
            path = prefix + name
            if "children" in node:
                if "geometry" in node:
                    raise ValueError("INVALID_TAXONOMY_DOCUMENT")
                walk(node["children"], path + "/")
                continue
            geometry = node.get("geometry")
            deprecated = node.get("deprecated", False)
            if (geometry not in ("none", "point", "polygon") or type(deprecated) is not bool
                    or path.casefold() in seen
                    or any(node.get(key) is not None and not isinstance(node[key], str)
                           for key in ("description", "replaces"))):
                raise ValueError("INVALID_TAXONOMY_DOCUMENT")
            seen.add(path.casefold())
            labels.append((path, geometry, node.get("description"), deprecated, node.get("replaces")))

    walk(tree.get("labels"))
    return tree["version"], released, sorted(labels)


def ingest_taxonomy(connection, path):
    from pipeline.ingest import read_source

    file_id, raw = read_source(path)
    text = raw.decode("utf-8")
    reason = None
    try:
        version, released, labels = parse_taxonomy(text)
    except ValueError as exc:
        reason = str(exc)
    inserted = 0
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("""INSERT INTO source_files VALUES (%s,%s,'yaml',%s)
                          ON CONFLICT DO NOTHING""", (file_id, path.name, raw))
        cursor.execute("""INSERT INTO source_records (source_file_id,row_number,raw_text)
                          VALUES (%s,1,%s) ON CONFLICT DO NOTHING""", (file_id, text))
        if reason is None:
            cursor.execute("SELECT released,source_file_id FROM taxonomy_versions WHERE version=%s", (version,))
            existing = cursor.fetchone()
            if existing:
                cursor.execute("""SELECT label_path,geometry_type,description,deprecated,replaces
                                  FROM taxonomy_labels WHERE version=%s ORDER BY label_path""", (version,))
                if existing[0] != released or cursor.fetchall() != labels:
                    reason = "CONFLICTING_TAXONOMY_VERSION"
                    cursor.execute("""INSERT INTO quarantine VALUES (%s,1,%s)
                                      ON CONFLICT DO NOTHING""", (existing[1], reason))
            else:
                cursor.execute("INSERT INTO taxonomy_versions VALUES (%s,%s,%s,1)", (version, released, file_id))
                for label in labels:
                    cursor.execute("INSERT INTO taxonomy_labels VALUES (%s,%s,%s,%s,%s,%s)", (version, *label))
                inserted = len(labels)
        if reason:
            cursor.execute("INSERT INTO quarantine VALUES (%s,1,%s) ON CONFLICT DO NOTHING", (file_id, reason))
    return {"new_labels": inserted, "document_failures": [reason] if reason else []}


def known_taxonomies(cursor):
    cursor.execute("""SELECT l.version,l.label_path,l.geometry_type,l.deprecated
                      FROM taxonomy_labels l JOIN taxonomy_versions v USING (version)
                      WHERE NOT EXISTS (SELECT 1 FROM quarantine q
                          WHERE q.source_file_id=v.source_file_id AND q.row_number=v.row_number)""")
    versions = {}
    for version, path, geometry, deprecated in cursor.fetchall():
        versions.setdefault(version, {})[path] = (geometry, deprecated)
    return versions


def normalize_label(label, labels):
    if not isinstance(label, str):
        return None
    key = "/".join(part.strip() for part in label.split("/")).casefold()
    matches = [path for path in labels if path.casefold() == key]
    return matches[0] if len(matches) == 1 else None


def validate_event_labels(payload, taxonomies):
    """One failing instance quarantines the whole event; issues retain positions."""
    issues = []
    normalized = deprecated = 0
    version = payload.get("label_tree_version")
    if type(version) is not int or version not in taxonomies:
        return [{"reason": "UNKNOWN_TAXONOMY_VERSION"}], 0, 0
    instances = payload.get("instances")
    if not isinstance(instances, list) or not instances:
        return [{"reason": "INVALID_INSTANCES"}], 0, 0
    labels = taxonomies[version]
    for index, instance in enumerate(instances):
        if not isinstance(instance, dict):
            issues.append({"reason": "INVALID_INSTANCE", "instance_index": index})
            continue
        original = instance.get("label")
        path = normalize_label(original, labels)
        if path is None:
            issues.append({"reason": "UNKNOWN_LABEL", "instance_index": index})
        else:
            normalized += path != original
            deprecated += labels[path][1]
    return issues, normalized, deprecated
