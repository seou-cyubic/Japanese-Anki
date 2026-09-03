from __future__ import annotations

import unittest
from collections import Counter

from decks.kanji.pipeline.stage3_reading_keys import (
    infer_actual_kanji_reading,
    is_jmdict_verb_pos,
    merge_reading_rows,
    reading_category_key,
)


class Stage3ReadingKeyTest(unittest.TestCase):
    def test_jmdict_boundary_evidence_requires_a_verb_pos(self) -> None:
        self.assertTrue(is_jmdict_verb_pos({"&n;", "&v1;", "&vi;"}))
        self.assertTrue(is_jmdict_verb_pos({"&aux-v;"}))
        self.assertFalse(is_jmdict_verb_pos({"&n;", "&adj-no;"}))

    def test_sei_inflections_use_only_the_kanji_reading(self) -> None:
        cases = (
            ("いきる", ["生きる", "長生き"], "い", "surface"),
            ("いかす", ["生かす"], "い", "surface"),
            ("いける", ["生ける", "生け捕り"], "い", "surface"),
            ("うまれる", ["生まれる", "生まれ"], "う", "surface"),
            ("うむ", ["生む"], "う", "surface"),
            ("おう", ["生い立ち", "生い茂る"], "お", "renyo"),
            ("はえる", ["生える", "芽生える"], "は", "surface"),
            ("はやす", ["生やす"], "は", "surface"),
        )
        for reading, examples, expected, method in cases:
            with self.subTest(reading=reading):
                self.assertEqual(
                    infer_actual_kanji_reading("生", reading, examples),
                    (expected, method),
                )
                self.assertEqual(
                    reading_category_key("生", reading, examples)[0],
                    expected + "ー",
                )

    def test_same_actual_reading_merges_in_source_order(self) -> None:
        stats: Counter[str] = Counter()
        merged = merge_reading_rows(
            "生",
            {
                "セイ": ["生活"],
                "いきる": ["生きる", "長生き"],
                "いかす": ["生かす"],
                "いける": ["生ける", "生け捕り"],
                "うまれる": ["生まれる", "生まれ"],
                "うむ": ["生む"],
                "おう": ["生い立ち", "生い茂る"],
                "はえる": ["生える", "芽生える"],
                "はやす": ["生やす"],
                "き": ["生糸"],
            },
            stats,
        )
        self.assertEqual(list(merged), ["セイ", "いー", "うー", "おー", "はー", "き"])
        self.assertEqual(
            merged["いー"],
            ["生きる", "長生き", "生かす", "生ける", "生け捕り"],
        )
        self.assertEqual(merged["うー"], ["生まれる", "生まれ", "生む"])
        self.assertEqual(merged["おー"], ["生い立ち", "生い茂る"])
        self.assertEqual(merged["はー"], ["生える", "芽生える", "生やす"])
        self.assertEqual(stats["surface"], 7)
        self.assertEqual(stats["renyo"], 1)

    def test_ending_shape_without_okurigana_is_not_inflection(self) -> None:
        for kanji, reading, word in (
            ("位", "くらい", "位"),
            ("猿", "さる", "猿"),
            ("夏", "なつ", "夏"),
            ("犬", "いぬ", "犬"),
        ):
            with self.subTest(kanji=kanji):
                self.assertEqual(
                    reading_category_key(kanji, reading, [word]),
                    (reading, "uninflected"),
                )

    def test_numerals_keep_their_okurigana_and_never_become_verb_stems(self) -> None:
        """``三つ指`` 의 ``みつ`` 는 ``立つ`` 의 ``たつ`` 와 겉모습만 같다.

        본표는 수사를 세 꼴로 싣는다 — ``み``·``みつ``·``みっつ``.  가운데 꼴이
        빠져 있어서 ``みつ`` 가 ``みー`` 로 갈렸고, 화면에서 '동사 활용' 칸에 앉았다.
        """
        for kanji, reading, example in (
            ("三", "みつ", "三つ指"),
            ("四", "よつ", "四つ角"),
            ("五", "いつ", "五つ"),
            ("六", "むつ", "六つ切り"),
            ("八", "やつ", "八つ当たり"),
        ):
            with self.subTest(kanji=kanji):
                self.assertEqual(
                    reading_category_key(kanji, reading, [example]),
                    (reading, "plain"),
                )

    def test_nouns_that_end_in_i_are_not_adjectives(self) -> None:
        """``互い``·``災い`` 는 활용하지 않는다.  끝소리 하나로 어간을 만들면 명사가
        통째로 '동사 활용' 칸에 앉는다."""
        for kanji, reading, examples in (
            ("互", "たがい", ["互い", "互いに", "互い違い"]),
            ("幸", "さいわい", ["幸い", "幸いな事"]),
            ("災", "わざわい", ["災い"]),
            ("勢", "いきおい", ["勢い"]),
            ("類", "たぐい", ["類い", "○○の類い"]),
        ):
            with self.subTest(kanji=kanji):
                self.assertEqual(
                    reading_category_key(kanji, reading, examples),
                    (reading, "plain"),
                )

    def test_real_i_adjectives_are_still_inflected(self) -> None:
        """명사를 빼내느라 형용사까지 빠지면 안 된다."""
        for kanji, reading, example, expected in (
            ("高", "たかい", "高い", "たかー"),
            ("少", "すくない", "少ない", "すくー"),
            ("潔", "いさぎよい", "潔い", "いさぎよー"),
            ("賢", "かしこい", "賢い", "かしこー"),
        ):
            with self.subTest(kanji=kanji):
                self.assertEqual(
                    reading_category_key(kanji, reading, [example])[0], expected
                )

    def test_a_noun_form_that_shares_a_verb_stem_still_merges(self) -> None:
        """``憩い`` 는 ``憩う`` 와 어간이 같다 — 그쪽은 활용이 맞으므로 갈라 두지 않는다."""
        self.assertEqual(
            merge_reading_rows("憩", {"いこう": ["憩う"], "いこい": ["憩い"]}),
            {"いこー": ["憩う", "憩い"]},
        )
        self.assertEqual(
            merge_reading_rows("問", {"とう": ["問う"], "とい": ["問い"]}),
            {"とー": ["問う", "問い"]},
        )

    def test_real_tsu_verbs_are_still_inflected(self) -> None:
        """수사를 빼내느라 진짜 동사까지 빠지면 안 된다."""
        for kanji, reading, example, expected in (
            ("立", "たつ", "立つ", "たー"),
            ("持", "もつ", "持つ", "もー"),
            ("待", "まつ", "待つ", "まー"),
            ("保", "たもつ", "保つ", "たもー"),
            ("貢", "みつぐ", "貢ぐ", "みつー"),
        ):
            with self.subTest(kanji=kanji):
                self.assertEqual(
                    reading_category_key(kanji, reading, [example])[0], expected
                )

    def test_common_okurigana_boundaries(self) -> None:
        for kanji, reading, example, expected in (
            ("上", "あがる", "上がる", "あー"),
            ("行", "おこなう", "行う", "おこなー"),
            ("承", "うけたまわる", "承る", "うけたまわー"),
            ("明", "あかるい", "明るい", "あかー"),
        ):
            with self.subTest(kanji=kanji, reading=reading):
                self.assertEqual(
                    reading_category_key(kanji, reading, [example])[0], expected
                )

    def test_dictionary_evidence_only_classifies_and_never_adds_examples(self) -> None:
        cases = (
            ("干", "ひる", "干物", "干る", "ひー"),
            ("初", "そめる", "書き初め", "初める", "そー"),
            ("足", "たる", "舌足らず", "足る", "たー"),
            ("飽", "あかす", "……に飽かして", "飽かす", "あー"),
            ("候", "そうろう", "候文", "候う", "そうろー"),
        )
        for kanji, reading, output_example, evidence, expected in cases:
            with self.subTest(kanji=kanji):
                merged = merge_reading_rows(
                    kanji,
                    {reading: [output_example]},
                    evidence={reading: [evidence]},
                )
                self.assertEqual(merged, {expected: [output_example]})


if __name__ == "__main__":
    unittest.main()
