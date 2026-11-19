import unittest

from pipeline.history import resolve_current, validate_history
from pipeline.migration import migrate_label


def event(event_id, parent=None, author='A01', pass_='first', status='committed', label='Normal', sample='s1'):
    return dict(event_id=event_id, sample_id=sample, frame_ids=['f1'], annotator_id=author,
                session_id='session', **{'pass': pass_}, status=status, supersedes_event_id=parent,
                saved_at='2026-07-10T12:00:00Z', exporter_version='2.0', label_tree_version=2,
                instances=[dict(label=label, geometry=None)])


class HistoryTests(unittest.TestCase):
    def test_independent_committed_review_of_draft_first_pass(self):
        events = {'a': event('a', status='draft'), 'b': event('b', 'a', 'A02', 'second')}
        reasons, baselines = validate_history(events)
        self.assertEqual(reasons, {'a': set(), 'b': set()})
        self.assertEqual(baselines, {'b': 'a'})
        self.assertEqual(resolve_current(events, set(events))['s1']['representative'], 'b')

    def test_self_review_and_second_pass_without_baseline(self):
        events = {'a': event('a'), 'b': event('b', 'a', 'A01', 'second'), 'c': event('c', pass_='second')}
        reasons, _ = validate_history(events)
        self.assertIn('SELF_REVIEW', reasons['b'])
        self.assertIn('NO_FIRST_PASS_ANCESTOR', reasons['c'])

    def test_missing_conflicted_cross_sample_parents(self):
        a = event('a', 'missing')
        self.assertIn('MISSING_PARENT', validate_history({'a': a})[0]['a'])
        self.assertIn('CONFLICTED_ANCESTOR', validate_history({'a': a}, {'missing'})[0]['a'])
        self.assertIn('CROSS_SAMPLE_PARENT', validate_history({'a': a, 'missing': event('missing', sample='other')})[0]['a'])

    def test_cycle_including_descendant_and_reversed_chronology(self):
        events = {'a': event('a', 'b'), 'b': event('b', 'a'), 'c': event('c', 'a')}
        self.assertTrue(all('CYCLIC_HISTORY' in reasons for reasons in validate_history(events)[0].values()))
        events = {'a': event('a'), 'b': event('b', 'a')}
        events['a']['saved_at'] = '2026-07-11T12:00:00Z'
        self.assertIn('PARENT_AFTER_CHILD', validate_history(events)[0]['b'])

    def test_draft_or_invalid_later_save_does_not_erase_committed_version(self):
        events = {'a': event('a'), 'b': event('b', 'a', status='draft')}
        self.assertEqual(resolve_current(events, {'a','b'})['s1']['representative'], 'a')
        events['b']['status'] = 'committed'
        self.assertEqual(resolve_current(events, {'a'})['s1']['representative'], 'a')

    def test_disagreeing_branches_and_agreeing_roots(self):
        events = {'a': event('a'), 'b': event('b', 'a'), 'c': event('c', 'a', label='Defect/Hole')}
        self.assertEqual(resolve_current(events, set(events))['s1']['status'], 'conflict')
        events = {'a': event('a'), 'b': event('b')}
        self.assertEqual(resolve_current(events, set(events))['s1']['contributors'], ['a','b'])

    def test_deep_committed_descendant_supersedes_ancestor_through_draft(self):
        events = {'a': event('a'), 'b': event('b', 'a', status='draft'), 'c': event('c', 'b')}
        self.assertEqual(resolve_current(events, set(events))['s1']['contributors'], ['c'])

    def test_safe_migration_uses_meaning_rules(self):
        self.assertEqual(migrate_label(1, 'Defect/Slub')[:2], ('Defect/Yarn/Thick place','safe'))
        self.assertEqual(migrate_label(1, 'Defect/Stain/Oil')[:2], (None,'review_required'))
        self.assertEqual(migrate_label(1, 'Defect/Knot')[:2], (None,'review_required'))
        self.assertEqual(migrate_label(2, 'Defect/Stain/Oil')[:2], ('Defect/Stain/Oil','direct'))
