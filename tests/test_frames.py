import unittest
from datetime import UTC, datetime

from pipeline.frames import frame_reference_reasons, validate_frame


class FrameTests(unittest.TestCase):
    def row(self, **changes):
        row = dict(frame_id="f1", roll_id="r1", machine_id="m1", camera_position="c1",
                   light_type=" vis", captured_at="2026-05-19 08:04:00",
                   height_px="1024", width_px="2448")
        row.update(changes)
        return row

    def test_light_normalization_and_equivalent_timestamps_preserve_input(self):
        for timestamp in ("2026-05-19 08:04:00", "2026-05-19T08:04:00+01:00",
                          "2026-05-19T07:04:00Z"):
            row = self.row(captured_at=timestamp)
            values, reason = validate_frame(row)
            self.assertIsNone(reason)
            self.assertEqual(values[4:6], ("VIS", datetime(2026, 5, 19, 7, 4, tzinfo=UTC)))
            self.assertEqual(row["light_type"], " vis")
        values, reason = validate_frame(self.row(captured_at="1786519117000"))
        self.assertIsNone(reason)
        self.assertEqual(values[5], datetime(2026, 8, 12, 7, 18, 37, tzinfo=UTC))

    def test_missing_or_impossible_dimensions_are_not_inferred(self):
        for dimension in ("", "0", "-1", "1.5", "999999999999"):
            self.assertEqual(validate_frame(self.row(height_px=dimension))[1], "INVALID_FRAME_DIMENSIONS")
        self.assertEqual(validate_frame(self.row(height_px="1920", width_px="1200"))[0][-2:], (1920, 1200))

    def test_bad_light_and_ambiguous_capture(self):
        self.assertEqual(validate_frame(self.row(light_type="UV"))[1], "INVALID_LIGHT_TYPE")
        self.assertEqual(validate_frame(self.row(captured_at="2026-10-25 01:30:00"))[1],
                         "FRAME_AMBIGUOUS_LOCAL_TIME")

    def test_whole_version_reference_failures(self):
        self.assertEqual(frame_reference_reasons({"frame_ids": ["f1", "f2"]}, {"f1", "f2"}), [])
        self.assertEqual(frame_reference_reasons({"frame_ids": ["f1", "f2", "missing"]}, {"f1", "f2"}),
                         ["INVALID_FRAME_COUNT", "UNKNOWN_OR_INVALID_FRAME"])
        self.assertEqual(frame_reference_reasons({"frame_ids": ["f1", "f1"]}, {"f1"}),
                         ["DUPLICATE_FRAME_REFERENCE"])
        for ids in (None, "f1", [None], [[]]):
            self.assertEqual(frame_reference_reasons({"frame_ids": ids}, {"f1"}), ["INVALID_FRAME_IDS"])
