# -*- coding: utf-8 -*-
"""한자 덱의 계약.

읽기 카드와 쓰기 카드는 **한 노트에서 나오는 두 장의 카드**다.

Anki 카드의 생김새는 **프론트엔드 카드와 같다** — 같은 것을 보고 배워야 하기
때문이다.  같게 만드는 방법은 하나뿐이다: 같은 것으로 그린다.  노트는 레코드
자체를 ``Data`` 필드에 싣고, ``static/card.js`` 와 ``static/card.css`` 가 화면과
Anki 를 **함께** 그린다(``shared/ankicard.py``).

그래서 파이썬이 하던 일이 두 가지 사라졌다.  카드 HTML 을 미리 만들어 ``Body``
에 넣던 일과, 쓰기 앞면을 위해 '정답 한자를 가린 본문' 을 따로 만들던 일이다.
가리기는 이제 화면에서와 똑같이 CSS 가 한다 — 정답 한자는 ``answer-char`` 로
감싸이고 ``.writing-front`` 가 그것을 감춘다.
"""
from __future__ import annotations

from shared.anki import DECK_FIELD
from shared.ankicard import build_note_type, envelope, pack
from shared.deckspec import AnkiNotes, DeckSpec
from shared.paths import DeckPaths

from .model import (
    index_row,
    ordered_record,
    payload_statistics,
    project_record,
    validate_payload,
    validate_record,
)
from .pipeline.ordering import sort_record

PATHS = DeckPaths("kanji")
ANKI_DECK = "한자"

# 학년·구분별 하위 덱.  Anki 는 하위 덱을 **이름순**으로만 늘어놓고 사람이 그 순서를
# 바꿀 방법이 없다.  그래서 학습 순서를 이름 앞의 번호로 고정한다 — `1. 소학교 1학년`.
SUBDECKS = [
    ("s1", "소학교 1학년"), ("s2", "소학교 2학년"), ("s3", "소학교 3학년"),
    ("s4", "소학교 4학년"), ("s5", "소학교 5학년"), ("s6", "소학교 6학년"),
    ("j", "상용한자"), ("h", "표외한자"),
]
SUBDECK_NAME = {tag: f"{index}. {label}"
                for index, (tag, label) in enumerate(SUBDECKS, 1)}

# **방향이 먼저다.**  읽기와 쓰기는 진도가 다르므로 덱도 갈라져야 한다.  같은 노트의
# 두 카드가 서로 다른 덱으로 가므로, 노트는 '카드 이름 -> 덱' 을 지고 다닌다.
CARD_DECKS = {"읽기": "1. 읽기", "쓰기": "2. 쓰기"}


def subdeck(tag: str) -> dict[str, str]:
    leaf = SUBDECK_NAME.get(tag, "9. 기타")
    return {card: f"{ANKI_DECK}::{group}::{leaf}"
            for card, group in CARD_DECKS.items()}


def build_notes(payload: dict) -> list[dict[str, str]]:
    """한자 하나가 노트 하나.  카드를 그리는 것은 ``Data`` 한 필드다."""
    notes = []
    for character, record in payload.items():
        korean = " · ".join(
            value for values in record.get("korean", {}).values() for value in values)
        notes.append({
            "Key": f"kanji:{character}",
            "Kanji": character,
            "Korean": korean,
            # 이체자는 자형이 구분의 이유다.  NFC 로 접히지 않도록 plan_sync 의
            # nfc_safe 가 수치 문자 참조로 바꾼다.  Data 는 base64 라 그럴 필요가 없다.
            "Variants": " · ".join(record.get("variant", {})),
            "Tag": record.get("tag", ""),
            "Data": pack(envelope(character, record)),
            DECK_FIELD: subdeck(record.get("tag", "")),
        })
    return notes


# ---------------------------------------------------------------------------
# Anki — 카드는 프론트엔드 렌더러가 그린다
# ---------------------------------------------------------------------------

RENDERER = "KanjiCard"

# 편집기의 모드 탭과 **같은 문자열**이다.  그 문자열이 곧 카드 요소의 클래스이고,
# 무엇을 가릴지는 static/card.css 가 그 클래스로 정한다.
MODES = [("reading-front", "읽기 앞면"), ("reading-back", "읽기 뒷면"),
         ("writing-front", "쓰기 앞면"), ("writing-back", "쓰기 뒷면")]

CARDS = [("읽기", "reading-front", "reading-back"),
         ("쓰기", "writing-front", "writing-back")]

NOTE_TYPE = build_note_type(
    name="SP 한자",
    # ``Data`` 가 카드를 그리고, 나머지는 사람이 Anki 브라우저에서 찾기 위한 것이다.
    fields=["Key", "Kanji", "Korean", "Variants", "Tag", "Data"],
    static_dir=PATHS.static,
    renderer=RENDERER,
    cards=CARDS,
    # 필기판은 쓰기 카드의 알맹이다.  손으로 써 보지 않으면 쓰기 연습이 아니다.
    # Anki 에는 획을 남길 곳이 없으므로 카드를 넘기면 지워지지만, 그것으로 족하다 —
    # 필요한 것은 '지금 이 한 자를 손으로 써 보는 일' 이다.
)


DECK = DeckSpec(
    name="kanji",
    title="한자",
    data_path=PATHS.data / "data_japanese.json",
    record_label="한자 한 자",
    validate_record=validate_record,
    validate_payload=validate_payload,
    sort_record=sort_record,
    project_record=project_record,
    statistics=payload_statistics,
    index_row=index_row,
    order_record=ordered_record,
    search_priorities={"key": 0, "variant": 1, "word": 2,
                       "korean": 3, "reading": 3, "exception": 3},
    static_dir=PATHS.static,
    renderer=RENDERER,
    modes=MODES,
    anki_deck=ANKI_DECK,
    anki_notes=[AnkiNotes(NOTE_TYPE, build_notes)],
)
