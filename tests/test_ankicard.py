# -*- coding: utf-8 -*-
"""화면과 Anki 가 **같은 렌더러로** 같은 카드를 그린다는 계약.

Anki 카드가 프론트엔드와 어긋나지 않는 이유는 '똑같이 만들어 두었기' 때문이 아니라
**같은 파일이 양쪽을 그리기** 때문이다.  이 시험이 잠그는 것은 그 사실이다.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.anki import Anki  # noqa: E402
from shared.ankicard import (  # noqa: E402
    DATA_FIELD,
    TOKENS,
    build_note_type,
    envelope,
    pack,
    unpack,
)
from shared.deckspec import discover  # noqa: E402
from shared.paths import DECKS  # noqa: E402

FOUND = discover(DECKS)


def note_types():
    """(덱 이름, 덱, 노트 타입) 전부.  한 덱이 노트 타입을 여럿 낼 수 있다."""
    for name, spec in FOUND.items():
        for group in spec.anki_notes:
            yield name, spec, group.note_type


class PackingTest(unittest.TestCase):
    """레코드를 그대로 싣되, Anki 가 손댈 수 없는 모양으로 싣는다."""

    def test_round_trip(self) -> None:
        env = envelope("今", {"tag": "s2", "readings": {"コン": []}}, {"level": "N1"})
        self.assertEqual(unpack(pack(env)), env)

    def test_the_same_record_always_packs_the_same(self) -> None:
        """멱등성의 근거.  같은 데이터면 필드가 한 글자도 달라지지 않는다."""
        record = {"b": 1, "a": [1, 2]}
        self.assertEqual(pack(envelope("k", record)), pack(envelope("k", record)))

    def test_packing_is_ascii_so_normalisation_cannot_touch_it(self) -> None:
        """Anki 는 필드를 NFC 로 접는다.  이체자(CJK 호환 한자)가 그 제물이었다."""
        packed = pack(envelope("逸", {"variant": {"逸": "康熙字典体"}}))
        self.assertTrue(packed.isascii())
        self.assertEqual(unpack(packed)["record"]["variant"], {"逸": "康熙字典体"})

    def test_whitespace_inside_the_field_is_survivable(self) -> None:
        """Anki 편집기가 줄바꿈을 끼워 넣어도 원문이 돌아와야 한다."""
        packed = pack(envelope("今", {"a": 1}))
        self.assertEqual(unpack(packed[:8] + "\n " + packed[8:]), unpack(packed))


class NoteTypeTest(unittest.TestCase):
    """노트 타입은 **덱의 static/ 에서 만들어진다.**  손으로 옮겨 적지 않는다."""

    def test_the_css_is_the_frontend_css(self) -> None:
        for name, spec, note_type in note_types():
            with self.subTest(deck=name, note_type=note_type.name):
                card_css = (spec.static_dir / "card.css").read_text(encoding="utf-8")
                self.assertIn(card_css, note_type.css)
                self.assertIn(TOKENS.read_text(encoding="utf-8"), note_type.css)

    def test_every_face_carries_the_frontend_renderer(self) -> None:
        for name, spec, note_type in note_types():
            script = (spec.static_dir / "card.js").read_text(encoding="utf-8")
            for template in note_type.templates:
                for face in (template.front, template.back):
                    with self.subTest(deck=name, card=template.name):
                        self.assertIn(script, face)
                        self.assertIn(f'window["{spec.renderer}"]', face)
                        self.assertIn("noteFrom", face)

    def test_the_renderer_never_contains_anki_field_syntax(self) -> None:
        """``{{`` 가 렌더러에 들어가면 Anki 가 그것을 필드로 읽어 템플릿이 깨진다."""
        for name, spec in FOUND.items():
            with self.subTest(deck=name):
                script = (spec.static_dir / "card.js").read_text(encoding="utf-8")
                self.assertNotIn("{{", script)
                self.assertNotIn("</script", script.lower())

    def test_templates_only_reference_declared_fields(self) -> None:
        """새 프로필에서도 그대로 만들어져야 한다 — 없는 필드를 부르면 Anki 가 막힌다."""
        for name, _spec, note_type in note_types():
            declared = set(note_type.fields)
            for template in note_type.templates:
                for face in (template.front, template.back):
                    for ref in re.findall(r"\{\{([^}]+)\}\}", face):
                        field = ref.split(":")[-1].lstrip("#^/")
                        with self.subTest(deck=name, field=field):
                            self.assertIn(field, declared)

    def test_every_card_face_is_a_face_the_editor_can_show(self) -> None:
        """Anki 의 앞뒷면은 편집기의 모드 탭과 **같은 문자열**이어야 한다.

        그 문자열이 곧 카드 요소의 클래스이고, 무엇을 가릴지는 card.css 가 그
        클래스로만 정한다.  이름이 어긋나면 Anki 에서만 아무것도 가려지지 않는다.
        """
        for name, spec, note_type in note_types():
            modes = {key for key, _label in spec.modes}
            for template in note_type.templates:
                for face in (template.front, template.back):
                    found = re.search(r'"mode":\s*"([^"]+)"', face)
                    with self.subTest(deck=name, card=template.name):
                        self.assertIsNotNone(found)
                        self.assertIn(found.group(1), modes)

    def test_mode_rules_never_reach_another_deck(self) -> None:
        """카드 면 규칙은 그 덱의 카드 안쪽으로 한정되어야 한다.

        편집기는 덱을 오갈 때 두 덱의 ``card.css`` 를 모두 싣고 지우지 않는다.
        한정하지 않은 ``.reading-front .reveal-korean`` 하나가 다른 덱의 카드까지
        가려 버리고, Anki 는 한 덱의 CSS 만 실으므로 그쪽에서는 가려지지 않는다 —
        **화면과 Anki 가 다르게 보이는 원인**이 정확히 이것이었다.
        """
        for name, spec in FOUND.items():
            modes = [key for key, _label in spec.modes]
            css = (spec.static_dir / "card.css").read_text(encoding="utf-8")
            body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
            for rule in body.split("}"):
                selector = rule.split("{")[0]
                for part in selector.split(","):
                    if any(mode in part for mode in modes):
                        with self.subTest(deck=name, selector=part.strip()):
                            self.assertIn("-card", part)

    def test_a_deck_that_draws_ruby_hides_with_visibility(self) -> None:
        """루비를 그리는 덱은 카드 면을 **visibility 로** 가려야 한다.

        ``opacity: 0`` 은 브라우저에서는 가려지는데 Anki 의 웹뷰에서는 루비 주석
        (``<rt>``)이 그대로 보인다 — 앞면에 답이 그대로 뜬다.  ``visibility`` 는
        상속되는 속성이라 자식이 되돌리지 않는 한 반드시 숨는다.
        """
        for name, spec in FOUND.items():
            css = (spec.static_dir / "card.css").read_text(encoding="utf-8")
            if "<ruby>" not in (spec.static_dir / "card.js").read_text(encoding="utf-8"):
                continue                      # 루비를 그리지 않는 덱은 해당 없다
            modes = [key for key, _label in spec.modes]
            body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
            for rule in body.split("}"):
                selector, _, declarations = rule.partition("{")
                if not any(mode in selector for mode in modes):
                    continue
                with self.subTest(deck=name, selector=selector.strip()[:60]):
                    self.assertNotIn("opacity", declarations,
                                     "루비가 보이는 채로 남는다 — visibility 를 쓴다")

    def test_nowrap_text_is_never_allowed_to_shrink_below_itself(self) -> None:
        """**줄이 안 바뀌는 글자 상자는 눌리면 안 된다.**

        플렉스 항목의 기본값 ``min-width: auto`` 는 '내용보다 좁아지지 않는다' 는
        보호막이다.  ``min-width: 0`` 은 그 보호막을 벗기는 선언이라, 자리가 모자라면
        상자가 글자 폭 아래로 눌린다.  안쪽 글자가 ``white-space: nowrap`` 이면 글자는
        줄지 않으므로 **상자 밖으로 흘러 옆 글자와 겹친다** — 한자 덱의 ``書き下ろす``
        가 ``書き`` 와 ``下`` 를 붙여 찍던 것이 이것이다.

        눌러도 되는 경우는 **잘라 낼 때**뿐이다(``overflow: hidden``).  그때는 넘친
        부분이 보이지 않으므로 겹칠 것도 없다.
        """
        sheets = [(spec.static_dir / "card.css") for spec in FOUND.values()]
        sheets.append(ROOT / "app" / "static" / "style.css")
        for sheet in sheets:
            body = re.sub(r"/\*.*?\*/", "", sheet.read_text(encoding="utf-8"), flags=re.S)
            for rule in body.split("}"):
                selector, _, declarations = rule.partition("{")
                if "nowrap" not in declarations or "min-width: 0" not in declarations:
                    continue
                with self.subTest(sheet=sheet.name, selector=selector.strip()[:50]):
                    self.assertIn("overflow: hidden", declarations,
                                  "줄이 안 바뀌는 글자가 눌려 옆 글자와 겹친다 — "
                                  "min-width: 0 을 빼거나 넘친 부분을 잘라 낸다")

    def test_the_example_column_keeps_its_automatic_minimum(self) -> None:
        """용례 칸은 후리가나가 걸리는 단위라 **안에서 줄을 바꿀 수 없다.**

        그래서 눌리면 갈 곳이 없다.  ``min-width`` 를 건드리지 않은 채로 두고,
        자리가 모자라면 칸 **사이**에서 줄을 바꾼다(``flex-wrap``).
        """
        body = re.sub(r"/\*.*?\*/", "",
                      (FOUND["kanji"].static_dir / "card.css").read_text(encoding="utf-8"),
                      flags=re.S)
        rules: dict[str, str] = {}
        for selector, _, declarations in (rule.partition("{") for rule in body.split("}")):
            # 같은 선택자가 반응형 블록에도 나온다.  선언을 모두 이어 본다.
            rules.setdefault(selector.strip(), "")
            rules[selector.strip()] += declarations
        for name in (".example-spell", ".fseg", ".spell"):
            with self.subTest(selector=name):
                self.assertNotIn("min-width", rules[name])
        self.assertIn("flex-wrap: wrap", rules[".example-spell"])
        self.assertIn("flex-wrap: wrap", rules[".word"])

    def test_the_card_sizes_itself_without_the_editor_shell(self) -> None:
        """카드는 **스스로** ``box-sizing: border-box`` 를 진다.

        카드는 ``width: 880px; max-width: 100%`` 에 큰 안쪽 여백을 준다.  편집기는
        ``style.css`` 의 ``* { box-sizing: border-box }`` 아래에서 그리므로 멀쩡하지만
        Anki 노트 타입에는 tokens.css + card.css 만 실린다 — 여백이 폭에 더해져 좁은
        화면(AnkiDroid)에서 카드가 옆으로 넘쳤다(375px 에서 한자 409px, 토익 413px).
        """
        for name, spec in FOUND.items():
            body = re.sub(r"/\*.*?\*/", "",
                          (spec.static_dir / "card.css").read_text(encoding="utf-8"),
                          flags=re.S)
            root = f".{name}-card"
            sized = False
            for rule in body.split("}"):
                selector, _, declarations = rule.partition("{")
                parts = {part.strip() for part in selector.split(",")}
                if root in parts and f"{root} *" in parts \
                        and "box-sizing: border-box" in declarations:
                    sized = True
            with self.subTest(deck=name):
                self.assertTrue(sized, f"{root} 와 그 자손이 border-box 를 스스로 정해야 한다")

    def test_screen_reader_text_is_hidden_inside_the_card(self) -> None:
        """카드가 싣는 ``.sr-only`` 는 카드 CSS 가 스스로 숨긴다.

        원본에서는 이 규칙이 편집기 ``style.css`` 에만 있어서, Anki 의 한자 카드에
        요미카타 갈래 이름(「コン 음독」)이 글자로 새어 나왔다.
        """
        for name, spec in FOUND.items():
            if "sr-only" not in (spec.static_dir / "card.js").read_text(encoding="utf-8"):
                continue
            body = re.sub(r"/\*.*?\*/", "",
                          (spec.static_dir / "card.css").read_text(encoding="utf-8"),
                          flags=re.S)
            rules = {selector.strip(): declarations
                     for selector, _, declarations in
                     (rule.partition("{") for rule in body.split("}"))}
            rule = rules.get(f".{name}-card .sr-only", "")
            with self.subTest(deck=name):
                self.assertIn("clip", rule)
                self.assertIn("position: absolute", rule)

    def test_the_toeic_switch_removes_the_example_rather_than_blanking_it(self) -> None:
        """예문 스위치는 **자리까지 걷어낸다.**

        앞뒤 가림은 *답*을 감추는 것이라 칸을 남겨야 뒤집을 때 글이 튀지 않지만,
        스위치는 사람이 **안 보겠다고 고른 것**이다.  고르고도 빈 자리가 남아 있으면
        고른 대로 되지 않은 것이다.
        """
        body = re.sub(r"/\*.*?\*/", "",
                      (FOUND["toeic"].static_dir / "card.css").read_text(encoding="utf-8"),
                      flags=re.S)
        rules = {selector.strip(): declarations
                 for selector, _, declarations in
                 (rule.partition("{") for rule in body.split("}"))}
        rule = rules.get(".toeic-card.examples-off .tc-example")
        self.assertIsNotNone(rule, "스위치를 끈 카드에서 예문을 걷어내는 규칙이 없다")
        self.assertIn("display: none", rule)

    def test_the_toeic_deck_declares_a_default_for_the_switch(self) -> None:
        """저장소가 막힌 웹뷰에서도 보이는 모습은 정해져 있어야 한다.

        스위치가 고른 값이 없으면 노트 타입에 실린 이 기본값이 쓰인다.
        """
        from decks.toeic.deck import NOTE_TYPE
        for template in NOTE_TYPE.templates:
            for face in (template.front, template.back):
                with self.subTest(card=template.name):
                    self.assertRegex(face, r'"examples":\s*(true|false)')

    def test_the_data_field_is_required(self) -> None:
        with self.assertRaises(ValueError):
            build_note_type(name="X", fields=["Key"],
                            static_dir=FOUND["kanji"].static_dir,
                            renderer="KanjiCard", cards=[("a", "b", "c")])

    def test_every_note_type_declares_the_data_field(self) -> None:
        for name, _spec, note_type in note_types():
            with self.subTest(deck=name, note_type=note_type.name):
                self.assertIn(DATA_FIELD, note_type.fields)


class FakeModelAnki(Anki):
    """노트 타입 쪽 AnkiConnect 대역.  Anki 가 꺼져 있어도 돌아간다."""

    def __init__(self, models=None):
        super().__init__()
        self.models = dict(models or {})       # 이름 -> {fields, templates, css}
        self.calls: list[str] = []

    def __call__(self, action, **params):
        self.calls.append(action)
        if action == "modelNames":
            return list(self.models)
        if action == "createModel":
            self.models[params["modelName"]] = {
                "fields": list(params["inOrderFields"]),
                "templates": {t["Name"]: {"Front": t["Front"], "Back": t["Back"]}
                              for t in params["cardTemplates"]},
                "css": params["css"]}
            return None
        if action == "modelFieldNames":
            return list(self.models[params["modelName"]]["fields"])
        if action == "modelFieldAdd":
            self.models[params["modelName"]]["fields"].insert(
                params["index"], params["fieldName"])
            return None
        if action == "modelTemplates":
            return dict(self.models[params["modelName"]]["templates"])
        if action == "updateModelTemplates":
            self.models[params["model"]["name"]]["templates"].update(
                params["model"]["templates"])
            return None
        if action == "modelStyling":
            return {"css": self.models[params["modelName"]]["css"]}
        if action == "updateModelStyling":
            self.models[params["model"]["name"]]["css"] = params["model"]["css"]
            return None
        raise AssertionError(action)


class EnsureModelTest(unittest.TestCase):
    """카드 디자인이 바뀌면 노트 타입도 따라간다.  필드는 덧셈만 한다."""

    def setUp(self) -> None:
        self.spec = FOUND["bunpo"].anki_notes[0].note_type
        self.anki = FakeModelAnki()

    def test_a_new_model_is_created_whole(self) -> None:
        self.anki.ensure_model(self.spec)
        made = self.anki.models[self.spec.name]
        self.assertEqual(made["fields"], self.spec.fields)
        self.assertEqual(made["css"], self.spec.css)
        self.assertEqual(set(made["templates"]),
                         {t.name for t in self.spec.templates})

    def test_running_again_changes_nothing(self) -> None:
        self.anki.ensure_model(self.spec)
        self.anki.calls.clear()
        self.anki.ensure_model(self.spec)
        for action in ("updateModelTemplates", "updateModelStyling", "modelFieldAdd"):
            self.assertNotIn(action, self.anki.calls)

    def test_a_reverted_note_type_is_visible_before_syncing(self) -> None:
        """Anki 에서 실행 취소를 누르면 노트 타입 갱신만 되돌아간다.

        노트 필드는 그대로라 계획은 '그대로' 로 보이는데 카드는 옛 모습이다.
        그 어긋남을 반영 전에 셀 수 있어야 사람이 알아챈다.
        """
        self.anki.ensure_model(self.spec)
        self.assertEqual(self.anki.template_drift(self.spec), [])
        model = self.anki.models[self.spec.name]
        first = self.spec.templates[0].name
        model["templates"][first] = {"Front": "옛 앞면", "Back": "옛 뒷면"}
        model["css"] = "/* 되돌려진 CSS */"
        self.assertEqual(self.anki.template_drift(self.spec), [first, "css"])

    def test_a_missing_note_type_counts_as_drift(self) -> None:
        self.assertEqual(self.anki.template_drift(self.spec), ["새 노트 타입"])

    def test_a_changed_design_reaches_anki(self) -> None:
        """이것이 없으면 화면만 바뀌고 Anki 는 옛 카드로 남는다."""
        self.anki.ensure_model(self.spec)
        model = self.anki.models[self.spec.name]
        model["css"] = "/* 손으로 고친 옛 CSS */"
        first = self.spec.templates[0].name
        model["templates"][first] = {"Front": "옛 앞면", "Back": "옛 뒷면"}
        self.anki.ensure_model(self.spec)
        self.assertEqual(model["css"], self.spec.css)
        self.assertEqual(model["templates"][first]["Front"],
                         self.spec.templates[0].front)

    def test_fields_are_only_added(self) -> None:
        """Anki 에서 필드를 지우면 그 내용이 사라진다.  뺄셈은 하지 않는다."""
        self.anki.models[self.spec.name] = {
            "fields": ["Key", "옛 필드"],
            "templates": {t.name: {"Front": t.front, "Back": t.back}
                          for t in self.spec.templates},
            "css": self.spec.css}
        self.anki.ensure_model(self.spec)
        fields = self.anki.models[self.spec.name]["fields"]
        self.assertIn("옛 필드", fields)
        for field in self.spec.fields:
            self.assertIn(field, fields)

    def test_a_card_template_anki_has_but_we_do_not_is_left_alone(self) -> None:
        """계획에 없는 카드 템플릿을 지우면 그 카드의 학습 이력이 사라진다."""
        self.anki.ensure_model(self.spec)
        model = self.anki.models[self.spec.name]
        model["templates"]["사람이 만든 카드"] = {"Front": "f", "Back": "b"}
        self.anki.ensure_model(self.spec)
        self.assertIn("사람이 만든 카드", model["templates"])


if __name__ == "__main__":
    unittest.main()
