# -*- coding: utf-8 -*-
"""용례 정렬 규칙의 계약."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "decks" / "kanji" / "pipeline"))

from tests import load  # noqa: E402

import ordering  # noqa: E402


def example(annotated, ko):
    """후리가나는 표기 안에 실린다.  별도 필드가 없다."""
    return {"w": annotated, "ko": ko}


class PlainSurfaceTest(unittest.TestCase):
    def test_generated_ruby_is_stripped_but_printed_ruby_stays(self) -> None:
        self.assertEqual(ordering.plain_surface("空港(くうこう)"), "空港")
        self.assertEqual(ordering.plain_surface("承(うけたまわ)る"), "承る")
        self.assertEqual(ordering.plain_surface("一(いち)羽（わ）"), "一羽（わ）")

    def test_it_agrees_with_the_canonical_definition_on_production_data(self) -> None:
        import json
        from shared.furigana import plain_surface as canonical
        payload = load("kanji", "data_japanese.json")
        for record in payload.values():
            for bucket in ("readings", "except"):
                for examples in record[bucket].values():
                    for row in examples:
                        self.assertEqual(
                            ordering.plain_surface(row["w"]), canonical(row["w"]))


class FuriganaLengthTest(unittest.TestCase):
    def test_pure_compound(self) -> None:
        self.assertEqual(ordering.furigana_length(example("空港(くうこう)", "공항")), 4)

    def test_okurigana_counts_too(self) -> None:
        """承る 의 읽기는 うけたまわ + る = 6."""
        self.assertEqual(
            ordering.furigana_length(example("承(うけたまわ)る", "받다")), 6)

    def test_alternating_runs(self) -> None:
        self.assertEqual(
            ordering.furigana_length(
                example("離(はな)れ離(ばな)れ", "뿔뿔이")), 6)

    def test_printed_full_width_annotation(self) -> None:
        self.assertEqual(
            ordering.furigana_length(example("今日（きょう）", "오늘")), 3)


class SortTest(unittest.TestCase):
    def test_kanji_length_comes_first(self) -> None:
        rows = [example("生意気(なまいき)", "건방짐"),
                example("空港(くうこう)", "공항")]
        self.assertEqual([e["w"] for e in ordering.sort_examples(rows)],
                         ["空港(くうこう)", "生意気(なまいき)"])

    def test_korean_length_breaks_the_kanji_tie(self) -> None:
        rows = [example("消滅(しょうめつ)", "소멸함"),
                example("空港(くうこう)", "공항")]
        self.assertEqual([e["w"] for e in ordering.sort_examples(rows)],
                         ["空港(くうこう)", "消滅(しょうめつ)"])

    def test_furigana_length_breaks_the_korean_tie(self) -> None:
        rows = [example("消滅(しょうめつ)", "소멸"),
                example("空港(くうこう)", "공항")]
        self.assertEqual([e["w"] for e in ordering.sort_examples(rows)],
                         ["空港(くうこう)", "消滅(しょうめつ)"])

    def test_korean_alphabetical_is_the_last_resort(self) -> None:
        # 세 용례 모두 한자 2자·뜻 2자·후리가나 4모라로 앞의 세 기준이 동점이다.
        rows = [example("漁港(ぎょこう)", "하항"),
                example("空港(くうこう)", "가항"),
                example("開港(かいこう)", "나항")]
        self.assertEqual([e["ko"] for e in ordering.sort_examples(rows)],
                         ["가항", "나항", "하항"])

    def test_sort_is_stable_and_idempotent(self) -> None:
        rows = [example("空港(くうこう)", "공항"),
                example("港湾(こうわん)", "항만"),
                example("港(みなと)", "항구")]
        once = ordering.sort_examples(rows)
        self.assertEqual(once, ordering.sort_examples(once))
        self.assertEqual([e["w"] for e in once],
                         ["港(みなと)", "空港(くうこう)", "港湾(こうわん)"])

    def test_sort_record_touches_both_buckets(self) -> None:
        record = {
            "readings": {"コウ": [example("港湾(こうわん)", "항만"),
                                  example("港(みなと)", "항구")]},
            "except": {"きょう": [example("今日（きょう）", "오늘")]},
        }
        ordering.sort_record(record)
        self.assertEqual([e["w"] for e in record["readings"]["コウ"]],
                         ["港(みなと)", "港湾(こうわん)"])
        self.assertEqual([e["w"] for e in record["except"]["きょう"]], ["今日（きょう）"])


if __name__ == "__main__":
    unittest.main()
