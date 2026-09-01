from __future__ import annotations

import json
import unittest
from pathlib import Path

from shared.furigana import parse_annotated, parse_annotation, reading_kind


ROOT = Path(__file__).resolve().parents[1]

from tests import load  # noqa: E402


class AnnotationTest(unittest.TestCase):
    def test_half_width_annotation_is_generated(self) -> None:
        parsed = parse_annotation("祈る", "祈(いの)る")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["word"], "祈る")
        self.assertEqual(parsed["all"], "いのる")
        self.assertEqual(parsed["segments"][0]["source"], "generated")

    def test_full_width_annotation_remains_in_source_word(self) -> None:
        parsed = parse_annotation("浴衣（ゆかた）", "浴衣（ゆかた）")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["word"], "浴衣（ゆかた）")
        self.assertEqual(parsed["segments"][0]["source"], "printed")

    def test_supplementary_plane_character(self) -> None:
        parsed = parse_annotation("𠮟る", "𠮟(しか)る")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["word"], "𠮟る")

    def test_reading_group_rule(self) -> None:
        self.assertEqual(reading_kind("キ"), "on")
        self.assertEqual(reading_kind("いのり"), "kun")
        self.assertEqual(reading_kind("いのー"), "verb")
        self.assertIsNone(reading_kind("いーの"))

    def test_every_production_annotation_reconstructs_w(self) -> None:
        payload = load("kanji", "data_japanese.json")
        failures = []
        count = 0
        for character, record in payload.items():
            for raw_key, examples in list(record["readings"].items()) + list(record["except"].items()):
                for example in examples:
                    count += 1
                    if parse_annotated(example["w"]) is None:
                        failures.append((character, raw_key, example))
        self.assertEqual(count, 11_910)
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
