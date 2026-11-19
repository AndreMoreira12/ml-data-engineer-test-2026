import unittest
from datetime import UTC, datetime

from pipeline.timestamps import TimestampError, normalize_saved_at


class TimestampTests(unittest.TestCase):
    def test_lisbon_summer_and_winter(self):
        for local, hour in (("2026-05-19 08:04:00", 7), ("2026-01-19 08:04:00", 8)):
            with self.subTest(local=local):
                result = normalize_saved_at(local, "1.4")
                self.assertEqual(result.hour, hour)
                self.assertEqual(result.tzinfo, UTC)

    def test_equivalent_offset_and_millisecond_evidence(self):
        expected = datetime(2026, 8, 12, 7, 18, 37, tzinfo=UTC)
        for value in (1786519117000, "2026-08-12T08:18:37+01:00", "2026-08-12T07:18:37Z"):
            self.assertEqual(normalize_saved_at(value, "2.1"), expected)

    def test_dst_gap_and_overlap_are_quarantined(self):
        for local, reason in (("2026-03-29 01:30:00", "NONEXISTENT_LOCAL_TIME"),
                              ("2026-10-25 01:30:00", "AMBIGUOUS_LOCAL_TIME")):
            with self.subTest(local=local):
                with self.assertRaisesRegex(TimestampError, reason):
                    normalize_saved_at(local, "1.4")

    def test_invalid_or_unexplained_representations(self):
        for value, version, reason in (
            (True, "2.1", "INVALID_SAVED_AT"),
            (1786519117000, "2.0", "INVALID_SAVED_AT"),
            (10**30, "2.1", "INVALID_SAVED_AT"),
            (None, "2.1", "INVALID_SAVED_AT"),
            ("2026-05-19", "2.0", "INVALID_SAVED_AT"),
            ("2026-05-19 08:04:00", "2.0", "MISSING_TIMESTAMP_OFFSET"),
            ("2026-05-19T08:04:00Z", "1.4", "UNEXPECTED_TIMESTAMP_OFFSET"),
            ("2026-05-19T08:04:00Z", "9.9", "UNKNOWN_TIMESTAMP_EXPORTER"),
        ):
            with self.subTest(value=value, version=version):
                with self.assertRaisesRegex(TimestampError, reason):
                    normalize_saved_at(value, version)


if __name__ == "__main__":
    unittest.main()
