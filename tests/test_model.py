from __future__ import annotations

import json
import unittest
from pathlib import Path

from decks.kanji.model import (
    payload_statistics,
    project_record,
    record_etag,
    validate_payload,
    validate_record,
)


ROOT = Path(__file__).resolve().parents[1]

from tests import load  # noqa: E402


class ProductionContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = load("kanji", "data_japanese.json")

    def test_full_payload_contract_and_counts(self) -> None:
        self.assertEqual(validate_payload(self.payload), [])
        self.assertEqual(
            payload_statistics(self.payload),
            {
                "characters": 3012,
                "readings": 4862,
                "examples": 11910,
                "regular_examples": 11708,
                "variants": 391,
                "exception_readings": 193,
                "exception_examples": 202,
                "tags": {
                    "s1": 80,
                    "s2": 160,
                    "s3": 200,
                    "s4": 202,
                    "s5": 193,
                    "s6": 191,
                    "j": 1115,
                    "h": 871,
                },
            },
        )

    def test_projection_keeps_native_record_exact(self) -> None:
        for character in ("亜", "衣", "餌", "𠮟"):
            record = self.payload[character]
            projected = project_record(character, record, edited=False)
            self.assertEqual(projected["record"], record)
            self.assertEqual(projected["record_etag"], record_etag(record))

    def test_empty_main_korean_is_valid_when_variant_has_value(self) -> None:
        self.assertEqual(validate_record("亜", self.payload["亜"]), [])
        self.assertEqual(self.payload["亜"]["korean"]["본"], [])
        self.assertTrue(self.payload["亜"]["korean"]["亞"])

    def test_exception_is_not_a_reading_example_bucket(self) -> None:
        record = self.payload["衣"]
        self.assertEqual(
            record["except"],
            {"ゆかた": [{"w": "浴衣(ゆかた)", "ko": "유카타, 여름용 홑옷 기모노"}]},
        )
        self.assertNotIn("ゆかた", record["readings"])

    def test_exception_key_is_the_whole_word_reading(self) -> None:
        """예외 키는 한자 하나가 지는 조각이 아니라 단어 전체의 요미가나다."""
        self.assertEqual(
            self.payload["生"]["except"]["やよい"],
            [{"w": "弥生(やよい)", "ko": "음력 3월"}],
        )
        self.assertNotIn("よい", self.payload["生"]["except"])

    def test_legacy_only_field_is_rejected(self) -> None:
        record = json.loads(json.dumps(self.payload["祈"], ensure_ascii=False))
        record["strokes"] = 8
        errors = validate_record("祈", record)
        self.assertTrue(any("현재 스키마에 없는 필드" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
