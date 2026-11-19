"""Timestamp rules; conversion never modifies the original source payload."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


class TimestampError(ValueError):
    """A timestamp cannot be interpreted without inventing evidence."""


def normalize_saved_at(value, exporter_version: str) -> datetime:
    """Return aware UTC; observed exporter 2.1 integers are Unix milliseconds."""
    if exporter_version not in ("1.4", "2.0", "2.1"):
        raise TimestampError("UNKNOWN_TIMESTAMP_EXPORTER")
    if type(value) is int and exporter_version == "2.1":
        try:
            return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=value)
        except OverflowError as exc:
            raise TimestampError("INVALID_SAVED_AT") from exc
    if not isinstance(value, str) or not value or "T" not in value and " " not in value:
        raise TimestampError("INVALID_SAVED_AT")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise TimestampError("INVALID_SAVED_AT") from exc
    if exporter_version != "1.4":
        if parsed.tzinfo is None:
            raise TimestampError("MISSING_TIMESTAMP_OFFSET")
        try:
            return parsed.astimezone(UTC)
        except (OverflowError, ValueError) as exc:
            raise TimestampError("INVALID_SAVED_AT") from exc
    if parsed.tzinfo is not None:
        raise TimestampError("UNEXPECTED_TIMESTAMP_OFFSET")
    local_zone = ZoneInfo("Europe/Lisbon")
    # Round trips distinguish real local times from the spring clock gap.
    candidates = set()
    for fold in (0, 1):
        utc = parsed.replace(tzinfo=local_zone, fold=fold).astimezone(UTC)
        if utc.astimezone(local_zone).replace(tzinfo=None) == parsed:
            candidates.add(utc)
    if not candidates:
        raise TimestampError("NONEXISTENT_LOCAL_TIME")
    if len(candidates) > 1:
        raise TimestampError("AMBIGUOUS_LOCAL_TIME")
    return candidates.pop()
