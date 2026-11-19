import unittest

from pipeline.samples import conflicting_sample_ids, sample_identity_reason


class SampleTests(unittest.TestCase):
    def test_order_and_identical_repeats_do_not_change_membership(self):
        a = {"sample_id": "s1", "frame_ids": ["f1", "f2"]}
        b = {"sample_id": "s1", "frame_ids": ["f2", "f1"]}
        self.assertEqual(conflicting_sample_ids([a, a, b]), set())

    def test_conflict_is_independent_of_file_order_or_missing_reference(self):
        a = {"sample_id": "s1", "frame_ids": ["f1"]}
        b = {"sample_id": "s1", "frame_ids": ["f1", "missing"]}
        self.assertEqual(conflicting_sample_ids([a, b]), {"s1"})
        self.assertEqual(conflicting_sample_ids([b, a]), {"s1"})

    def test_malformed_declarations_do_not_crash_or_invent_membership(self):
        valid = {"sample_id": "s1", "frame_ids": ["f1"]}
        for ids in (None, [], [[]], [None], ["f1", "f1"]):
            self.assertEqual(conflicting_sample_ids([valid, {"sample_id": "s1", "frame_ids": ids}]), set())
        for sample in (None, [], "", " s1"):
            self.assertEqual(sample_identity_reason({"sample_id": sample}), "INVALID_SAMPLE_ID")
