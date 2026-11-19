import unittest
from pathlib import Path

from pipeline.taxonomy import normalize_label, parse_taxonomy, validate_event_labels


class TaxonomyTests(unittest.TestCase):
    def taxonomies(self):
        result = {}
        for number in (1, 2):
            version, _, rows = parse_taxonomy(Path(f"data/label_tree_v{number}.yaml").read_text(encoding="utf-8"))
            result[version] = {path: (geometry, deprecated) for path, geometry, _, deprecated, _ in rows}
        return result

    def test_version_meaning_and_replacement_are_preserved(self):
        _, _, one = parse_taxonomy(Path("data/label_tree_v1.yaml").read_text())
        _, _, two = parse_taxonomy(Path("data/label_tree_v2.yaml").read_text())
        a, b = {r[0]: r for r in one}, {r[0]: r for r in two}
        self.assertNotEqual(a["Defect/Stain/Oil"][2], b["Defect/Stain/Oil"][2])
        self.assertEqual(b["Defect/Yarn/Thick place"][4], "Defect/Slub")
        self.assertIn("Defect/Knot", a)
        self.assertNotIn("Defect/Knot", b)

    def test_formatting_only_normalization(self):
        labels = self.taxonomies()[1]
        self.assertEqual(normalize_label(" Defect / Slub ", labels), "Defect/Slub")
        self.assertEqual(normalize_label("normal", labels), "Normal")
        self.assertIsNone(normalize_label("Defect/Weft/Brokn pick", labels))
        self.assertIsNone(normalize_label("Defect/Holes", labels))

    def test_invalid_instance_quarantines_version_and_keeps_position(self):
        payload = {"label_tree_version": 1, "instances": [
            {"label": "Normal"}, {"label": "Defect/Stain/Grease"}, {"label": "unknown"}]}
        issues, _, _ = validate_event_labels(payload, self.taxonomies())
        self.assertEqual(issues, [{"reason": "UNKNOWN_LABEL", "instance_index": 1},
                                  {"reason": "UNKNOWN_LABEL", "instance_index": 2}])

    def test_deprecated_is_valid_history_not_automatic_migration(self):
        payload = {"label_tree_version": 1, "instances": [{"label": "Defect/Knot"}]}
        self.assertEqual(validate_event_labels(payload, self.taxonomies()), ([], 0, 1))
        payload["label_tree_version"] = 2
        self.assertEqual(validate_event_labels(payload, self.taxonomies())[0][0]["reason"], "UNKNOWN_LABEL")
        payload["label_tree_version"] = True
        self.assertEqual(validate_event_labels(payload, self.taxonomies())[0], [{"reason": "UNKNOWN_TAXONOMY_VERSION"}])

    def test_invalid_taxonomy_documents(self):
        for text in ("[]", "version: true", "{broken", "version: 1\nreleased: 2026-01-01\nlabels: []"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "INVALID_TAXONOMY_DOCUMENT"):
                parse_taxonomy(text)
