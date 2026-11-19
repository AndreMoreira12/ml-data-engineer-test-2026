import unittest

from pipeline.splitting import split_for_roll


class RollSplitTests(unittest.TestCase):
    def test_existing_roll_assignments_survive_new_rolls_and_reordering(self):
        original = ['R-2026-0002', 'R-2026-0003', 'R-2026-0004']
        before = {roll: split_for_roll(roll) for roll in original}
        after = {roll: split_for_roll(roll) for roll in ['NEW', *reversed(original)]}
        self.assertEqual(before, {roll: after[roll] for roll in original})

    def test_same_roll_keeps_different_samples_and_paired_frames_together(self):
        samples = [('sample-a', 'VIS', 'roll-a'), ('sample-a', 'IR', 'roll-a'),
                   ('sample-b', 'VIS', 'roll-a')]
        self.assertEqual(len({split_for_roll(roll) for _, _, roll in samples}), 1)

    def test_missing_roll_cannot_silently_receive_a_split(self):
        for roll in (None, '', ' '):
            with self.subTest(roll=roll), self.assertRaises(ValueError):
                split_for_roll(roll)
