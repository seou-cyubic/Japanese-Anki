# -*- coding: utf-8 -*-
"""AnkiConnect 클라이언트와 덱 동기화.

Anki 가 실행 중이고 AnkiConnect 애드온(코드 2055492159)이 설치되어 있어야 한다.
애드온은 기본으로 **8765 포트**를 쓰므로 이 프로젝트의 편집기는 다른 포트를 쓴다.

**학습 설정과 학습 이력은 건드리지 않는다.**  사전 설정은 사람이 자기 리듬에 맞춰
정한 것이고 데이터에서 다시 만들어 낼 수 없다.  ``FORBIDDEN_ACTIONS`` 에 든 액션은
아예 부를 수 없게 막아 두었다.  덱을 새로 만들면 Anki 가 기본 설정을 붙이는데, 그것을
바꿔 줄 수는 없으므로 **새로 만든 덱을 계획에 실어 알린다**(``SyncPlan.created``).

동기화는 **덮어쓰기가 아니라 대조**다.  각 노트에 프로젝트가 부여한 안정 식별자를
``Key`` 필드로 심고, 그 값으로 찾아 없으면 추가하고 있으면 바뀐 필드만 갱신한다.
그래서 몇 번을 돌려도 중복이 생기지 않는다.  삭제는 하지 않는다 — 사람이 Anki 에서
직접 지운 것을 되살려 놓지 않기 위해서다.
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.error
import urllib.request
from typing import Any, Iterable

DEFAULT_ENDPOINT = "http://127.0.0.1:8765"
KEY_FIELD = "Key"
# 노트가 어느 하위 덱에 놓일지.  Anki 필드가 아니라 동기화용 표식이다.
DECK_FIELD = "__deck__"

# **학습 설정은 이 프로젝트의 것이 아니다.**
#
# 사전 설정(하루 새 카드 수, 복습 상한, 간격 배수 …)은 사람이 자기 리듬에 맞춰
# 정해 둔 것이고, 데이터에서 다시 만들어 낼 수 없다.  덱을 만들고 카드를 옮기는 일과
# 학습 설정을 정하는 일은 별개이므로, 후자는 **코드가 아예 할 수 없게 막는다.**
#
# 실수로 부르는 것을 막는 것이지 사람을 막는 것이 아니다 — 사람은 Anki 에서 바꾼다.
FORBIDDEN_ACTIONS = frozenset({
    "saveDeckConfig",        # 사전 설정의 값을 바꾼다
    "setDeckConfigId",       # 덱에 붙은 사전 설정을 갈아 끼운다
    "cloneDeckConfigId",     # 사전 설정을 복제해 새로 만든다
    "removeDeckConfigId",    # 사전 설정을 지운다
    "updateCompleteDeck",    # 덱을 통째로 덮어쓴다 — 설정과 학습 이력을 함께 날린다
    "setSpecificValueOfCard",
    "forgetCards",           # 학습 이력을 지운다
    "relearnCards",
    "setDueDate",
})


class AnkiUnavailable(RuntimeError):
    """Anki 가 떠 있지 않거나 AnkiConnect 가 응답하지 않는다."""


class AnkiError(RuntimeError):
    """AnkiConnect 가 오류를 돌려주었다."""


class AnkiForbidden(RuntimeError):
    """이 프로젝트가 하지 않기로 한 일이다.  ``FORBIDDEN_ACTIONS`` 참조."""


class Anki:
    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, timeout: int = 30):
        self.endpoint = endpoint
        self.timeout = timeout

    def __call__(self, action: str, **params) -> Any:
        if action in FORBIDDEN_ACTIONS:
            raise AnkiForbidden(
                f"{action} 는 학습 설정이나 학습 이력을 건드린다. "
                "이 프로젝트는 노트와 카드의 배치만 다룬다 — 그것은 Anki 에서 사람이 정한다.")
        payload = json.dumps(
            {"action": action, "version": 6, "params": params}).encode()
        request = urllib.request.Request(
            self.endpoint, data=payload,
            headers={"Content-Type": "application/json"})
        try:
            raw = urllib.request.urlopen(request, timeout=self.timeout).read()
        except (urllib.error.URLError, OSError) as error:
            raise AnkiUnavailable(
                "Anki 에 연결할 수 없다. Anki 를 실행하고 AnkiConnect 애드온"
                f"(2055492159)이 설치되어 있는지 확인한다. ({error})") from error
        body = json.loads(raw.decode("utf-8"))
        if body.get("error"):
            raise AnkiError(f"{action}: {body['error']}")
        return body["result"]

    # ---------- 상태 ----------

    def available(self) -> bool:
        try:
            self("version")
            return True
        except (AnkiUnavailable, AnkiError):
            return False

    def deck_names(self) -> list[str]:
        return self("deckNames")

    def model_names(self) -> list[str]:
        return self("modelNames")

    # ---------- 스키마 ----------

    def ensure_deck(self, name: str) -> bool:
        """없으면 만든다.  **만들었으면 True 를 낸다.**

        Anki 에서 새로 만들어진 덱은 언제나 **기본 사전 설정**을 쓴다.  프로젝트가
        그것을 바꿔 줄 수는 없으므로(설정은 사람의 것이다), 대신 '새로 생겼다' 는
        사실을 돌려주어 동기화 결과에 실어 보낸다.  사람이 그 덱만 골라 자기 설정을
        붙이면 된다.
        """
        if name in self.deck_names():
            return False
        self("createDeck", deck=name)
        return True

    def ensure_model(self, spec: "NoteTypeSpec") -> None:
        """노트 타입을 만들거나, 이미 있으면 제자리에서 맞춘다.

        **필드는 덧셈만 한다.**  기존 필드를 지우거나 이름을 바꾸지 않는다 — Anki
        에서 필드를 지우면 그 내용이 사라지기 때문이다.

        **템플릿과 CSS 는 프로젝트가 낸다.**  카드의 생김새는 덱의 ``card.js`` ·
        ``card.css`` 에서 만들어지므로, 그것이 바뀌면 노트 타입도 따라가야 한다.
        따라가지 않으면 화면과 Anki 가 어긋나는데 그것이 정확히 이 프로젝트가
        피하려는 상태다.  카드 **이름**은 그대로 두므로 카드와 학습 이력은
        그대로 남고, 계획에 없는 카드 템플릿도 지우지 않는다.
        """
        if spec.name not in self.model_names():
            self("createModel",
                 modelName=spec.name,
                 inOrderFields=list(spec.fields),
                 css=spec.css,
                 cardTemplates=[{"Name": t.name, "Front": t.front, "Back": t.back}
                                for t in spec.templates])
            return
        existing = self("modelFieldNames", modelName=spec.name)
        for index, field in enumerate(spec.fields):
            if field not in existing:
                self("modelFieldAdd", modelName=spec.name, fieldName=field,
                     index=index)
        self.sync_templates(spec)

    def template_drift(self, spec: "NoteTypeSpec") -> list[str]:
        """선언과 다른 카드 템플릿·CSS 의 이름.  **아무것도 바꾸지 않는다.**

        노트 필드가 그대로여도 카드가 옛 모습일 수 있다 — Anki 에서 실행 취소를
        누르면 노트 타입 갱신만 되돌아간다.  그때 '반영할 것 없음' 으로 보이면
        사람이 알 길이 없으므로, 계획에 이것도 함께 세워 보여 준다.
        """
        if spec.name not in self.model_names():
            return ["새 노트 타입"]
        current = self("modelTemplates", modelName=spec.name)
        drift = [t.name for t in spec.templates
                 if current.get(t.name) != {"Front": t.front, "Back": t.back}]
        if self("modelStyling", modelName=spec.name).get("css") != spec.css:
            drift.append("css")
        return drift

    def sync_templates(self, spec: "NoteTypeSpec") -> list[str]:
        """템플릿과 CSS 가 선언과 다르면 맞춘다.  같으면 아무것도 보내지 않는다."""
        changed: list[str] = []
        current = self("modelTemplates", modelName=spec.name)
        wanted = {t.name: {"Front": t.front, "Back": t.back} for t in spec.templates}
        stale = {name: faces for name, faces in wanted.items()
                 if current.get(name) != faces}
        if stale:
            self("updateModelTemplates",
                 model={"name": spec.name, "templates": stale})
            changed.extend(sorted(stale))
        if self("modelStyling", modelName=spec.name).get("css") != spec.css:
            self("updateModelStyling", model={"name": spec.name, "css": spec.css})
            changed.append("css")
        return changed

    # ---------- 노트 ----------

    def find_by_key(self, model: str, key: str) -> list[int]:
        return self("findNotes", query=f'"note:{model}" "{KEY_FIELD}:{escape(key)}"')

    def existing_keys(self, model: str) -> dict[str, int]:
        """그 노트 타입의 ``Key`` → note id 전부.  한 번에 받아 왕복을 줄인다."""
        ids = self("findNotes", query=f'"note:{model}"')
        if not ids:
            return {}
        found: dict[str, int] = {}
        for info in self("notesInfo", notes=ids):
            key = info["fields"].get(KEY_FIELD, {}).get("value", "")
            if key:
                found[key] = info["noteId"]
        return found

    def card_decks(self, note_ids: Iterable[int],
                   batch: int = 500) -> dict[int, list[tuple[int, int, str]]]:
        """노트마다 그 카드들이 **몇 번째 카드로** 지금 어느 덱에 있는지.

        ``ord`` 가 필요하다.  한 노트의 카드들이 서로 다른 덱에 놓이기 때문이다 —
        읽기 카드는 읽기 덱에, 쓰기 카드는 쓰기 덱에 간다.  몇 번째 카드인지를
        알아야 어느 덱으로 가야 하는지 정할 수 있다.

        ``nid:1 or nid:2 …`` 로 이으면 Anki 의 SQLite 가 식 깊이 한계(1000)에 걸린다.
        쉼표 목록(``nid:1,2,3``)을 쓰고 그마저도 나누어 보낸다.
        """
        note_ids = list(note_ids)
        found: dict[int, list[tuple[int, int, str]]] = {}
        for start in range(0, len(note_ids), batch):
            group = note_ids[start:start + batch]
            ids = self("findCards",
                       query="nid:" + ",".join(str(note) for note in group))
            if not ids:
                continue
            for card in self("cardsInfo", cards=ids):
                found.setdefault(card["note"], []).append(
                    (card["cardId"], card["ord"], card["deckName"]))
        return found

    def move_cards(self, card_ids: list[int], deck: str) -> None:
        if card_ids:
            self("changeDeck", cards=card_ids, deck=deck)

    def notes_fields(self, ids: Iterable[int]) -> dict[int, dict[str, str]]:
        ids = list(ids)
        if not ids:
            return {}
        return {info["noteId"]: {n: f["value"] for n, f in info["fields"].items()}
                for info in self("notesInfo", notes=ids)}


def escape(value: str) -> str:
    """Anki 검색 문법에서 특별한 뜻을 갖는 문자를 막는다."""
    return re.sub(r'([\\":*_()])', r"\\\1", value)


def nfc_safe(value: str) -> str:
    """NFC 정규화로 사라질 글자를 수치 문자 참조로 바꾼다.

    Anki 는 필드를 저장할 때 NFC 로 정규화한다.  그런데 이체자 62 자는 CJK 호환
    한자(U+F900–U+FAFF)여서 NFC 를 거치면 통합 한자로 접혀 버린다 — ``逸``
    (U+FA67) 이 ``逸`` (U+9038) 이 되는 식이다.  자형 구분이 이체자 필드의 존재
    이유이므로 그대로 보낼 수 없다.

    ``&#xFA67;`` 로 실으면 저장되는 글자는 ASCII 뿐이라 정규화가 건드리지 않고,
    Anki 의 렌더러(브라우저)가 원래 자형으로 그려 준다.  덤으로 동기화가 멱등해진다.
    """
    if unicodedata.is_normalized("NFC", value):
        return value
    return "".join(
        character if unicodedata.is_normalized("NFC", character)
        else f"&#x{ord(character):04X};"
        for character in value
    )


class CardTemplate:
    def __init__(self, name: str, front: str, back: str):
        self.name = name
        self.front = front
        self.back = back


class NoteTypeSpec:
    """한 노트 타입의 전부 — 필드 순서, 카드 템플릿, CSS."""

    def __init__(self, name: str, fields: list[str],
                 templates: list[CardTemplate], css: str = ""):
        if KEY_FIELD not in fields:
            raise ValueError(f"노트 타입 {name!r} 에 {KEY_FIELD} 필드가 있어야 한다")
        self.name = name
        self.fields = fields
        self.templates = templates
        self.css = css


class SyncPlan:
    """반영 전에 사람이 볼 수 있는 변경 계획."""

    def __init__(self):
        self.add: list[dict[str, str]] = []
        self.update: list[tuple[int, dict[str, str], dict[str, str]]] = []
        self.unchanged = 0
        # 이미 있는 노트인데 카드가 다른 덱에 놓여 있는 것 — (카드 id, 가야 할 덱)
        self.relocate: list[tuple[int, str]] = []
        # Anki 에만 있고 이 계획에는 없는 Key.  **지우지 않는다** — 사람이 보고
        # 판단할 수 있도록 세어서 보여 주기만 한다(식별자 규칙을 바꾸면 옛 노트가
        # 여기에 남는다).
        self.stale: list[str] = []
        # 이번 반영에서 **새로 만들어진 덱.**  새 덱은 언제나 기본 사전 설정을 쓰므로
        # 사람이 자기 설정을 붙여야 한다는 사실을 알려야 한다.
        self.created: list[str] = []

    @property
    def total(self) -> int:
        return len(self.add) + len(self.update) + len(self.relocate)

    def summary(self) -> dict[str, int]:
        return {"add": len(self.add), "update": len(self.update),
                "move": len(self.relocate), "unchanged": self.unchanged,
                "stale": len(self.stale), "new_decks": len(self.created)}


def card_names(model) -> list[str]:
    """노트 타입의 카드 이름을 **순서대로**.  그 순서가 곧 카드의 ``ord`` 다."""
    return [template.name for template in getattr(model, "templates", [])]


def model_name(model) -> str:
    return getattr(model, "name", model)


def deck_of(placement, cards: list[str], ordinal: int, default: str) -> str:
    """몇 번째 카드가 어느 덱으로 가는가.

    ``__deck__`` 이 문자열이면 그 노트의 카드 전부가 한 덱에 간다.  사전이면
    **카드마다 덱이 다르다** — 한자의 읽기 카드와 쓰기 카드가 그렇다.  학습은
    방향별로 진도가 다르므로 덱도 방향별로 갈라져야 한다.
    """
    if isinstance(placement, dict):
        name = cards[ordinal] if 0 <= ordinal < len(cards) else ""
        return placement.get(name) or default
    return placement or default


def decks_in(placement, default: str) -> set[str]:
    """그 노트가 쓰는 덱 전부.  미리 만들어 두어야 할 것들이다."""
    if isinstance(placement, dict):
        return {value or default for value in placement.values()} or {default}
    return {placement or default}


def plan_sync(anki: Anki, model, notes: list[dict[str, str]],
              default_deck: str = "") -> SyncPlan:
    """``notes`` 를 Anki 의 현재 상태와 대조해 계획을 만든다.  아무것도 바꾸지 않는다.

    노트가 ``__deck__`` 을 지고 있으면 그 하위 덱에 놓여야 한다.  이미 있는 노트라도
    카드가 다른 덱에 있으면 옮길 목록에 올린다 — 덱 구조를 바꾼 뒤에도 기존 노트가
    제자리를 찾아가야 하기 때문이다.

    ``model`` 은 노트 타입 선언(``NoteTypeSpec``)이거나 그 이름이다.  카드마다 덱이
    다른 덱(읽기/쓰기)은 카드 이름을 알아야 하므로 선언을 넘긴다.
    """
    plan = SyncPlan()
    cards = card_names(model)
    model = model_name(model)
    # 보내는 값과 저장될 값을 같은 형태로 맞춘 뒤에 비교해야 멱등해진다.
    # ``__deck__`` 은 Anki 필드가 아니라 동기화용 표식이므로 손대지 않는다 —
    # 카드마다 덱이 다르면 문자열이 아니라 사전이기도 하다.
    notes = [{name: value if name == DECK_FIELD else nfc_safe(value)
              for name, value in note.items()}
             for note in notes]
    # 키가 겹치면 Anki 가 통째로 거절한다.  덱 쪽 실수를 여기서 먼저 잡는다.
    keys = [note.get(KEY_FIELD, "") for note in notes]
    if len(set(keys)) != len(keys):
        seen, collided = set(), []
        for key in keys:
            if key in seen and key not in collided:
                collided.append(key)
            seen.add(key)
        raise ValueError(
            f"{KEY_FIELD} 가 겹친다 ({len(collided)}건): {collided[:5]}")
    known = anki.existing_keys(model)
    wanted_ids = [known[n[KEY_FIELD]] for n in notes if n.get(KEY_FIELD) in known]
    current = anki.notes_fields(wanted_ids)
    placement = anki.card_decks(wanted_ids) if wanted_ids else {}
    for note in notes:
        key = note.get(KEY_FIELD)
        if not key:
            raise ValueError(f"{KEY_FIELD} 없는 노트: {note}")
        wanted = note.get(DECK_FIELD) or default_deck
        fields = {name: value for name, value in note.items() if name != DECK_FIELD}
        note_id = known.get(key)
        if note_id is None:
            plan.add.append({**fields, DECK_FIELD: wanted})
            continue
        before = current.get(note_id, {})
        changed = {name: value for name, value in fields.items()
                   if before.get(name, "") != value}
        misplaced = []
        for card, ordinal, deck in placement.get(note_id, []):
            target = deck_of(wanted, cards, ordinal, default_deck)
            if target and deck != target:
                misplaced.append(card)
                plan.relocate.append((card, target))
        if changed:
            plan.update.append((note_id, changed, before))
        elif not misplaced:
            plan.unchanged += 1
    plan.stale = sorted(set(known) - set(keys))
    return plan


def place_new(anki: Anki, made: list, notes: list[dict], cards: list[str],
              default: str, batch: int = 400) -> None:
    """방금 만든 노트의 카드를 카드마다 제 덱으로 보낸다.

    노트 하나를 만들 때 덱은 하나만 고를 수 있으므로, 카드마다 덱이 다른 덱에서는
    만든 **직후에** 옮겨야 한다.  다음 동기화까지 미루면 사람이 두 번 눌러야 한다.
    """
    wanted: dict[str, list[int]] = {}
    made_ids = [note_id for note_id in made if note_id]
    if not made_ids or not cards:
        return
    placement = anki.card_decks(made_ids)
    by_id = {note_id: note for note_id, note in zip(made, notes) if note_id}
    for note_id, note in by_id.items():
        for card, ordinal, deck in placement.get(note_id, []):
            target = deck_of(note.get(DECK_FIELD), cards, ordinal, default)
            if target and deck != target:
                wanted.setdefault(target, []).append(card)
    for target, group in wanted.items():
        for start in range(0, len(group), batch):
            anki.move_cards(group[start:start + batch], target)


def apply_sync(anki: Anki, deck: str, model, plan: SyncPlan,
               batch: int = 400, progress=None) -> dict[str, int]:
    """계획을 실제로 반영한다.  추가·갱신·이동만 하고 **삭제는 하지 않는다**.

    한 번에 몰아 보내면 Anki 가 오래 멈추므로 나누어 보낸다.
    """
    cards = card_names(model)
    model = model_name(model)

    # 새 노트가 놓일 하위 덱을 **먼저 만든다.**  Anki 는 없는 덱으로 보낸 배치를
    # 통째로 거절한다.  이동 대상만 만들고 추가 대상을 빠뜨리면, 하위 덱 이름을
    # 바꾼 뒤 첫 동기화가 그대로 실패한다.
    for note in plan.add:
        for target in sorted(decks_in(note.get(DECK_FIELD), deck)):
            if anki.ensure_deck(target):
                plan.created.append(target)

    added = 0
    for start in range(0, len(plan.add), batch):
        group = plan.add[start:start + batch]
        payload = []
        for note in group:
            fields = {n: v for n, v in note.items() if n != DECK_FIELD}
            payload.append({
                # 노트를 만들 때 덱은 하나만 고를 수 있다.  첫 카드의 덱으로 만들고,
                # 나머지 카드는 바로 아래에서 제 덱으로 보낸다.
                "deckName": deck_of(note.get(DECK_FIELD), cards, 0, deck),
                "modelName": model,
                "fields": fields,
                "options": {"allowDuplicate": False},
                "tags": ["SP"],
            })
        made = anki("addNotes", notes=payload) or []
        place_new(anki, made, group, cards, deck, batch)
        added += len(group)
        if progress:
            progress("add", added, len(plan.add))

    for index, (note_id, changed, _before) in enumerate(plan.update, 1):
        anki("updateNoteFields", note={"id": note_id, "fields": changed})
        if progress and index % batch == 0:
            progress("update", index, len(plan.update))

    # 덱 구조가 바뀌면 이미 있던 카드도 제자리를 찾아가야 한다.
    by_deck: dict[str, list[int]] = {}
    for card, target in plan.relocate:
        by_deck.setdefault(target, []).append(card)
    for target, cards in by_deck.items():
        if anki.ensure_deck(target):
            plan.created.append(target)
        for start in range(0, len(cards), batch):
            anki.move_cards(cards[start:start + batch], target)
        if progress:
            progress("move", len(cards), len(plan.relocate))
    return plan.summary()


def sync_spec(anki: Anki, spec, payload) -> list[dict]:
    """덱 하나를 통째로 반영한다 — 덱·노트 타입을 맞추고 노트 타입마다 대조·반영.

    **부르는 곳이 둘이다.**  파이프라인의 마지막 걸음(``python -m app sync``)과
    편집기의 Anki 블록이 같은 이 함수를 쓴다.  둘이 갈라지면 '화면으로 반영한
    것' 과 '파이프라인이 반영한 것' 이 달라지는데, 그것을 알아차릴 방법이 없다.
    """
    done = []
    anki.ensure_deck(spec.anki_deck)
    for group in spec.anki_notes:
        notes = group.build(payload)
        anki.ensure_model(group.note_type)
        # 노트 타입 선언을 그대로 넘긴다 — 카드마다 덱이 다른 덱은 카드 이름을
        # 알아야 어느 덱으로 보낼지 정할 수 있다.
        plan = plan_sync(anki, group.note_type, notes, spec.anki_deck)
        result = apply_sync(anki, spec.anki_deck, group.note_type, plan)
        done.append({"note_type": group.note_type.name, "deck": spec.anki_deck,
                     "result": result})
    return done
