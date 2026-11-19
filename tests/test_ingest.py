import unittest

from pipeline.ingest import parse_event


class ParseEventTests(unittest.TestCase):
    def test_object_is_parsed_without_domain_validation(self):
        self.assertEqual(parse_event('{"event_id": "evt_1"}'), ({"event_id": "evt_1"}, None))
        self.assertEqual(parse_event('{}'), ({}, None))

    def test_malformed_or_blank_line_has_parse_reason(self):
        for raw_text in ('{broken', '', '\n'):
            with self.subTest(raw_text=raw_text):
                self.assertEqual(parse_event(raw_text), (None, "INVALID_JSON"))

    def test_valid_json_must_be_an_object(self):
        for raw_text in ('[]', 'null', '42', '"text"', 'true'):
            with self.subTest(raw_text=raw_text):
                self.assertEqual(parse_event(raw_text), (None, "EVENT_NOT_OBJECT"))


if __name__ == "__main__":
    unittest.main()
