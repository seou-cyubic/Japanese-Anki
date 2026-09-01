# -*- coding: utf-8 -*-
"""토익 덱: 목록 합치기·주석 만들기·검증 등급·덱 계약."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests import deck_data, load  # noqa: E402

from decks.toeic import model  # noqa: E402
from decks.toeic.pipeline import stage1_lists, stage3_verify  # noqa: E402
from shared.furigana import annotate, plain_surface  # noqa: E402



class AnnotationTest(unittest.TestCase):
    """표기와 읽기를 합쳐 이 저장소의 주석 표기를 만든다.

    가나는 읽기 위의 고정점이다.  그것을 앵커로 삼으면 각 한자런이 담당하는 구간이
    확정된다 — 한자 덱의 付表 판정이 쓰는 것과 같은 착상이다.
    """

    def test_whole_word_is_one_run(self) -> None:
        self.assertEqual(annotate("取締役会", "とりしまりやくかい"),
                         "取締役会(とりしまりやくかい)")

    def test_okurigana_stays_outside(self) -> None:
        self.assertEqual(annotate("搭乗する", "とうじょうする"), "搭乗(とうじょう)する")

    def test_kana_between_two_runs_anchors_both(self) -> None:
        self.assertEqual(annotate("払い戻す", "はらいもどす"), "払(はら)い戻(もど)す")

    def test_kana_prefix_is_kept(self) -> None:
        self.assertEqual(annotate("お知らせ", "おしらせ"), "お知(し)らせ")

    def test_a_kana_only_word_needs_no_annotation(self) -> None:
        self.assertEqual(annotate("チャージ", "チャージ"), "チャージ")

    def test_a_reading_that_does_not_fit_is_refused(self) -> None:
        """맞물리지 않으면 **조용히 무언가를 고르지 않는다.**"""
        self.assertIsNone(annotate("搭乗する", "とうじょうしない"))
        self.assertIsNone(annotate("お知らせ", "しらせ"))

    def test_an_already_annotated_surface_is_left_alone(self) -> None:
        self.assertIsNone(annotate("搭乗(とうじょう)する", "とうじょうする"))

    def test_the_annotation_restores_the_surface(self) -> None:
        for surface, reading in (("取締役会", "とりしまりやくかい"),
                                 ("払い戻す", "はらいもどす"),
                                 ("買い物客", "かいものきゃく")):
            self.assertEqual(plain_surface(annotate(surface, reading)), surface)


class VerifyTest(unittest.TestCase):
    """모델이 낸 일본어를 사전이 확인한다.  읽기가 틀리면 학습자가 그대로 외운다."""

    READINGS = {"搭乗": {"とうじょう"}, "取締役会": {"とりしまりやくかい"},
                "掲示板": {"けいじばん"}, "上手": {"じょうず", "うわて"}}

    def test_a_matching_reading_passes(self) -> None:
        self.assertEqual(
            stage3_verify.verify("取締役会", "とりしまりやくかい", self.READINGS),
            (stage3_verify.CHECKED, "とりしまりやくかい"))

    def test_a_suru_tail_is_stripped_before_looking_up(self) -> None:
        state, reading = stage3_verify.verify("搭乗する", "とうじょうする", self.READINGS)
        self.assertEqual(state, stage3_verify.CHECKED)
        self.assertEqual(reading, "とうじょうする")

    def test_any_of_the_dictionary_readings_may_match(self) -> None:
        self.assertEqual(
            stage3_verify.verify("上手", "うわて", self.READINGS)[0],
            stage3_verify.CHECKED)

    def test_a_wrong_reading_is_flagged_and_corrected(self) -> None:
        state, reading = stage3_verify.verify("掲示板", "けいしばん", self.READINGS)
        self.assertEqual(state, stage3_verify.UNSURE)
        self.assertEqual(reading, "けいじばん")     # 사전 쪽 읽기를 들려 보낸다

    def test_something_that_is_not_a_headword_is_a_phrase(self) -> None:
        state, _reading = stage3_verify.verify("していただけませんか",
                                               "していただけませんか", self.READINGS)
        self.assertEqual(state, stage3_verify.PHRASE)


class ListTest(unittest.TestCase):
    """NGSL 과 TSL 은 한 낱말도 겹치지 않는다 — 합집합이 곧 덱 크기다."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.entries = load("toeic", "toeic.json")

    def test_the_two_lists_do_not_overlap(self) -> None:
        ngsl = {w for w, e in self.entries.items() if e["list"] == "ngsl"}
        tsl = {w for w, e in self.entries.items() if e["list"] == "tsl"}
        self.assertEqual(ngsl & tsl, set())
        self.assertEqual(len(ngsl), 2809)
        self.assertEqual(len(tsl), 1250)
        self.assertEqual(len(self.entries), 4059)

    def test_every_word_lands_in_a_band(self) -> None:
        for word, entry in self.entries.items():
            self.assertIn(entry["band"], model.BAND_LABELS, word)

    def test_the_band_follows_the_rank(self) -> None:
        for word, entry in self.entries.items():
            if entry["list"] != "ngsl":
                continue
            wanted = stage1_lists.band_of(entry["rank"])
            self.assertEqual(entry["band"], wanted, word)

    def test_every_word_carries_its_own_family(self) -> None:
        for word, entry in self.entries.items():
            forms = [form.lower() for form in entry["family"]]
            self.assertIn(word, forms, word)


class ProductionDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = load("toeic", "toeic_japanese.json")

    def test_the_payload_satisfies_the_contract(self) -> None:
        self.assertEqual(model.validate_payload(self.payload), [])

    def test_every_word_has_at_least_one_sense(self) -> None:
        empty = [w for w, r in self.payload.items() if not r["senses"]]
        self.assertEqual(empty, [], f"뜻이 없는 낱말 {len(empty)}개")

    def test_every_japanese_form_is_wholly_annotated_or_not_at_all(self) -> None:
        """반쪽짜리 주석은 허용하지 않는다.

        어떤 한자에는 읽기가 있고 어떤 한자에는 없으면, 학습자가 그 빠진 곳을
        '읽기가 필요 없는 글자' 로 오해한다.
        """
        for word, record in self.payload.items():
            for sense in record["senses"]:
                self.assertTrue(model.is_written(sense["ja"]),
                                f"{word}: {sense['ja']!r}")

    def test_almost_every_form_carries_furigana(self) -> None:
        """한자가 있으면 읽기가 붙어야 한다.  붙지 못한 것은 손에 꼽아야 한다."""
        from shared.furigana import is_cjk_run
        bare = [f"{w}:{s['ja']}" for w, r in self.payload.items() for s in r["senses"]
                if "(" not in s["ja"] and any(is_cjk_run(c) for c in s["ja"])]
        self.assertLess(len(bare), 40, f"주석이 없는 한자 표기가 많다: {bare[:20]}")

    def test_senses_keep_the_order_the_model_gave(self) -> None:
        """뜻의 순서가 이 덱의 알맹이다.  저장 경로가 다시 정렬하면 안 된다."""
        for word, record in list(self.payload.items())[:200]:
            self.assertEqual(model.sort_record(record)["senses"], record["senses"], word)

    def test_examples_are_a_whole_pair_or_absent(self) -> None:
        """한쪽만 있으면 카드가 반쪽이 된다.  둘 다이거나 둘 다 없거나다."""
        for word, record in self.payload.items():
            for index, sense in enumerate(record["senses"]):
                self.assertEqual(model.validate_example(f"{word}[{index}]",
                                                        sense.get("example")), [])

    def test_the_example_contains_both_the_word_and_the_sense(self) -> None:
        """예문은 그 낱말과 그 뜻이 쓰인 자리를 보여 주는 것이다."""
        import re
        from decks.toeic.pipeline.stage4_examples import japanese_stem
        from shared.furigana import plain_surface as plain
        missed = []
        for word, record in self.payload.items():
            family = [f.lower() for f in record["family"]]
            for sense in record["senses"]:
                example = sense.get("example")
                if not example:
                    continue
                english = example["en"].lower()
                if not any(re.search(rf"\b{re.escape(f)}", english) for f in family):
                    missed.append((word, "en"))
                if japanese_stem(plain(sense["ja"])) not in plain(example["ja"]):
                    missed.append((word, "ja"))
        self.assertEqual(missed[:10], [], f"{len(missed)}건이 낱말을 담지 않았다")

    def test_most_senses_are_dictionary_checked(self) -> None:
        senses = [s for r in self.payload.values() for s in r["senses"]]
        checked = sum(1 for s in senses if s["checked"] == "jmdict")
        self.assertGreater(checked / len(senses), 0.7,
                           "사전으로 확인된 뜻이 70% 아래다 — 검증기를 의심한다")


class DeckContractTest(unittest.TestCase):
    def test_the_deck_is_discovered(self) -> None:
        from shared.deckspec import discover
        from shared.paths import DECKS
        self.assertIn("toeic", discover(DECKS))

    def test_the_subdeck_splits_by_direction_then_band(self) -> None:
        from decks.toeic.deck import ANKI_DECK, CARD_DECKS, subdeck
        placement = subdeck("1-1000")
        self.assertEqual(set(placement), set(CARD_DECKS))
        for deck in placement.values():
            self.assertTrue(deck.startswith(f"{ANKI_DECK}::"), deck)
        self.assertEqual(placement["뜻"], "토익::1. 뜻::1. NGSL 1-1000")
        self.assertEqual(placement["철자"], "토익::2. 철자::1. NGSL 1-1000")

    def test_notes_carry_the_record_itself(self) -> None:
        from decks.toeic.deck import DECK
        from shared.ankicard import DATA_FIELD, unpack
        deck_data("toeic", "toeic_japanese.json")
        payload = DECK.load_payload()
        notes = DECK.anki_notes[0].build(payload)
        self.assertEqual(len(notes), len(payload))
        for note in notes[:50]:
            env = unpack(note[DATA_FIELD])
            self.assertEqual(env["record"], payload[env["key"]])
            self.assertTrue(note[DATA_FIELD].isascii())


if __name__ == "__main__":
    unittest.main()
