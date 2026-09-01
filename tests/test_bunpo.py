# -*- coding: utf-8 -*-
"""문법 덱: 추출 표기·문법 구간 표시·덱 계약."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "decks" / "bunpo" / "pipeline"))

from tests import deck_data, load  # noqa: E402

from marking import (MARK, find_span, mark, mark_with_span, marked_span,  # noqa: E402
                     views)
from shared.deckspec import discover  # noqa: E402
from shared.paths import DECKS  # noqa: E402

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


class ViewsTest(unittest.TestCase):
    """주석 표기에서 '표기만'과 '읽기만' 두 평면을 만든다."""

    def test_plain_drops_the_ruby(self) -> None:
        self.assertEqual(views("夏(なつ)の間(あいだ)、")["plain"], "夏の間、")

    def test_reading_replaces_kanji_with_its_ruby(self) -> None:
        self.assertEqual(views("夏(なつ)の間(あいだ)、")["reading"], "なつのあいだ、")

    def test_offsets_point_back_at_the_whole_ruby_group(self) -> None:
        """대응표는 글자가 아니라 **덩이**를 가리킨다.

        한자만 가리키면 그 표로 자른 구간이 한자와 그 읽기 사이에서 끊긴다 —
        ``*後*(あと)``.  그렇게 되면 렌더러는 루비 없는 ``後`` 와 걸릴 한자가 없는
        ``(あと)`` 를 받아, 읽기만 허공에 뜨고 그 자리가 벌어져 보인다.
        """
        annotated = "夏(なつ)の間(あいだ)、"
        view = views(annotated)
        start = view["plain"].index("間")
        begin, end = view["plain_map"][start]
        self.assertEqual(annotated[begin:end], "間(あいだ)")

    def test_reading_replaces_a_multi_kanji_group_as_one(self) -> None:
        """숙자훈은 한자 하나씩 나눌 수 없다.  ``今日`` 의 읽기는 ``きょう`` 하나다."""
        view = views("今日(きょう)は一人(ひとり)で行(い)く。")
        self.assertEqual(view["reading"], "きょうはひとりでいく。")

    def test_every_group_maps_to_its_own_bounds(self) -> None:
        annotated = "今日(きょう)は"
        view = views(annotated)
        for index, character in enumerate(view["plain"][:2]):
            begin, end = view["plain_map"][index]
            self.assertEqual(annotated[begin:end], "今日(きょう)", character)


class MarkingTest(unittest.TestCase):
    """표제형은 가나, 예문은 한자.  후리가나가 그 다리다."""

    def test_literal_match(self) -> None:
        marked, method = mark("愛(あい)あっての結(けっ)婚(こん)", "あっての")
        self.assertEqual(marked, "愛(あい)*あっての*結(けっ)婚(こん)")
        self.assertEqual(method, "exact/plain")

    def test_kana_headword_finds_the_kanji_spelling(self) -> None:
        marked, method = mark("夏(なつ)の間(あいだ)、ずっと", "あいだ")
        self.assertEqual(marked, "夏(なつ)の*間(あいだ)*、ずっと")
        self.assertEqual(method, "exact/reading")

    def test_optional_part_in_parentheses(self) -> None:
        marked, _ = mark("約(やく)束(そく)した以(い)上(じょう)、", "いじょう（は）")
        self.assertEqual(marked_span(marked), "以(い)上(じょう)")

    def test_tilde_stands_for_arbitrary_content(self) -> None:
        marked, _ = mark("は あまりの暑(あつ)さに 食(しょく)欲(よく)", "あまりの～に")
        self.assertEqual(marked_span(marked), "あまりの暑(あつ)さに")

    def test_unmatched_headword_leaves_the_text_alone(self) -> None:
        marked, method = mark("まったく別(べつ)の文(ぶん)です。", "ぬきにして")
        self.assertIsNone(method)
        self.assertNotIn(MARK, marked)

    def test_stripping_the_marks_restores_the_example(self) -> None:
        annotated = "夏(なつ)の間(あいだ)、ずっと"
        marked, _ = mark(annotated, "あいだ")
        self.assertEqual(marked.replace(MARK, ""), annotated)

    def test_the_mark_never_splits_a_kanji_from_its_reading(self) -> None:
        """``*後*(あと)`` 는 나올 수 없다.  덩이 바깥에서만 끊는다."""
        marked, _ = mark("祭(まつ)りの後(あと)、ごみが", "あと")
        self.assertEqual(marked, "祭(まつ)りの*後(あと)*、ごみが")

    def test_a_model_span_ending_on_a_kanji_snaps_past_its_reading(self) -> None:
        """모델은 후리가나를 뗀 평문으로 구간을 준다 — ``祭りの後``.

        그 끝을 글자 그대로 옮기면 별표가 ``後`` 와 ``(あと)`` 사이에 떨어진다.
        """
        marked, method = mark_with_span("祭(まつ)りの後(あと)、ごみが", "後")
        self.assertEqual(marked, "祭(まつ)りの*後(あと)*、ごみが")
        self.assertEqual(method, "model")

    def test_a_model_span_starting_inside_a_group_snaps_to_its_head(self) -> None:
        marked, _ = mark_with_span("今日(きょう)は", "日は")
        self.assertEqual(marked, "*今日(きょう)は*")

    def test_the_span_is_readable_with_one_split(self) -> None:
        """프론트엔드가 쓰는 방법 그대로."""
        marked, _ = mark("愛(あい)あっての結(けっ)婚(こん)", "あっての")
        self.assertEqual(marked.split(MARK)[1], "あっての")


class ExtractedDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entries = load("bunpo", "bunpo.json")

    def test_every_entry_has_what_a_card_needs(self) -> None:
        for entry in self.entries:
            self.assertTrue(entry["head"], entry)
            self.assertTrue(entry["examples"], entry["head"])
            self.assertTrue(entry["gloss_ko"], entry["head"])

    def test_level_counts_match_the_source(self) -> None:
        """급수 표시 수가 표제형 수와 같아야 한 항목도 놓치지 않은 것이다."""
        counts = {level: sum(1 for e in self.entries if e["level"] == level)
                  for level in ("1", "2", "3", "4")}
        self.assertEqual(counts, {"1": 123, "2": 325, "3": 153, "4": 30})
        self.assertEqual(sum(counts.values()), len(self.entries))

    def test_no_example_already_contains_the_marker(self) -> None:
        """``*`` 를 표시로 쓸 수 있는 근거."""
        for entry in self.entries:
            for example in entry["examples"]:
                self.assertNotIn("*", example["ja"])
                self.assertNotIn("＊", example["ja"])

    # 원전의 오식.  ①②②④ 로 매기고 ② 를 통째로 빠뜨린 자리가 있다.
    MISPRINTED = {("くらい～はない", 76): [1, 2, 2, 4],
                  ("ようと（も）", 398): [1, 3, 4, 5, 6]}

    # 원전이 마침표 없이 인쇄한 예문.  표지판(``止まれ``)과 조판 누락 셋이다.
    UNPUNCTUATED = {("かわりに", "①"), ("しろ", "①"), ("て", "③"), ("ぬきで", "①")}

    def test_examples_are_numbered_straight_through(self) -> None:
        """번호가 건너뛰면 예문 하나를 통째로 놓친 것이다.

        예문의 글꼴 굵기가 한 가지가 아니어서(``BODY_FONTS``) Bold 만 보던 때는
        ``が`` 항목의 ② 처럼 한 쪽이 통째로 사라졌다.
        """
        for entry in self.entries:
            numbers = [CIRCLED.index(x["no"]) + 1 for x in entry["examples"]]
            expected = self.MISPRINTED.get((entry["head"], entry["page"]))
            self.assertEqual(numbers, expected or list(range(1, len(numbers) + 1)),
                             f'{entry["head"]} ({entry["page"]} 쪽)')

    def test_examples_are_not_cut_short(self) -> None:
        """예문이 문장부호로 끝나지 않으면 조판 변덕에 꼬리를 잃은 것이다.

        ``むきに`` ③ 은 마지막 ``すよ。`` 가 해설 글꼴로 흘러 있어 ``思いま`` 에서
        끊겨 있었다.
        """
        for entry in self.entries:
            for example in entry["examples"]:
                if (entry["head"], example["no"]) in self.UNPUNCTUATED:
                    continue
                self.assertIn(example["ja"].rstrip()[-1], "。！？」』）…",
                              f'{entry["head"]} {example["no"]}: {example["ja"][-24:]}')

    def test_ruby_is_balanced(self) -> None:
        for entry in self.entries:
            for example in entry["examples"]:
                self.assertEqual(example["ja"].count("("), example["ja"].count(")"),
                                 example["ja"])


class MarkedDataTest(unittest.TestCase):
    """표시가 붙은 산출물 전체를 한 번에 잰다."""

    @classmethod
    def setUpClass(cls) -> None:
        from decks.bunpo.deck import DECK
        deck_data("bunpo", DECK.data_path.name)
        cls.payload = DECK.load_payload()

    def test_no_mark_splits_a_kanji_from_its_reading(self) -> None:
        """전수.  덱 계약이 잡는 것과 같은 규칙을 산출물에도 건다."""
        from decks.bunpo.deck import group_edges, mark_offsets
        for key, entry in self.payload.items():
            for example in entry["examples"]:
                marked = example.get("marked", "")
                if marked.count(MARK) != 2:
                    continue
                edges = group_edges(example["ja"])
                for offset in mark_offsets(marked):
                    self.assertIn(offset, edges, f"{key} {example['no']}: {marked}")

    def test_the_payload_satisfies_its_own_contract(self) -> None:
        from decks.bunpo.deck import validate_payload
        self.assertEqual(validate_payload(self.payload), [])


class ReadingFaceTest(unittest.TestCase):
    """뜻(읽기) 카드의 앞면은 **읽기 연습**이다.

    후리가나가 한자 위에 적혀 있으면 한자를 몰라도 문장이 읽히므로, 앞면에 남겨
    두면 이 카드는 가나 읽기 연습이 된다.  후리가나도 답이다.
    """

    CSS = ROOT / "decks" / "bunpo" / "static" / "card.css"

    @classmethod
    def setUpClass(cls) -> None:
        body = cls.CSS.read_text(encoding="utf-8")
        cls.rules = [
            (selector.strip(), declarations)
            for selector, _, declarations
            in (rule.partition("{") for rule in
                re.sub(r"/\*.*?\*/", "", body, flags=re.S).split("}"))
            if selector.strip()
        ]

    def hidden_on(self, mode: str) -> list[str]:
        """그 면에서 가려지는 선택자들."""
        found = []
        for selector, declarations in self.rules:
            if "hidden" not in declarations:
                continue
            found.extend(part.strip() for part in selector.split(",")
                         if mode in part)
        return found

    def test_the_reading_front_hides_the_furigana(self) -> None:
        self.assertTrue(any(part.endswith("rt")
                            for part in self.hidden_on("reading-front")),
                        "뜻 앞면은 예문의 루비를 가려야 한다")

    def test_the_reading_back_shows_the_furigana(self) -> None:
        """뒷면은 확인하는 자리다.  가리는 것이 없어야 한다."""
        self.assertEqual(self.hidden_on("reading-back"), [])

    def test_the_furigana_keeps_its_room(self) -> None:
        """``display: none`` 이면 줄 높이가 바뀌어 뒤집을 때 문장이 튄다."""
        for selector, declarations in self.rules:
            if "reading-front" in selector and selector.endswith("rt"):
                self.assertIn("visibility", declarations)
                self.assertNotIn("display", declarations)


class NoteKeyTest(unittest.TestCase):
    """사전에는 동형이의 항목이 있고, 원전의 예문 번호에는 오식도 있다."""

    @classmethod
    def setUpClass(cls) -> None:
        from decks.bunpo.deck import DECK
        deck_data("bunpo", DECK.data_path.name)
        cls.notes = DECK.anki_notes[0].build(DECK.load_payload())

    def test_keys_are_unique(self) -> None:
        keys = [note["Key"] for note in self.notes]
        self.assertEqual(len(set(keys)), len(keys))

    def test_homographs_get_a_suffix_but_the_first_keeps_its_bare_key(self) -> None:
        from marking import entry_keys
        keys = entry_keys([{"head": "から"}, {"head": "あっての"}, {"head": "から"}])
        self.assertEqual(keys, ["から", "あっての", "から#2"])

    def test_one_note_per_grammar_point(self) -> None:
        """문형 하나가 카드 한 장이다.  예문은 그 안에 함께 실린다.

        예문마다 노트를 만들면 같은 문형의 예문들이 서로 다른 날 흩어져 나오고,
        '이 문형이 어떤 자리에 쓰이는가' 를 예문끼리 견주어 보는 일이 사라진다.
        인쇄된 예문 번호는 애초에 식별자가 될 수도 없다 — 원전에 ①②②④ 로 잘못
        매긴 항목이 있다.
        """
        from decks.bunpo.deck import build_notes
        entry = {"head": "x", "level": "1", "gloss_ko": "",
                 "examples": [{"no": "②", "ja": "あ"}, {"no": "②", "ja": "い"}]}
        notes = build_notes({"x": entry})
        self.assertEqual([note["Key"] for note in notes], ["bunpo:x"])

    def test_one_note_per_entry_in_production(self) -> None:
        from decks.bunpo.deck import DECK
        payload = DECK.load_payload()
        self.assertEqual(len(self.notes), len(payload))

    def test_the_card_data_is_the_record_itself(self) -> None:
        """Anki 는 만들어 둔 HTML 이 아니라 **레코드 그 자체**를 받는다.

        화면과 Anki 가 같은 렌더러로 그리려면 같은 것을 받아야 한다.  봉투 모양도
        편집기가 넘기는 것과 같다 — ``{key, record, derived}``.
        """
        from shared.ankicard import DATA_FIELD, unpack
        from decks.bunpo.deck import DECK, LEVEL_LABEL
        payload = DECK.load_payload()
        for note in self.notes[:50]:
            envelope = unpack(note[DATA_FIELD])
            entry = payload[envelope["key"]]
            self.assertEqual(envelope["record"], entry)
            self.assertEqual(envelope["derived"]["level"],
                             LEVEL_LABEL.get(entry.get("level", ""), ""))
            self.assertTrue(note[DATA_FIELD].isascii())

    def test_every_example_travels_with_its_grammar(self) -> None:
        from shared.ankicard import DATA_FIELD, unpack
        from decks.bunpo.deck import DECK
        payload = DECK.load_payload()
        carried = sum(len(unpack(note[DATA_FIELD])["record"]["examples"])
                      for note in self.notes)
        self.assertEqual(carried,
                         sum(len(e["examples"]) for e in payload.values()))


class KeyCollisionGuardTest(unittest.TestCase):
    """키가 겹치면 Anki 가 통째로 거절한다.  그 전에 잡아야 한다."""

    def test_plan_sync_refuses_colliding_keys(self) -> None:
        from shared.anki import plan_sync
        from tests.test_anki import FakeAnki
        with self.assertRaises(ValueError) as caught:
            plan_sync(FakeAnki(), "M",
                      [{"Key": "k:1", "A": "x"}, {"Key": "k:1", "A": "y"}])
        self.assertIn("k:1", str(caught.exception))


class DeckContractTest(unittest.TestCase):
    def test_every_deck_folder_is_discovered(self) -> None:
        """덱을 하나 더 붙이는 일은 폴더 하나를 더하는 일이다."""
        found = discover(DECKS)
        self.assertEqual(set(found), {"kanji", "bunpo", "toeic"})

    def test_every_note_type_declares_a_key_field(self) -> None:
        for spec in discover(DECKS).values():
            for group in spec.anki_notes:
                self.assertIn("Key", group.note_type.fields)

    def test_note_type_names_do_not_collide(self) -> None:
        names = [group.note_type.name
                 for spec in discover(DECKS).values() for group in spec.anki_notes]
        self.assertEqual(len(names), len(set(names)))

    def test_each_deck_is_its_own_root(self) -> None:
        """셋은 서로 독립된 학습이다.  Anki 덱 목록에서도 나란한 셋이어야 한다."""
        roots = [spec.anki_deck for spec in discover(DECKS).values()]
        self.assertEqual(sorted(roots), ["문법", "토익", "한자"])
        for root in roots:
            self.assertNotIn("::", root)


if __name__ == "__main__":
    unittest.main()
