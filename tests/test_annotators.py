import unittest
from datetime import UTC, date, datetime

from pipeline.annotators import active_date_reason, annotator_reason, validate_annotator


class AnnotatorTests(unittest.TestCase):
    def test_inclusive_boundaries_use_lisbon_day(self):
        start, end = date(2026, 7, 15), date(2026, 7, 15)
        for value, expected in (
            ("2026-07-14T22:59:59+00:00", "ANNOTATOR_OUTSIDE_ACTIVE_DATES"),
            ("2026-07-14T23:00:00+00:00", None),
            ("2026-07-15T16:00:00+00:00", None),
            ("2026-07-15T22:59:59+00:00", None),
            ("2026-07-15T23:00:00+00:00", "ANNOTATOR_OUTSIDE_ACTIVE_DATES"),
        ):
            with self.subTest(value=value):
                self.assertEqual(active_date_reason(datetime.fromisoformat(value), start, end), expected)
        self.assertIsNone(active_date_reason(datetime(2030, 1, 1, tzinfo=UTC), start, None))

    def row(self, **changes):
        return dict(annotator_id="A09", display_name="Inês Carvalho", site="Porto",
                    active_from="2026-05-18", active_to="", **changes)

    def test_unicode_and_open_ended_dates_are_preserved(self):
        values, reason = validate_annotator(self.row())
        self.assertIsNone(reason)
        self.assertEqual(values[1], "Inês Carvalho")
        self.assertIsNone(values[4])

    def test_invalid_dates_or_identity_quarantine_entire_row(self):
        for field, value, expected in (
            ("active_to", "2026-05-17", "INVALID_ANNOTATOR_DATES"),
            ("active_from", "bad", "INVALID_ANNOTATOR_DATES"),
            ("annotator_id", " A09", "INVALID_ANNOTATOR_IDENTITY"),
            ("display_name", "", "INVALID_ANNOTATOR_IDENTITY"),
        ):
            row = self.row()
            row[field] = value
            self.assertEqual(validate_annotator(row), (None, expected))

    def test_wrong_column_count(self):
        row = self.row()
        row[None] = ["extra"]
        self.assertEqual(validate_annotator(row)[1], "INVALID_ANNOTATOR_ROW")
        del row[None]
        row["site"] = None
        self.assertEqual(validate_annotator(row)[1], "INVALID_ANNOTATOR_ROW")

    def test_unknown_and_malformed_event_identity(self):
        for value in (None, [], 12, ""):
            self.assertEqual(annotator_reason({"annotator_id": value}, {"A01"}),
                             "INVALID_ANNOTATOR_ID")
        self.assertEqual(annotator_reason({"annotator_id": "A12"}, {"A01"}), "UNKNOWN_ANNOTATOR")
        self.assertIsNone(annotator_reason({"annotator_id": "A01"}, {"A01"}))


if __name__ == "__main__":
    unittest.main()
