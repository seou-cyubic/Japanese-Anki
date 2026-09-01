# -*- coding: utf-8 -*-
"""토익 덱의 계약.

**레코드 하나(영어 낱말 하나)가 노트 하나다.**  한 낱말의 여러 뜻은 나란히 놓고
견주어야 '이 낱말이 어떤 자리에 쓰이는가' 가 보인다 — 한자 덱의 요미카타, 문법 덱의
읽기 카드와 같은 이유다.

카드의 생김새는 여기서 만들지 않는다.  ``static/card.js`` 와 ``static/card.css`` 가
화면과 Anki 를 **함께** 그린다 — 노트는 레코드 그 자체를 ``Data`` 필드에 싣고 갈
뿐이다(``shared/ankicard.py``).
"""
from __future__ import annotations

import json

from shared.anki import DECK_FIELD
from shared.ankicard import build_note_type, envelope, pack
from shared.deckspec import AnkiNotes, DeckSpec
from shared.furigana import plain_surface
from shared.paths import DeckPaths

from .model import (
    BAND_LABELS,
    index_row,
    ordered_record,
    payload_statistics,
    project_record,
    sort_record,
    validate_payload,
    validate_record,
)

PATHS = DeckPaths("toeic")
DATA_PATH = PATHS.data / "toeic_japanese.json"
ANKI_DECK = "토익"

# 빈도대별 하위 덱.  Anki 는 하위 덱을 **이름순**으로만 늘어놓고 사람이 그 순서를
# 바꿀 방법이 없으므로, 학습 순서(자주 쓰는 것부터)를 이름 앞의 번호로 고정한다.
BAND_ORDER = {"1-1000": 1, "1001-2000": 2, "2001-2809": 3, "TSL": 4}

# **방향이 먼저다.**  뜻(영→일)과 철자(일→영)는 진도가 다르므로 덱도 갈라진다.
# 노트 하나가 카드 둘을 내므로 표식은 '카드 이름 -> 덱' 의 사전이다.
CARD_DECKS = {"뜻": "1. 뜻", "철자": "2. 철자"}


def subdeck(band: str) -> dict[str, str]:
    leaf = f"{BAND_ORDER.get(band, 9)}. {BAND_LABELS.get(band, band or '미분류')}"
    return {card: f"{ANKI_DECK}::{group}::{leaf}"
            for card, group in CARD_DECKS.items()}


def load_payload():
    with DATA_PATH.open(encoding="utf-8") as stream:
        return json.load(stream)


def search_text(record: dict) -> str:
    """Anki 브라우저에서 찾기 위한 평문.

    ``Data`` 는 base64 라 검색이 걸리지 않는다.  카드에 쓰이지는 않지만 사람이 노트를
    찾을 때 필요하므로 후리가나를 뗀 일본어와 뜻풀이를 한 줄씩 남긴다.
    """
    lines = []
    for sense in record.get("senses", []):
        lines.append(plain_surface(sense.get("ja", "")))
        if sense.get("gloss"):
            lines.append(sense["gloss"])
    return "<br>".join(line for line in lines if line)


def build_notes(payload) -> list[dict[str, str]]:
    """낱말 하나가 노트 하나.  카드를 그리는 것은 ``Data`` 한 필드다."""
    notes = []
    for word, record in payload.items():
        senses = record.get("senses", [])
        notes.append({
            "Key": f"toeic:{word}",
            "Word": word,
            "Japanese": " · ".join(plain_surface(s.get("ja", "")) for s in senses),
            "Band": BAND_LABELS.get(record.get("band", ""), ""),
            "Rank": str(record.get("rank", "")),
            "Text": search_text(record),
            # 카드를 그리는 것은 이 한 필드다.  화면이 받는 것과 같은 봉투다.
            "Data": pack(envelope(word, record)),
            DECK_FIELD: subdeck(record.get("band", "")),
        })
    return notes


# ---------------------------------------------------------------------------
# Anki — 카드는 프론트엔드 렌더러가 그린다
# ---------------------------------------------------------------------------

RENDERER = "ToeicCard"

# 편집기의 모드 탭과 **같은 문자열**이다.  그 문자열이 곧 카드 요소의 클래스이고,
# 무엇을 가릴지는 static/card.css 가 그 클래스로 정한다.
MODES = [("reading-front", "뜻 앞면"), ("reading-back", "뜻 뒷면"),
         ("spell-front", "철자 앞면"), ("spell-back", "철자 뒷면")]

CARDS = [("뜻", "reading-front", "reading-back"),
         ("철자", "spell-front", "spell-back")]

NOTE_TYPE = build_note_type(
    name="SP 토익",
    # ``Data`` 가 카드를 그리고, 나머지는 사람이 Anki 브라우저에서 찾기 위한 것이다.
    fields=["Key", "Word", "Japanese", "Band", "Rank", "Text", "Data"],
    static_dir=PATHS.static,
    renderer=RENDERER,
    cards=CARDS,
    # 검증 등급 뱃지는 편집기의 진단이다.  학습 카드에는 띄우지 않는다.
    options={"diagnostics": False},
)


DECK = DeckSpec(
    name="toeic",
    title="토익",
    data_path=DATA_PATH,
    record_label="영어 낱말 하나",
    validate_record=validate_record,
    validate_payload=validate_payload,
    sort_record=sort_record,
    project_record=project_record,
    statistics=payload_statistics,
    index_row=index_row,
    order_record=ordered_record,
    search_priorities={"key": 0, "family": 1, "sense": 2,
                       "annotation": 2, "gloss": 3, "en": 3, "band": 4},
    static_dir=PATHS.static,
    renderer=RENDERER,
    modes=MODES,
    anki_deck=ANKI_DECK,
    anki_notes=[AnkiNotes(NOTE_TYPE, build_notes)],
    load_payload=load_payload,
)
