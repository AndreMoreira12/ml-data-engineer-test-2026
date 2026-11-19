"""One event validation entry point shared by reconciliation and domain loading."""

from pipeline.annotators import active_date_reason, annotator_reason
from pipeline.events import event_identity_reason
from pipeline.frames import frame_reference_reasons
from pipeline.geometry import validate_event_geometry
from pipeline.history import core_event_reasons
from pipeline.samples import sample_identity_reason
from pipeline.taxonomy import validate_event_labels
from pipeline.timestamps import TimestampError, normalize_saved_at


def event_issues(payload, people, frames, taxonomies):
    issues = []
    for reason in (event_identity_reason(payload), sample_identity_reason(payload), *core_event_reasons(payload)):
        if reason:
            issues.append({"reason": reason})
    saved = None
    try:
        saved = normalize_saved_at(payload.get("saved_at"), payload.get("exporter_version"))
    except TimestampError as exc:
        issues.append({"reason": str(exc)})
    reason = annotator_reason(payload, people)
    if reason is None and saved is not None:
        reason = active_date_reason(saved, *people[payload["annotator_id"]])
    if reason:
        issues.append({"reason": reason})
    for reason in frame_reference_reasons(payload, frames):
        issues.append({"reason": reason})
    ids = payload.get("frame_ids")
    if saved is not None and isinstance(ids, list):
        if any(isinstance(fid, str) and fid in frames and frames[fid]["captured_at"] > saved for fid in ids):
            issues.append({"reason": "SAVE_BEFORE_CAPTURE"})
    label_issues, _, _ = validate_event_labels(payload, taxonomies)
    issues.extend(label_issues)
    issues.extend(validate_event_geometry(payload, taxonomies, frames))
    return issues
