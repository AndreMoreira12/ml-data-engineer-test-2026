"""Small, explicit history and current-state rules; no timestamp winner."""

import json
from collections import defaultdict

from pipeline.timestamps import TimestampError, normalize_saved_at


def core_event_reasons(event):
    reasons = []
    for field in ("session_id",):
        value = event.get(field)
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            reasons.append("INVALID_" + field.upper())
    if event.get("pass") not in ("first", "second"):
        reasons.append("INVALID_PASS")
    if event.get("status") not in ("draft", "committed"):
        reasons.append("INVALID_STATUS")
    if "supersedes_event_id" not in event:
        reasons.append("MISSING_PARENT_FIELD")
    else:
        parent = event["supersedes_event_id"]
        if parent is not None and (not isinstance(parent, str) or not parent.strip() or parent != parent.strip()):
            reasons.append("INVALID_PARENT_ID")
    return reasons


def validate_history(events, conflicting_ids=()):
    """Inspect unconflicted evidence, even when an ancestor's annotation is invalid.

    An ancestor with invalid geometry can still identify a first-pass author.
    A missing/conflicted parent, cycle or cross-sample chain cannot establish it.
    """
    conflicts = set(conflicting_ids)
    reasons = defaultdict(set)
    baselines = {}
    for event_id, event in events.items():
        reasons[event_id].update(core_event_reasons(event))
        seen = {event_id}
        current = event
        first = None
        while True:
            parent_id = current.get("supersedes_event_id")
            if parent_id is None:
                break
            if not isinstance(parent_id, str):
                reasons[event_id].add("INVALID_ANCESTRY")
                break
            if parent_id in seen:
                reasons[event_id].add("CYCLIC_HISTORY")
                break
            seen.add(parent_id)
            if parent_id in conflicts:
                reasons[event_id].add("CONFLICTED_ANCESTOR")
                break
            parent = events.get(parent_id)
            if parent is None:
                reasons[event_id].add("MISSING_PARENT")
                break
            if parent.get("sample_id") != event.get("sample_id"):
                reasons[event_id].add("CROSS_SAMPLE_PARENT")
                break
            if core_event_reasons(parent):
                reasons[event_id].add("INVALID_ANCESTRY")
            try:
                parent_time = normalize_saved_at(parent.get("saved_at"), parent.get("exporter_version"))
                child_time = normalize_saved_at(current.get("saved_at"), current.get("exporter_version"))
                if parent_time > child_time:
                    reasons[event_id].add("PARENT_AFTER_CHILD")
            except TimestampError:
                reasons[event_id].add("INVALID_ANCESTRY_TIME")
            if first is None and parent.get("pass") == "first":
                first = parent_id
            current = parent
        if event.get("pass") == "second":
            if first is None:
                reasons[event_id].add("NO_FIRST_PASS_ANCESTOR")
            elif not isinstance(events[first].get("annotator_id"), str):
                reasons[event_id].add("INVALID_REVIEW_BASELINE")
            elif events[first]["annotator_id"] == event.get("annotator_id"):
                reasons[event_id].add("SELF_REVIEW")
            else:
                baselines[event_id] = first
    return dict(reasons), baselines


def annotation_signature(event):
    """Exact geometry comparison; instance/frame ordering is irrelevant."""
    instances = [json.dumps({"label": i["label"], "geometry": i["geometry"]},
                            sort_keys=True, separators=(",", ":")) for i in event["instances"]]
    return (event["label_tree_version"], tuple(sorted(event["frame_ids"])), tuple(sorted(instances)))


def resolve_current(events, valid_ids):
    """Return committed leaves after removing any committed valid ancestor.

    Drafts/invalid saves do not erase valid committed history. Multiple roots are
    treated like branches. Agreeing leaves retain all authorship, with lexical ID
    selecting only a deterministic display representative, never a content winner.
    """
    by_sample = defaultdict(list)
    for event_id in valid_ids:
        if events[event_id]["status"] == "committed":
            by_sample[events[event_id]["sample_id"]].append(event_id)
    result = {}
    for sample, ids in by_sample.items():
        superseded = set()
        candidates = set(ids)
        for event_id in ids:
            seen = {event_id}
            parent = events[event_id].get("supersedes_event_id")
            while parent in events and parent not in seen:
                seen.add(parent)
                if parent in candidates:
                    superseded.add(parent)
                parent = events[parent].get("supersedes_event_id")
        leaves = sorted(candidates - superseded)
        signatures = {annotation_signature(events[event_id]) for event_id in leaves}
        result[sample] = {"status": "resolved" if len(signatures) == 1 else "conflict",
                          "contributors": leaves if len(signatures) == 1 else [],
                          "representative": leaves[0] if len(signatures) == 1 else None,
                          "leaves": leaves}
    return result
