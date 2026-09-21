# -*- coding: utf-8 -*-
"""Anki 연동의 계약.  Anki 가 떠 있지 않아도 전부 돌아간다."""
from __future__ import annotations

import sys
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests import load  # noqa: E402

from decks.kanji.deck import NOTE_TYPE, build_notes  # noqa: E402
from shared.anki import (  # noqa: E402
    DECK_FIELD,
    KEY_FIELD,
    CardTemplate,
    NoteTypeSpec,
    SyncPlan,
    apply_sync,
    escape,
    nfc_safe,
    plan_sync,
)
from shared.ankicard import DATA_FIELD, unpack  # noqa: E402
from shared.furigana import to_anki_ruby, to_ruby_html  # noqa: E402


class RubyTest(unittest.TestCase):
    """Anki 는 '직전 공백 이후'를 읽기 대상으로 본다."""

    def test_plain_compound(self) -> None:
        self.assertEqual(to_anki_ruby("空港(くうこう)"), "空港[くうこう]")

    def test_okurigana_follows_outside_the_bracket(self) -> None:
        self.assertEqual(to_anki_ruby("承(うけたまわ)る"), "承[うけたまわ]る")

    def test_space_is_inserted_when_something_precedes(self) -> None:
        self.assertEqual(to_anki_ruby("お巡(まわ)りさん"), "お 巡[まわ]りさん")
        self.assertEqual(to_anki_ruby("離(はな)れ離(ばな)れ"), "離[はな]れ 離[ばな]れ")
        self.assertEqual(to_anki_ruby("白羽(しらは)の矢(や)"), "白羽[しらは]の 矢[や]")

    def test_printed_reading_is_left_alone(self) -> None:
        """전각 （…） 는 원전 인쇄분이다.  루비로 바꾸면 없던 읽기를 붙인 것이 된다."""
        self.assertEqual(to_anki_ruby("一(いち)羽（わ）"), "一[いち]羽（わ）")
        self.assertEqual(to_anki_ruby("今日（きょう）"), "今日（きょう）")


class RubyHtmlTest(unittest.TestCase):
    """후리가나는 한자 **위에** 붙어야 한다.

    ``漢字[かんじ]`` 표기는 Japanese Support 애드온이 있어야 루비가 되고, 없으면
    대괄호가 한자 옆에 그대로 찍힌다.  애드온에 기대지 않도록 HTML 을 직접 낸다.
    """

    def test_kanji_run_becomes_ruby(self) -> None:
        self.assertEqual(to_ruby_html("空港(くうこう)"),
                         "<ruby>空港<rt>くうこう</rt></ruby>")

    def test_okurigana_stays_outside(self) -> None:
        self.assertEqual(to_ruby_html("承(うけたまわ)る"),
                         "<ruby>承<rt>うけたまわ</rt></ruby>る")

    def test_printed_reading_is_not_turned_into_ruby(self) -> None:
        """전각 （…） 는 원전 인쇄분이라 표기의 일부다."""
        self.assertEqual(to_ruby_html("一(いち)羽（わ）"),
                         "<ruby>一<rt>いち</rt></ruby>羽（わ）")

    def test_markup_characters_are_escaped(self) -> None:
        self.assertEqual(to_ruby_html("a<b>&"), "a&lt;b&gt;&amp;")


class NfcTest(unittest.TestCase):
    def test_compatibility_ideographs_survive_as_references(self) -> None:
        """Anki 는 저장할 때 NFC 로 접는다.  이체자 자형이 사라지면 안 된다."""
        variant = "逸"                      # 逸 (康熙字典体)
        self.assertNotEqual(unicodedata.normalize("NFC", variant), variant)
        self.assertEqual(nfc_safe(f"{variant}(康熙字典体)"), "&#xFA67;(康熙字典体)")

    def test_ordinary_text_is_untouched(self) -> None:
        for value in ("今日[こんにち]", "이제 금", "", "한자::1. 읽기"):
            self.assertEqual(nfc_safe(value), value)

    def test_every_production_variant_survives(self) -> None:
        import json
        payload = load("kanji", "data_japanese.json")
        folded = [variant
                  for record in payload.values()
                  for variant in record.get("variant", {})
                  if unicodedata.normalize("NFC", variant) != variant]
        self.assertTrue(folded, "호환 한자 이체자가 있어야 이 검사가 의미 있다")
        for variant in folded:
            encoded = nfc_safe(variant)
            self.assertTrue(encoded.startswith("&#x"), variant)
            self.assertEqual(unicodedata.normalize("NFC", encoded), encoded)


class SearchEscapeTest(unittest.TestCase):
    def test_special_characters_are_escaped(self) -> None:
        self.assertEqual(escape('a"b'), 'a\\"b')

    def test_the_colon_inside_a_key_is_escaped(self) -> None:
        """``Key:kanji:今`` 이 되면 Anki 가 두 번째 콜론에서 헷갈린다."""
        self.assertEqual(escape("kanji:今"), "kanji\\:今")

    def test_plain_text_is_untouched(self) -> None:
        self.assertEqual(escape("今日"), "今日")


class FakeAnki:
    """AnkiConnect 대역.  대조 논리만 시험한다."""

    def __init__(self, notes=None, placement=None, cards_per_note=1):
        self.notes = dict(notes or {})          # note id -> fields
        self.placement = dict(placement or {})  # note id -> [(card id, ord, deck)]
        self.added: list[dict] = []
        self.updated: list[tuple[int, dict]] = []
        self.moved: list[tuple[list[int], str]] = []
        self.decks: set[str] = set()
        # 노트 하나가 만들어 내는 카드 수.  노트 타입의 카드 템플릿 수와 같다.
        self.cards_per_note = cards_per_note
        self.next_id = 1001

    def __call__(self, action, **params):
        if action == "addNotes":
            made = []
            for note in params["notes"]:
                self.added.append(note)
                note_id = self.next_id
                self.next_id += 1
                # Anki 는 노트를 만들 때 그 카드를 전부 같은 덱에 넣는다.
                self.placement[note_id] = [
                    (note_id * 10 + ordinal, ordinal, note["deckName"])
                    for ordinal in range(self.cards_per_note)]
                made.append(note_id)
            return made
        if action == "updateNoteFields":
            note = params["note"]
            self.updated.append((note["id"], note["fields"]))
            self.notes[note["id"]].update(note["fields"])
            return None
        if action == "findNotes":
            return list(self.notes)
        if action == "notesInfo":
            return [{"noteId": i,
                     "fields": {n: {"value": v} for n, v in self.notes[i].items()}}
                    for i in params["notes"]]
        raise AssertionError(action)

    def existing_keys(self, model):
        return {f[KEY_FIELD]: i for i, f in self.notes.items() if f.get(KEY_FIELD)}

    def notes_fields(self, ids):
        return {i: dict(self.notes[i]) for i in ids}

    def card_decks(self, note_ids):
        return {i: list(self.placement.get(i, [])) for i in note_ids}

    def move_cards(self, card_ids, deck):
        self.moved.append((list(card_ids), deck))

    def ensure_deck(self, name):
        if name in self.decks:
            return False
        self.decks.add(name)
        return True


class SyncTest(unittest.TestCase):
    def test_missing_notes_are_added(self) -> None:
        anki = FakeAnki()
        plan = plan_sync(anki, "M", [{KEY_FIELD: "k:1", "Kanji": "一"}])
        self.assertEqual(plan.summary(), {"add": 1, "update": 0, "move": 0, "unchanged": 0, "stale": 0,
                          "new_decks": 0})

    def test_identical_notes_are_left_alone(self) -> None:
        anki = FakeAnki({7: {KEY_FIELD: "k:1", "Kanji": "一"}})
        plan = plan_sync(anki, "M", [{KEY_FIELD: "k:1", "Kanji": "一"}])
        self.assertEqual(plan.summary(), {"add": 0, "update": 0, "move": 0, "unchanged": 1, "stale": 0,
                          "new_decks": 0})

    def test_only_changed_fields_are_sent(self) -> None:
        anki = FakeAnki({7: {KEY_FIELD: "k:1", "Kanji": "一", "Korean": "옛"}})
        plan = plan_sync(anki, "M", [{KEY_FIELD: "k:1", "Kanji": "一", "Korean": "새"}])
        self.assertEqual(plan.summary(), {"add": 0, "update": 1, "move": 0, "unchanged": 0, "stale": 0,
                          "new_decks": 0})
        apply_sync(anki, "D", "M", plan)
        self.assertEqual(anki.updated, [(7, {"Korean": "새"})])

    def test_sync_is_idempotent(self) -> None:
        anki = FakeAnki()
        notes = [{KEY_FIELD: "k:1", "Kanji": "一"}]
        apply_sync(anki, "D", "M", plan_sync(anki, "M", notes))
        anki.notes = {1: dict(anki.added[0]["fields"])}
        self.assertEqual(plan_sync(anki, "M", notes).summary(),
                         {"add": 0, "update": 0, "move": 0, "unchanged": 1, "stale": 0,
                          "new_decks": 0})

    def test_sync_never_deletes(self) -> None:
        """Anki 에만 있는 노트는 **지우지 않는다.**  세어서 보여 주기만 한다.

        식별자 규칙을 바꾸면(문법 덱이 예문 단위에서 문형 단위로 옮겨 갔듯) 옛
        노트가 남는다.  무엇이 남았는지 사람이 알아야 하지만, 되살리거나 지우는
        것은 프로젝트가 할 일이 아니다.
        """
        anki = FakeAnki({7: {KEY_FIELD: "k:버림", "Kanji": "廢"}})
        plan = plan_sync(anki, "M", [{KEY_FIELD: "k:1", "Kanji": "一"}])
        self.assertEqual(plan.summary(),
                         {"add": 1, "update": 0, "move": 0, "unchanged": 0, "stale": 1,
                          "new_decks": 0})
        self.assertEqual(plan.stale, ["k:버림"])
        apply_sync(anki, "D", "M", plan)
        self.assertIn(7, anki.notes)

    def test_a_note_without_a_key_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            plan_sync(FakeAnki(), "M", [{"Kanji": "一"}])


class SubdeckTest(unittest.TestCase):
    """노트는 자기가 놓일 하위 덱을 지고 다닌다."""

    def test_new_notes_go_to_their_own_deck(self) -> None:
        anki = FakeAnki()
        plan = plan_sync(anki, "M",
                         [{KEY_FIELD: "k:1", "A": "x", DECK_FIELD: "D::1 A"}])
        apply_sync(anki, "D", "M", plan)
        self.assertEqual(anki.added[0]["deckName"], "D::1 A")
        # __deck__ 은 표식일 뿐 Anki 필드가 아니다.
        self.assertNotIn(DECK_FIELD, anki.added[0]["fields"])

    def test_the_subdeck_of_a_new_note_is_created_first(self) -> None:
        """Anki 는 없는 덱으로 보낸 배치를 통째로 거절한다.

        하위 덱 이름을 바꾸면 첫 동기화의 추가분이 아직 없는 덱으로 간다.  만들지
        않고 보내면 그 배치가 전부 실패한다.
        """
        anki = FakeAnki()
        plan = plan_sync(anki, "M",
                         [{KEY_FIELD: "k:1", "A": "x", DECK_FIELD: "D::새 덱"}])
        apply_sync(anki, "D", "M", plan)
        self.assertIn("D::새 덱", anki.decks)

    def test_existing_cards_in_the_wrong_deck_are_moved(self) -> None:
        """덱 구조를 바꾸면 이미 있던 카드도 제자리를 찾아가야 한다."""
        anki = FakeAnki({7: {KEY_FIELD: "k:1", "A": "x"}},
                        placement={7: [(70, 0, "D"), (71, 1, "D")]})
        plan = plan_sync(anki, "M",
                         [{KEY_FIELD: "k:1", "A": "x", DECK_FIELD: "D::1 A"}])
        self.assertEqual(plan.summary(),
                         {"add": 0, "update": 0, "move": 2, "unchanged": 0, "stale": 0,
                          "new_decks": 0})
        apply_sync(anki, "D", "M", plan)
        self.assertEqual(anki.moved, [([70, 71], "D::1 A")])

    def test_cards_already_in_place_are_left_alone(self) -> None:
        anki = FakeAnki({7: {KEY_FIELD: "k:1", "A": "x"}},
                        placement={7: [(70, 0, "D::1 A")]})
        plan = plan_sync(anki, "M",
                         [{KEY_FIELD: "k:1", "A": "x", DECK_FIELD: "D::1 A"}])
        self.assertEqual(plan.summary(),
                         {"add": 0, "update": 0, "move": 0, "unchanged": 1, "stale": 0,
                          "new_decks": 0})

    def test_each_card_of_a_note_goes_to_its_own_deck(self) -> None:
        """읽기와 쓰기는 진도가 다르다.  한 노트의 두 카드가 서로 다른 덱에 놓인다."""
        model = NoteTypeSpec("M", [KEY_FIELD, "A"],
                             [CardTemplate("읽기", "{{A}}", "{{A}}"),
                              CardTemplate("쓰기", "{{A}}", "{{A}}")])
        anki = FakeAnki({7: {KEY_FIELD: "k:1", "A": "x"}},
                        placement={7: [(70, 0, "D"), (71, 1, "D")]})
        note = {KEY_FIELD: "k:1", "A": "x",
                DECK_FIELD: {"읽기": "D::1. 읽기", "쓰기": "D::2. 쓰기"}}
        plan = plan_sync(anki, model, [note])
        self.assertEqual(plan.summary(),
                         {"add": 0, "update": 0, "move": 2, "unchanged": 0, "stale": 0,
                          "new_decks": 0})
        apply_sync(anki, "D", model, plan)
        self.assertEqual(sorted(anki.moved),
                         [([70], "D::1. 읽기"), ([71], "D::2. 쓰기")])

    def test_a_new_note_has_every_card_placed_at_once(self) -> None:
        """노트를 만들 때 덱은 하나만 고를 수 있다.  나머지 카드는 곧바로 옮긴다 —
        미루면 사람이 같은 버튼을 두 번 눌러야 한다."""
        model = NoteTypeSpec("M", [KEY_FIELD, "A"],
                             [CardTemplate("읽기", "{{A}}", "{{A}}"),
                              CardTemplate("쓰기", "{{A}}", "{{A}}")])
        anki = FakeAnki(cards_per_note=2)
        note = {KEY_FIELD: "k:1", "A": "x",
                DECK_FIELD: {"읽기": "D::1. 읽기", "쓰기": "D::2. 쓰기"}}
        apply_sync(anki, "D", model, plan_sync(anki, model, [note]))
        self.assertEqual(anki.added[0]["deckName"], "D::1. 읽기")
        self.assertEqual({"D::1. 읽기", "D::2. 쓰기"} - anki.decks, set())
        # 두 번째 카드(쓰기)만 옮겨진다.  첫 카드는 만들 때 이미 제자리다.
        second = anki.placement[1001][1][0]
        self.assertEqual(anki.moved, [([second], "D::2. 쓰기")])


class ForbiddenTest(unittest.TestCase):
    """학습 설정과 학습 이력은 이 프로젝트의 것이 아니다.

    사전 설정은 사람이 자기 리듬에 맞춰 정한 것이고 데이터에서 다시 만들어 낼 수
    없다.  실수로라도 부르지 못하게 코드가 막는다.
    """

    def test_config_writing_actions_are_refused(self) -> None:
        from shared.anki import Anki, AnkiForbidden
        anki = Anki()
        for action in ("saveDeckConfig", "setDeckConfigId", "cloneDeckConfigId",
                       "removeDeckConfigId", "updateCompleteDeck"):
            with self.subTest(action=action), self.assertRaises(AnkiForbidden):
                anki(action)

    def test_history_erasing_actions_are_refused(self) -> None:
        from shared.anki import Anki, AnkiForbidden
        anki = Anki()
        for action in ("forgetCards", "setDueDate", "relearnCards"):
            with self.subTest(action=action), self.assertRaises(AnkiForbidden):
                anki(action)

    def test_the_actions_we_do_use_are_not_forbidden(self) -> None:
        from shared.anki import FORBIDDEN_ACTIONS
        for action in ("addNotes", "updateNoteFields", "changeDeck", "createDeck",
                       "findCards", "cardsInfo", "notesInfo", "deckNames"):
            self.assertNotIn(action, FORBIDDEN_ACTIONS)


class NewDeckTest(unittest.TestCase):
    """새로 만든 덱은 기본 사전 설정을 쓴다.  그 사실을 사람에게 알려야 한다."""

    def test_created_decks_are_reported(self) -> None:
        model = NoteTypeSpec("M", [KEY_FIELD, "A"],
                             [CardTemplate("읽기", "{{A}}", "{{A}}")])
        anki = FakeAnki()
        note = {KEY_FIELD: "k:1", "A": "x", DECK_FIELD: "D::새 덱"}
        plan = plan_sync(anki, model, [note])
        result = apply_sync(anki, "D", model, plan)
        self.assertEqual(plan.created, ["D::새 덱"])
        self.assertEqual(result["new_decks"], 1)

    def test_an_existing_deck_is_not_reported(self) -> None:
        model = NoteTypeSpec("M", [KEY_FIELD, "A"],
                             [CardTemplate("읽기", "{{A}}", "{{A}}")])
        anki = FakeAnki()
        anki.decks.add("D::있던 덱")
        note = {KEY_FIELD: "k:1", "A": "x", DECK_FIELD: "D::있던 덱"}
        plan = plan_sync(anki, model, [note])
        apply_sync(anki, "D", model, plan)
        self.assertEqual(plan.created, [])


class NoteTypeTest(unittest.TestCase):
    def test_key_field_is_required(self) -> None:
        with self.assertRaises(ValueError):
            NoteTypeSpec("X", ["A"], [])


class ProductionNotesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import json
        cls.payload = load("kanji", "data_japanese.json")
        cls.notes = build_notes(cls.payload)

    def test_one_note_per_character_with_a_unique_key(self) -> None:
        self.assertEqual(len(self.notes), len(self.payload))
        keys = {note[KEY_FIELD] for note in self.notes}
        self.assertEqual(len(keys), len(self.notes))

    def test_every_note_fills_the_declared_fields(self) -> None:
        from decks.kanji.deck import NOTE_TYPE
        for note in self.notes:
            self.assertEqual(set(note) - {DECK_FIELD}, set(NOTE_TYPE.fields))

    def test_every_note_declares_a_deck_for_each_of_its_cards(self) -> None:
        """방향(읽기·쓰기)이 먼저 갈리고 그 아래에서 학년으로 갈린다.

        Anki 는 하위 덱을 이름순으로만 늘어놓으므로 학습 순서는 이름 앞의 번호로
        고정한다.
        """
        from decks.kanji.deck import ANKI_DECK, CARD_DECKS, NOTE_TYPE, SUBDECKS
        leaves = [f"{index}. {label}"
                  for index, (_tag, label) in enumerate(SUBDECKS, 1)]
        wanted = {f"{ANKI_DECK}::{group}::{leaf}"
                  for group in CARD_DECKS.values() for leaf in leaves}
        seen = set()
        for note in self.notes:
            placement = note[DECK_FIELD]
            self.assertEqual(set(placement),
                             {t.name for t in NOTE_TYPE.templates})
            seen |= set(placement.values())
        self.assertEqual(seen, wanted)

    def test_the_card_data_is_the_record_itself(self) -> None:
        """Anki 가 받는 것은 만들어 둔 HTML 이 아니라 **레코드 그 자체**다."""
        for note in self.notes[:50]:
            envelope = unpack(note[DATA_FIELD])
            character = note["Kanji"]
            self.assertEqual(envelope["key"], character)
            self.assertEqual(envelope["record"], self.payload[character])

    def test_the_data_field_is_pure_ascii(self) -> None:
        """base64 라서 NFC 정규화가 손댈 것이 없다 — 이체자가 접히지 않는다."""
        for note in self.notes:
            self.assertTrue(note[DATA_FIELD].isascii(), note["Kanji"])
            self.assertEqual(nfc_safe(note[DATA_FIELD]), note[DATA_FIELD])

    def test_every_variant_survives_the_round_trip(self) -> None:
        """이체자 62 자는 CJK 호환 한자다.  필드에 직접 실으면 자형이 사라진다."""
        for note in self.notes:
            wanted = self.payload[note["Kanji"]].get("variant", {})
            if wanted:
                self.assertEqual(unpack(note[DATA_FIELD])["record"]["variant"],
                                 wanted, note["Kanji"])


if __name__ == "__main__":
    unittest.main()


class CacheTest(unittest.TestCase):
    """한 파일에 용도가 둘 이상이어도 서로를 덮어쓰지 않아야 한다."""

    def test_two_purposes_survive_each_other(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        from shared.gemini import MODEL, Cache

        path = Path(tempfile.mkdtemp()) / "cache.json"
        alpha = Cache(path, "alpha")
        beta = Cache(path, "beta")
        alpha["x"] = "1"
        alpha.flush()
        beta["y"] = "2"
        beta.flush()                      # 여기서 alpha 가 사라지면 안 된다
        saved = json.loads(path.read_text(encoding="utf-8"))[MODEL]
        self.assertEqual(saved["alpha"], {"x": "1"})
        self.assertEqual(saved["beta"], {"y": "2"})
