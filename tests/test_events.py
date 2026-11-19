import unittest

from pipeline.events import canonical_event, event_identity_reason
from pipeline.ingest import parse_event


class EventIdentityTests(unittest.TestCase):
    def test_json_formatting_and_key_order_do_not_create_variants(self):
        a = parse_event('{"event_id":"e1", "nested":{"a":1,"b":2}}')[0]
        b = parse_event('{ "nested": {"b": 2, "a": 1}, "event_id": "e1" }')[0]
        self.assertEqual(canonical_event(a), canonical_event(b))

    def test_array_order_types_and_source_strings_are_significant(self):
        baseline = canonical_event({"event_id": "e1", "value": [1, 2]})
        for value in ([2, 1], [True, 2], [1.0, 2], ["1", 2]):
            self.assertNotEqual(canonical_event({"event_id": "e1", "value": value}), baseline)
        self.assertNotEqual(canonical_event({"label": "Normal"}), canonical_event({"label": "normal"}))

    def test_missing_and_malformed_ids(self):
        for value in (None, [], True, "", " e1"):
            self.assertEqual(event_identity_reason({"event_id": value}), "INVALID_EVENT_ID")

    def test_ambiguous_json_cannot_silently_lose_evidence(self):
        for text in ('{"event_id":"a","event_id":"b"}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'):
            self.assertEqual(parse_event(text), (None, "INVALID_JSON"))
