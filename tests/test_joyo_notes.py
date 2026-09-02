# -*- coding: utf-8 -*-
"""常用漢字表 본표 備考 칸의 계약.

備考 에는 성격이 전혀 다른 것들이 한 칸에 섞여 있다 — 付表 상호참조, 同訓異字,
자체 주석, 그리고 **표의 다른 어디에도 없는 읽기**.  Stage 3 은 이 칸을 용례를 캐는
데에만 썼고 나머지는 버렸으므로 ``「観音」は，「カンノン」。`` 이 통째로 사라졌다.

이 시험이 잠그는 것은 둘이다.

1. **모르는 모양을 만나면 선다.**  기계적으로 갈리는 것만 자동으로 가르고, 그러지
   못한 것은 전수로 적어 두었다.  둘 다 아니면 ``UnknownNote`` 다 — 조용히 버리는
   것보다 시끄럽게 서는 편이 낫다(``fuhyo.ADJUDICATED`` 와 같은 방법).
2. **備考 는 용례로 새어 들어가지 않는다.**  나온 것은 새 선택 필드 ``note`` 에만
   들어간다.  ``readings``·``except`` 는 한 글자도 바뀌지 않는다.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "decks" / "kanji" / "pipeline"))

from tests import load  # noqa: E402

import notes  # noqa: E402

from decks.kanji.model import NOTE_KINDS, validate_payload  # noqa: E402


class ClassifyTest(unittest.TestCase):
    def test_a_special_reading_is_kept(self) -> None:
        self.assertEqual(
            notes.classify("音", "オン", "「観音」は，「カンノン」。"),
            [{"kind": "special_reading", "of": "オン",
              "word": "観音", "reading": "カンノン"}])

    def test_an_alternative_reading_of_a_word(self) -> None:
        self.assertEqual(
            notes.classify("貼", "チョウ", "「貼付」は，「テンプ」とも。"),
            [{"kind": "also_read", "of": "チョウ",
              "word": "貼付", "reading": "テンプ"}])

    def test_an_alternative_reading_of_the_reading_itself(self) -> None:
        self.assertEqual(
            notes.classify("側", "がわ", "「かわ」とも。"),
            [{"kind": "also_reading", "of": "がわ", "reading": "かわ"}])

    def test_paired_lists_stay_paired(self) -> None:
        """``「春雨」，「小雨」，「霧雨」などは，「はるさめ」，「こさめ」，「きりさめ」。``"""
        found = notes.classify(
            "雨", "あま",
            "「春雨」，「小雨」，「霧雨」などは，「はるさめ」，「こさめ」，「きりさめ」。")
        self.assertEqual([(entry["word"], entry["reading"]) for entry in found],
                         [("春雨", "はるさめ"), ("小雨", "こさめ"), ("霧雨", "きりさめ")])

    def test_one_word_may_carry_several_readings(self) -> None:
        found = notes.classify(
            "主", "ス", "「法主（ホッス）」は，「ホウシュ」，「ホッシュ」とも。")
        self.assertEqual([entry["reading"] for entry in found],
                         ["ホウシュ", "ホッシュ"])
        self.assertEqual({entry["word"] for entry in found}, {"法主"})

    def test_same_kun_cross_references(self) -> None:
        self.assertEqual(
            notes.classify("下", "もと", "⇔元，本，基"),
            [{"kind": "same_kun", "of": "もと", "words": ["元", "本", "基"]}])

    def test_a_fuhyo_pointer_yields_nothing(self) -> None:
        """``下手（へた）`` 는 付表 상호참조다.  ``fuhyo`` 가 이미 맡고 있다."""
        self.assertEqual(notes.classify("下", "カ", "下手（へた）"), [])

    def test_a_glyph_note_yields_nothing(self) -> None:
        """자체 주석은 Stage 1 의 ``variant`` 가 이미 담고 있다."""
        self.assertEqual(notes.classify("餌", "ジ", "［餌］＝許容字体，"), [])

    def test_prefecture_names_are_examples_not_notes(self) -> None:
        """``岡山県，静岡県，福岡県`` 은 용례다.  Stage 3 이 용례로 캔다."""
        self.assertEqual(notes.classify("岡", "おか", "岡山県，静岡県，福岡県"), [])

    def test_a_quoted_word_is_not_mistaken_for_a_pointer(self) -> None:
        """``「羽（は）」`` 는 付表 포인터와 모양이 같지만 인용된 낱말이다."""
        found = notes.classify(
            "羽", "は", "「羽（は）」は，前に来る音によって「わ」，「ば」，「ぱ」になる。")
        self.assertEqual([entry["kind"] for entry in found], ["text"])
        self.assertIn("「羽（は）」", found[0]["body"])

    def test_an_unknown_note_stops_the_build(self) -> None:
        with self.assertRaises(notes.UnknownNote):
            notes.classify("音", "オン", "「観音」は，まったく新しい書きぶり。")

    def test_every_kind_is_declared_in_the_record_contract(self) -> None:
        self.assertEqual(set(notes.KINDS), set(NOTE_KINDS))


class ProductionNoteTest(unittest.TestCase):
    """산출물 전건.  아직 파이프라인을 돌리지 않았으면 건너뛴다."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = load("kanji", "tmp/s1_joyo.json")["rows"]
        cls.payload = load("kanji", "data_japanese.json")

    def test_every_note_in_the_source_is_classified(self) -> None:
        for kanji, rows in self.rows.items():
            try:
                notes.collect(kanji, rows)
            except notes.UnknownNote as error:      # pragma: no cover — 실패 보고용
                self.fail(str(error))

    def test_the_record_contract_accepts_the_notes(self) -> None:
        self.assertEqual(validate_payload(self.payload)[:5], [])

    def test_the_reading_the_table_hides_is_now_carried(self) -> None:
        """``観音`` 을 ``カンノン`` 으로 읽는다는 사실은 備考 에만 있다."""
        carried = self.payload["音"].get("note") or []
        self.assertIn({"kind": "special_reading", "of": "オン",
                       "word": "観音", "reading": "カンノン"}, carried)

    def test_notes_never_leak_into_the_examples(self) -> None:
        """備考 에서 나온 낱말이 용례 칸에 들어가 있으면 안 된다.

        두 곳에 같은 것을 넣으면 어느 쪽이 맞는지 알 수 없게 되고, 備考 를 손보는 일이
        용례를 흔드는 일이 된다.
        """
        leaked = []
        for kanji, record in self.payload.items():
            wanted = {entry.get("body") for entry in record.get("note") or ()
                      if entry.get("kind") == "text"}
            wanted.discard(None)
            if not wanted:
                continue
            for bucket in ("readings", "except"):
                for examples in record.get(bucket, {}).values():
                    for example in examples:
                        if example.get("w") in wanted:
                            leaked.append(f"{kanji}: {example['w']}")
        self.assertEqual(leaked, [])

    def test_the_prefecture_examples_survived(self) -> None:
        """備考 를 갈라내면서 거기서 캐던 용례가 사라지면 안 된다."""
        for kanji, expected in (("茨", "茨城県"), ("埼", "埼玉県"),
                                ("栃", "栃木県"), ("阜", "岐阜県")):
            found = {example["w"]
                     for examples in self.payload[kanji]["readings"].values()
                     for example in examples}
            self.assertTrue(any(expected in surface for surface in found),
                            f"{kanji}: {found}")


if __name__ == "__main__":
    unittest.main()
