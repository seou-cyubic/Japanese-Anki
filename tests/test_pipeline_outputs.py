from __future__ import annotations

import json
import sys
import unittest
from collections import Counter
from pathlib import Path

from shared.furigana import (
    parse_annotated,
    plain_surface,
    reading_kind,
    reading_matches,
)


ROOT = Path(__file__).resolve().parents[1]

from tests import deck_data, load  # noqa: E402
from shared.gemini import MODEL  # noqa: E402

sys.path.insert(0, str(ROOT / "decks" / "kanji" / "pipeline"))
import meanings  # noqa: E402


class PipelineOutputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.translated = load("kanji", "data_translate.json")
        cls.japanese = load("kanji", "data_japanese.json")
        cache = load("kanji", "cache.json")
        model_cache = cache[MODEL]
        # 뜻은 이제 표기가 아니라 **(한자, 요미카타, 표기)** 에 붙는다.  표기 하나에
        # 답 하나였던 옛 칸(``word_ko``)으로는 ``音(おと)`` 와 ``音(ね)`` 를 가를 수 없었다.
        cls.word_cache = model_cache[meanings.DRAFT_SLOT]
        cls.furigana_cache = model_cache["furigana"]
        # 뜻은 **두 번** 물어 나온다 — 1 패스가 초안을 짓고 2 패스가 감수한다.
        # 카드에 실리는 것은 감수본이고, 감수를 못 받은 자리에서만 초안이다.
        # 그 규칙은 ``pipeline/meanings.py`` 한 곳에만 있고 시험도 그것을 쓴다.
        cls.review_cache = cache.get(meanings.REVIEW_MODEL, {}).get(
            meanings.REVIEW_SLOT, {})
        # 3 패스.  한 낱말이 여러 한자 카드에 실릴 때 뜻이 어긋나면 다시 답한 것이다.
        cls.agree_cache = cache.get(meanings.REVIEW_MODEL, {}).get(
            meanings.AGREE_SLOT, {})
        # 마지막 감수.  Claude Code 세션이 전건을 읽고 남긴 파일이다 — 모델 캐시가 아니다.
        try:
            cls.claude_review = meanings.load_claude_review(
                deck_data("kanji", "claude_review.json"))
        except unittest.SkipTest:
            cls.claude_review = {}

    def test_stage5_only_adds_furigana_to_every_example(self) -> None:
        self.assertEqual(self.translated.keys(), self.japanese.keys())
        regular_count = 0
        exception_count = 0

        for character, translated_record in self.translated.items():
            japanese_record = self.japanese[character]
            for field in translated_record.keys() - {"readings", "except"}:
                self.assertEqual(translated_record[field], japanese_record[field])

            for bucket in ("readings", "except"):
                self.assertEqual(
                    translated_record[bucket].keys(), japanese_record[bucket].keys()
                )
                for reading, translated_examples in translated_record[bucket].items():
                    japanese_examples = japanese_record[bucket][reading]
                    # Stage 5 는 ja 를 붙이고 정렬 규칙을 적용한다.  따라서 순서는
                    # 달라질 수 있어도 (w, ko) 의 다중집합은 보존되어야 한다.
                    self.assertEqual(
                        sorted((e["w"], e["ko"]) for e in translated_examples),
                        sorted((plain_surface(e["w"]), e["ko"]) for e in japanese_examples),
                    )
                    for translated in translated_examples:
                        self.assertEqual(set(translated), {"w", "ko"})
                    for japanese in japanese_examples:
                        self.assertEqual(set(japanese), {"w", "ko"})
                        self.assertTrue(japanese["ko"])
                        parsed = parse_annotated(japanese["w"])
                        self.assertIsNotNone(parsed)
                        # Regular buckets intentionally retain historical special
                        # forms and rendaku examples whose full word reading does
                        # not literally contain the dictionary key.  Exception
                        # buckets, however, name the exact fragment they record.
                        if bucket == "except":
                            self.assertTrue(reading_matches(parsed, reading))
                        surface = plain_surface(japanese["w"])
                        key = f"{character}|{reading}|{surface}"
                        expected = meanings.final_ko(
                            key, self.word_cache[key]["ko"],
                            self.review_cache, self.agree_cache,
                            self.claude_review)
                        self.assertEqual("\n".join(expected), japanese["ko"])
                        self.assertEqual(
                            self.furigana_cache[f"{surface}|{reading}"],
                            japanese["w"],
                        )
                        if bucket == "readings":
                            regular_count += 1
                        else:
                            exception_count += 1

        self.assertEqual(regular_count, 11708)
        # 付表 202 + 備考 의 '특별한 읽기' 13(春雨·観音·天皇…).
        self.assertEqual(exception_count, 215)

    def test_furigana_agrees_with_the_dictionary_where_it_was_wrong(self) -> None:
        """후리가나는 사전에 대 보고 단다(``stage5_japanese.py`` 의 사전 대조).

        예전에는 괄호 구조와 읽기 키만 보았으므로 사전과 다른 읽기가 49 개 실려 있었다.
        공식 표가 정한 한 글자 용례(``掛`` かかり)는 사전보다 표를 따른다.
        """
        expected = {
            ("上", "うわ"): "上積(うわづ)み",
            ("勘", "カン"): "勘当(かんどう)",
            ("出", "スイ"): "出納(すいとう)",
            ("術", "ジュツ"): "術策(じゅっさく)",
            ("掛", "かかり"): "掛(かかり)",
            ("基", "もとい"): "基(もとい)",
        }
        for (character, reading), annotated in expected.items():
            found = [example["w"] for example in self.japanese[character]["readings"][reading]]
            self.assertIn(annotated, found, f"{character} {reading}")

    def test_reading_group_contract_matches_production_data(self) -> None:
        groups = Counter(
            reading_kind(reading)
            for record in self.japanese.values()
            for reading in record["readings"]
        )
        self.assertNotIn(None, groups)
        # 활용 칸에서 훈독으로 옮겨 온 아홉 — 수사 넷(``みつ``·``よつ``·``むつ``·``やつ``)과
        # 명사 다섯(``たがい``·``さいわい``·``わざわい``·``いきおい``·``たぐい``) 이다.
        # 끝소리 모양만 활용을 닮았을 뿐 활용하지 않는다(``stage3_reading_keys.py``).
        self.assertEqual(groups, {"on": 3177, "kun": 818, "verb": 867})

    def test_inflection_key_is_the_actual_kanji_reading(self) -> None:
        readings = self.japanese["生"]["readings"]
        expected = {
            "いー": ["生きる", "長生き", "生かす", "生ける", "生け捕り"],
            "うー": ["生む", "生まれ", "生まれる"],
            "おー": ["生い立ち", "生い茂る"],
            "はー": ["生える", "生やす", "芽生える"],
        }
        for reading, words in expected.items():
            # 순서는 ``ordering.py`` 가 뜻 길이까지 보아 정한다.  여기서 잠그는 것은
            # **어느 읽기 키가 어느 용례를 지는가** 이므로 순서를 빼고 견준다.
            self.assertEqual(
                sorted(plain_surface(example["w"]) for example in readings[reading]),
                sorted(words),
            )
        for obsolete in (
            "いきー",
            "いかー",
            "いけー",
            "うまれー",
            "うむー",
            "おうー",
            "はえー",
            "はやー",
        ):
            self.assertNotIn(obsolete, readings)

    def test_noun_kana_endings_are_not_inflection_markers(self) -> None:
        for character, reading, wrong in (
            ("位", "くらい", "くらー"),
            ("猿", "さる", "さー"),
            ("夏", "なつ", "なー"),
            ("犬", "いぬ", "いー"),
            ("境", "さかい", "さかー"),
            ("病", "やまい", "やまー"),
            ("舞", "まい", None),
            ("謡", "うたい", None),
        ):
            with self.subTest(character=character):
                self.assertIn(reading, self.japanese[character]["readings"])
                if wrong is not None:
                    self.assertNotIn(wrong, self.japanese[character]["readings"])

    def test_exception_keys_are_whole_word_readings(self) -> None:
        # 잠그는 것은 **어느 키 아래 어느 표기가 오는가** 다.  뜻 문자열은 모델이
        # 내는 것이라 다시 받을 때마다 달라질 수 있고, 그것은 이 시험의 주제가 아니다.
        self.assertEqual(
            [example["w"] for example in self.japanese["生"]["except"]["やよい"]],
            ["弥生(やよい)"],
        )
        self.assertEqual(
            [example["w"] for example in self.japanese["乙"]["except"]["さおとめ"]],
            ["早乙女(さおとめ)"],
        )

    def test_regular_reading_keeps_the_kanji_out_of_except(self) -> None:
        """手 는 た·て 를 가지므로 下手·手伝う 를 지지 않는다."""
        self.assertEqual(list(self.japanese["手"]["except"]), ["じょうず"])
        self.assertEqual(list(self.japanese["下"]["except"]), ["へた"])
        self.assertEqual(list(self.japanese["伝"]["except"]),
                         ["てつだう", "てんません"])
        self.assertEqual(self.japanese["年"]["except"], {})
        self.assertEqual(self.japanese["川"]["except"], {})

    def test_fuhyo_cross_references_never_reach_readings(self) -> None:
        """備考 의 「단어（よみ）」 는 付表 포인터이지 용례가 아니다.

        例 칸에 인쇄된 연탁·촉음 용례(一羽（わ） 등)만 남아야 한다.
        """
        leaked = {
            plain_surface(example["w"])
            for record in self.japanese.values()
            for examples in record["readings"].values()
            for example in examples
            if "（" in example["w"]
        }
        self.assertEqual(
            leaked,
            {"一羽（わ）", "三羽（ば）", "六羽（ぱ）", "三日（みっか）",
             "四日（よっか）", "一把（ワ）", "三把（バ）", "十把（パ）"},
        )

    def test_every_example_list_follows_the_ordering_rule(self) -> None:
        import sys
        sys.path.insert(0, str(ROOT / "decks" / "kanji" / "pipeline"))
        import ordering
        violations = [
            (character, bucket, reading)
            for character, record in self.japanese.items()
            for bucket in ("readings", "except")
            for reading, examples in record[bucket].items()
            if examples != ordering.sort_examples(examples)
        ]
        self.assertEqual(violations, [])


    def test_an_on_reading_row_carries_the_on_reading(self) -> None:
        """朝/チョウ 의 今朝 는 けさ 가 아니라 こんちょう 다.

        예외 읽기가 음독 행으로 새어 들어온 사례였다.  付表 는 除去했지만
        요미가나 캐시에까지 남아 있었으므로 여기서 못박는다.
        """
        self.assertEqual(
            sorted(example["w"] for example in self.japanese["朝"]["readings"]["チョウ"]),
            sorted(["今朝(こんちょう)", "朝食(ちょうしょく)", "早朝(そうちょう)"]),
        )
        self.assertEqual(
            sorted(example["w"] for example in self.japanese["今"]["readings"]["コン"]),
            sorted(["今日(こんにち)", "今朝(こんちょう)", "今年(こんねん)",
                    "昨今(さっこん)", "今後(こんご)"]),
        )

    def test_genuine_note_column_examples_survive(self) -> None:
        """備考 칸에는 付表 포인터만 있는 것이 아니라 진짜 용례도 있다.

        괄호 읽기가 없는 都道府県 표기는 구성 한자가 모두 정규 읽기라는 뜻이고,
        따라서 그 한자의 정당한 용례다.  「…」などと使う 안의 것도 마찬가지다.
        이것들까지 지우면 埼·栃·茨·阜 는 용례가 비어 추측으로 채워진다.
        """
        expected = {
            ("岡", "おか"): ["福岡県", "岡山県", "静岡県"],
            ("埼", "さい"): ["埼玉県"],
            ("栃", "とち"): ["栃木県"],
            ("茨", "いばら"): ["茨城県"],
            ("阜", "フ"): ["岐阜県"],
            ("宮", "ク"): ["宮内庁"],
            ("京", "ケイ"): ["京阪", "京浜"],
        }
        for (character, reading), words in expected.items():
            with self.subTest(character=character):
                self.assertEqual(
                    sorted(plain_surface(example["w"])
                           for example in self.japanese[character]["readings"][reading]),
                    sorted(words),
                )

    def test_distinction_marker_notes_never_leak_as_examples(self) -> None:
        """⇔ 뒤는 동음이의 주석이다.  固/かた- 에 「硬い」 가 들어와서는 안 된다."""
        for reading, examples in self.japanese["固"]["readings"].items():
            for example in examples:
                self.assertIn("固", example["w"], f"{reading}: {example['w']}")
        # 城/ジョウ 은 「茨城（いばらき）県，宮城（みやぎ）県」 을 잘못 끊어 만든
        # 「県」 이라는 쓰레기 용례를 갖고 있었다.
        self.assertNotIn(
            "県",
            [plain_surface(e["w"]) for e in self.japanese["城"]["readings"]["ジョウ"]])

if __name__ == "__main__":
    unittest.main()
