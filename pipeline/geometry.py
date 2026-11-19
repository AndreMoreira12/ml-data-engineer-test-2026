"""Validate original [row, column] coordinates; never clip, swap or rescale."""

import math

from pipeline.taxonomy import normalize_label


def _orientation(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _intersects(a, b, c, d):
    def on_segment(p, q, r):
        return (min(p[0], r[0]) <= q[0] <= max(p[0], r[0])
                and min(p[1], r[1]) <= q[1] <= max(p[1], r[1]))
    x, y, z, w = _orientation(a, b, c), _orientation(a, b, d), _orientation(c, d, a), _orientation(c, d, b)
    if ((x > 0 and y < 0) or (x < 0 and y > 0)) and ((z > 0 and w < 0) or (z < 0 and w > 0)):
        return True
    return ((x == 0 and on_segment(a, c, b)) or (y == 0 and on_segment(a, d, b))
            or (z == 0 and on_segment(c, a, d)) or (w == 0 and on_segment(c, b, d)))


def geometry_reasons(instance, expected_type, dimensions):
    if "geometry" not in instance:
        return ["MISSING_GEOMETRY"]
    shape = instance["geometry"]
    if shape is None:
        return [] if expected_type in (None, "none") else ["GEOMETRY_TYPE_MISMATCH"]
    if not isinstance(shape, dict) or shape.get("type") not in ("point", "polygon"):
        return ["INVALID_GEOMETRY"]
    reasons = []
    kind = shape["type"]
    if expected_type is not None and kind != expected_type:
        reasons.append("GEOMETRY_TYPE_MISMATCH")
    coordinates = shape.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        return reasons + ["INVALID_COORDINATES"]
    for pair in coordinates:
        if (not isinstance(pair, list) or len(pair) != 2
                or any(type(v) not in (int, float) for v in pair)):
            return reasons + ["INVALID_COORDINATES"]
        try:
            if not all(math.isfinite(v) for v in pair):
                return reasons + ["INVALID_COORDINATES"]
        except OverflowError:
            return reasons + ["INVALID_COORDINATES"]
    if any(row < 0 or column < 0 or any(row >= h or column >= w for h, w in dimensions)
           for row, column in coordinates):
        reasons.append("GEOMETRY_OUT_OF_BOUNDS")
    if kind == "point":
        if len(coordinates) != 1:
            reasons.append("INVALID_POINT")
        return reasons
    # An optional final copy of the first vertex is accepted, not written back.
    vertices = coordinates[:-1] if coordinates[-1] == coordinates[0] else coordinates
    if len(vertices) < 3 or len({tuple(p) for p in vertices}) != len(vertices):
        return reasons + ["INVALID_POLYGON"]
    origin = vertices[0]
    area = sum(_orientation(origin, vertices[i], vertices[i + 1]) for i in range(1, len(vertices) - 1))
    try:
        if area == 0 or not math.isfinite(area):
            return reasons + ["INVALID_POLYGON"]
    except OverflowError:
        return reasons + ["INVALID_POLYGON"]
    count = len(vertices)
    for i in range(count):
        for j in range(i + 1, count):
            if j == i + 1 or (i == 0 and j == count - 1):
                continue
            if _intersects(vertices[i], vertices[(i + 1) % count], vertices[j], vertices[(j + 1) % count]):
                return reasons + ["INVALID_POLYGON"]
    return reasons


def validate_event_geometry(payload, taxonomies, frames):
    """Report instance positions; caller quarantines the entire version."""
    issues = []
    ids = payload.get("frame_ids")
    selected = []
    if isinstance(ids, list) and all(isinstance(v, str) for v in ids):
        selected = [frames[v] for v in ids if v in frames]
        if len(ids) == 2 and len(selected) == 2:
            a, b = selected
            if (any(a[k] != b[k] for k in ("roll_id", "machine_id", "camera_position", "height_px", "width_px"))
                    or a["light_type"] == b["light_type"]):
                issues.append({"reason": "INCOMPATIBLE_FRAME_PAIR"})
    dimensions = [(f["height_px"], f["width_px"]) for f in selected]
    version = payload.get("label_tree_version")
    labels = taxonomies.get(version, {}) if type(version) is int else {}
    instances = payload.get("instances")
    if not isinstance(instances, list):
        return issues
    normal = False
    for index, instance in enumerate(instances):
        if not isinstance(instance, dict):
            continue  # Already reported by label validation.
        label = normalize_label(instance.get("label"), labels)
        normal |= label == "Normal"
        expected = labels[label][0] if label is not None else None
        for reason in geometry_reasons(instance, expected, dimensions):
            issues.append({"reason": reason, "instance_index": index})
    if normal and len(instances) != 1:
        issues.append({"reason": "NORMAL_WITH_OTHER_INSTANCES"})
    return issues
