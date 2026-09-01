# -*- coding: utf-8 -*-
"""문법 덱의 계약.

**레코드 하나(문형 하나)가 노트 하나다.**  두 덱이 같다.  문형은 예문 서너 개를
나란히 놓고 볼 때 비로소 '어떤 자리에 쓰는 말인가' 가 보이는데, 예문을 한 장에
하나씩 흩어 놓으면 그 비교가 사라진다.  편집기가 문형 하나를 카드 한 장으로
보여 주는 이유도 같고, 그래서 Anki 카드도 같은 모양이어야 한다.

카드의 생김새는 여기서 만들지 않는다.  ``static/card.js`` 와 ``static/card.css``
가 화면과 Anki 를 **함께** 그린다 — 노트는 레코드 그 자체를 ``Data`` 필드에 싣고
갈 뿐이다.  ``shared/ankicard.py`` 참조.
"""
from __future__ import annotations

import json
import re

from decks.bunpo.pipeline.marking import groups as marking_groups
from decks.kanji.model import record_etag
from shared.anki import DECK_FIELD
from shared.ankicard import build_note_type, envelope, pack
from shared.deckspec import AnkiNotes, DeckSpec
from shared.paths import DeckPaths

PATHS = DeckPaths("bunpo")
DATA_PATH = PATHS.data / "bunpo_korean.json"

MARK = "*"
ANKI_DECK = "문법"

# 원전은 옛 JLPT 급수(1~4級)로 표시한다.  현행 N 등급과의 대응은 공식 안내를 따른다 —
# 4級=N5, 3級=N4, 2級=N2, 1級=N1.  N3 는 2級과 3級 사이를 메우려고 뒤에 신설된
# 등급이라 옛 표기에는 대응이 없다.
LEVEL_LABEL = {"4": "N5", "3": "N4", "2": "N2", "1": "N1"}
# Anki 는 하위 덱을 이름순으로만 늘어놓는다.  쉬운 것부터 나오도록 번호로 고정한다.
LEVEL_ORDER = {"N5": 1, "N4": 2, "N3": 3, "N2": 4, "N1": 5}

# **방향이 먼저다.**  읽기와 작문은 진도도 학습 단위도 다르므로 덱이 갈라진다.
READING_GROUP = "1. 읽기"
COMPOSE_GROUP = "2. 작문"


def subdeck(level_label: str, group: str) -> str:
    """급수 하위 덱.

    원전에 없는 급수의 하위 덱은 **만들지 않는다.**  N3 가 그렇다 — 현행 N3 는
    옛 2級과 3級 사이를 메우려고 뒤에 신설된 등급이라 옛 표기에 대응이 없다.
    """
    leaf = (f"{LEVEL_ORDER.get(level_label, 9)}. {level_label}"
            if level_label else "9. 미분류")
    return f"{ANKI_DECK}::{group}::{leaf}"


def split_marked(marked: str) -> tuple[str, str, str]:
    """``앞*문법*뒤`` 를 셋으로 가른다.  표시가 없으면 가운데가 빈다."""
    parts = marked.split(MARK)
    if len(parts) >= 3:
        return parts[0], parts[1], MARK.join(parts[2:])
    return marked, "", ""


def mark_offsets(marked: str) -> list[int]:
    """표시를 걷어 낸 예문 기준으로 두 별표가 놓인 자리."""
    first = marked.find(MARK)
    if first < 0:
        return []
    second = marked.find(MARK, first + 1)
    if second < 0:
        return []
    return [first, second - 1]


def group_edges(annotated: str) -> set[int]:
    """``漢字런(よみ)`` 덩이의 바깥 경계.  표시가 놓일 수 있는 자리다."""
    edges = {0, len(annotated)}
    for _surface, _reading, start, stop in marking_groups(annotated):
        edges.add(start)
        edges.add(stop)
    return edges


def card_derived(record: dict) -> dict:
    """봉투에 실을 파생값.  **렌더러가 실제로 읽는 것만** 담는다.

    편집기는 서버가 계산해 준 ``derived`` 를 통째로 넘기지만 문법 렌더러가 거기서
    읽는 것은 급수 표기 하나뿐이다.  옛 급수(1~4級)와 현행 N 등급의 대응은
    ``LEVEL_LABEL`` 한 곳에서만 정하므로 화면이든 Anki 든 여기를 거친다.
    """
    return {"level": LEVEL_LABEL.get(record.get("level", ""), "")}


def search_text(record: dict) -> str:
    """Anki 브라우저에서 예문으로 찾을 수 있게 하는 평문.

    ``Data`` 는 base64 라 검색이 걸리지 않는다.  카드에 쓰이지는 않지만 사람이
    노트를 찾을 때 필요하므로 후리가나를 뗀 예문과 해석을 한 줄씩 남긴다.
    """
    lines = []
    for example in record.get("examples", []):
        lines.append(plain_of(example.get("ja", "")))
        if example.get("ko"):
            lines.append(example["ko"])
    return "<br>".join(lines)


def build_notes(payload) -> list[dict[str, str]]:
    """**읽기 노트** — 문형 하나가 노트 하나.

    예문을 나란히 놓고 견주어야 '어떤 자리에 쓰는 말인가' 가 보이므로, 읽기 카드는
    문형 하나에 예문 전부를 싣는다.

    식별자는 항목 키(``から`` / ``から#2``)다.  동형이의 항목이 64 개 있어 표제형
    만으로는 갈라지지 않으므로, ``marking.entry_keys`` 가 붙인 등장 순번을 그대로
    쓴다.  인쇄된 예문 번호는 식별자가 될 수 없다 — 원전에 오식이 있다
    (``くらい～はない`` 는 ①②②④ 로 인쇄되어 있다).
    """
    notes = []
    for entry_key, entry in payload.items():
        level = LEVEL_LABEL.get(entry.get("level", ""), "")
        notes.append({
            "Key": f"bunpo:{entry_key}",
            "Grammar": entry["head"],
            "Level": level,
            "Meaning": entry.get("gloss_ko", ""),
            "Connect": " / ".join(entry.get("connect", [])),
            "Note": entry.get("note_ko", ""),
            "Text": search_text(entry),
            # 카드를 그리는 것은 이 한 필드다.  화면이 받는 것과 같은 봉투다.
            "Data": pack(envelope(entry_key, entry, card_derived(entry))),
            DECK_FIELD: subdeck(level, READING_GROUP),
        })
    return notes


def one_example(entry: dict, position: int) -> dict:
    """항목을 예문 하나로 좁힌 레코드.

    작문 카드는 문장 하나를 짓는 연습이므로 한 장에 예문이 하나여야 한다.  레코드의
    모양은 그대로 두고 ``examples`` 만 그 하나로 줄인다 — 그래야 **같은 렌더러가
    손대지 않고** 그대로 그린다.
    """
    return {**entry, "examples": [entry["examples"][position - 1]]}


def build_compose_notes(payload) -> list[dict[str, str]]:
    """**작문 노트** — 예문 하나가 노트 하나.

    앞면은 어떤 문형을 쓰는지와 그 뜻, 그리고 예문의 한국어 해석만 보여 주고,
    일본어 문장은 뒤집어 확인한다.

    식별자는 항목 키와 예문 **위치**다.  인쇄된 번호는 쓸 수 없다 — 원전에 오식이
    있다(``くらい～はない`` 는 ①②②④ 로 인쇄되어 있다).
    """
    notes = []
    for entry_key, entry in payload.items():
        level = LEVEL_LABEL.get(entry.get("level", ""), "")
        for position, example in enumerate(entry["examples"], 1):
            record = one_example(entry, position)
            notes.append({
                "Key": f"bunpo:{entry_key}:{position}",
                "Grammar": entry["head"],
                "Level": level,
                "Meaning": entry.get("gloss_ko", ""),
                "Text": search_text(record),
                "Data": pack(envelope(entry_key, record, card_derived(entry))),
                DECK_FIELD: subdeck(level, COMPOSE_GROUP),
            })
    return notes


def load_payload():
    with DATA_PATH.open(encoding="utf-8") as stream:
        return json.load(stream)


# ---------------------------------------------------------------------------
# 데이터 계약
# ---------------------------------------------------------------------------

REQUIRED = ("head", "level", "gloss_ko", "examples")


def validate_record(key: str, record) -> list[str]:
    errors = []
    if not isinstance(record, dict):
        return [f"{key}: 항목은 object 여야 한다"]
    for field in REQUIRED:
        if field not in record:
            errors.append(f"{key}: 필수 필드 없음 — {field}")
    for index, example in enumerate(record.get("examples", [])):
        spot = f"{key}[{index}]"
        if not example.get("ja"):
            errors.append(f"{spot}: 예문이 비었다")
        marked = example.get("marked", "")
        if marked.count(MARK) not in (0, 2):
            errors.append(f"{spot}: 문법 표시가 짝을 이루지 않는다")
        if marked and marked.replace(MARK, "") != example.get("ja", ""):
            errors.append(f"{spot}: 표시를 걷으면 예문이 그대로 나와야 한다")
        elif marked.count(MARK) == 2:
            # **별표는 한자와 그 읽기 사이에 놓일 수 없다.**  ``*後*(あと)`` 처럼
            # 덩이 가운데를 끊으면 읽기가 걸릴 글자를 잃어 화면에서 허공에 뜬다.
            edges = group_edges(example.get("ja", ""))
            if any(offset not in edges for offset in mark_offsets(marked)):
                errors.append(f"{spot}: 문법 표시가 한자와 그 후리가나 사이를 끊는다")
    return errors


def validate_payload(payload) -> list[str]:
    if not isinstance(payload, dict):
        return ["문법 데이터 최상위는 object 여야 한다"]
    errors = []
    for key, entry in payload.items():
        errors.extend(validate_record(key, entry))
    return errors


def statistics(payload) -> dict:
    entries = list(payload.values())
    examples = [x for entry in entries for x in entry["examples"]]
    return {
        "records": len(entries),
        "examples": len(examples),
        "translated": sum(1 for x in examples if x.get("ko")),
        "marked": sum(1 for x in examples if x.get("mark_method")),
        "levels": {LEVEL_LABEL.get(level, level): sum(1 for e in entries
                                                      if e.get("level") == level)
                   for level in ("1", "2", "3", "4")},
    }


def index_row(key: str, record: dict) -> dict:
    """문형 하나를 검색 색인 한 줄로."""
    terms = [(key, "key", "표제형"), (record["head"], "head", "표제형")]
    level = LEVEL_LABEL.get(record.get("level", ""), "")
    if level:
        terms.append((level, "level", "급수"))
    for name, kind in (("gloss_ko", "meaning"), ("gloss_ja", "gloss"),
                       ("gloss_en", "gloss"), ("note_ko", "note")):
        if record.get(name):
            terms.append((record[name], kind, name))
    for shape in record.get("connect", []):
        terms.append((shape, "connect", "접속형"))
    for example in record["examples"]:
        marked = example.get("marked") or example["ja"]
        _b, grammar, _a = split_marked(marked)
        terms.append((plain_of(example["ja"]), "example", "예문"))
        terms.append((example["ja"], "annotation", "예문"))
        if example.get("ko"):
            terms.append((example["ko"], "translation", "해석"))
        if grammar:
            terms.append((plain_of(grammar), "span", "문법 구간"))
    return {
        "key": key,
        "title": record["head"],
        "subtitle": record.get("gloss_ko", ""),
        "weight": len(record["examples"]),
        "level": level,
        "examples": len(record["examples"]),
        "marked": sum(1 for x in record["examples"] if x.get("mark_method")),
        "_terms": terms,
    }


_RUBY = re.compile(r"\([^)]*\)")


def plain_of(annotated: str) -> str:
    """후리가나를 뗀 표기.  검색은 두 꼴 모두로 걸려야 한다."""
    return _RUBY.sub("", annotated)


def sort_record(record):
    """문법 예문은 원전의 등장 순서가 곧 학습 순서다.  다시 정렬하지 않는다."""
    return record


FIELD_ORDER = ("head", "page", "level", "gloss_ja", "gloss_en", "gloss_zh",
               "gloss_ko", "connect", "examples", "note_ja", "note_ko")


def order_record(record: dict) -> dict:
    """저장 파일의 필드 순서를 고정한다.  진단 diff 가 읽기 쉬워진다."""
    ordered = {name: record[name] for name in FIELD_ORDER if name in record}
    ordered.update({name: value for name, value in record.items()
                    if name not in ordered})
    return ordered


def project_record(key: str, record: dict, *, edited: bool) -> dict:
    """화면이 쓸 봉투.  한자 덱과 같은 모양이라 프론트엔드가 덱을 가리지 않는다."""
    examples = []
    for position, example in enumerate(record.get("examples", []), 1):
        marked = example.get("marked") or example.get("ja", "")
        _before, grammar, _after = split_marked(marked)
        examples.append({
            **example,
            "position": position,
            "span": grammar,
            "span_plain": plain_of(grammar),
            "plain": plain_of(example.get("ja", "")),
        })
    return {
        "schema_version": 1,
        "key": key,
        "record_etag": record_etag(record),
        "edited": edited,
        "record": record,
        "derived": {
            "head": record.get("head", ""),
            "level": LEVEL_LABEL.get(record.get("level", ""), ""),
            "meaning": record.get("gloss_ko", ""),
            "connect": record.get("connect", []),
            "note": record.get("note_ko", ""),
            "gloss_ja": record.get("gloss_ja", ""),
            "examples": examples,
            "unmarked": sum(1 for x in record.get("examples", [])
                            if not x.get("mark_method")),
        },
    }


# ---------------------------------------------------------------------------
# Anki — 카드는 프론트엔드 렌더러가 그린다
# ---------------------------------------------------------------------------

RENDERER = "BunpoCard"

# 편집기의 모드 탭과 **같은 문자열**이다.  그 문자열이 곧 카드 요소의 클래스이고,
# 무엇을 가릴지는 static/card.css 가 그 클래스로 정한다.
MODES = [("reading-front", "뜻 앞면"), ("reading-back", "뜻 뒷면"),
         ("produce-front", "작문 앞면"), ("produce-back", "작문 뒷면")]

# 편집기에서만 뜻이 있는 것.  문법 구간 미표시 경고는 학습 카드가 아니라 진단이다.
CARD_OPTIONS = {"diagnostics": False}

# 읽기: 일본어 예문을 보고 뜻을 떠올린다.  문형 하나에 예문 전부가 실린다.
READING_NOTE_TYPE = build_note_type(
    name="SP 문법",
    # ``Data`` 가 카드를 그리고, 나머지는 사람이 Anki 브라우저에서 찾기 위한 것이다.
    fields=["Key", "Grammar", "Level", "Meaning", "Connect", "Note", "Text", "Data"],
    static_dir=PATHS.static,
    renderer=RENDERER,
    cards=[("뜻", "reading-front", "reading-back")],
    options=CARD_OPTIONS,
)

# 작문: 한국어 해석을 보고 일본어 문장을 짓는다.  **예문 하나가 카드 한 장**이므로
# 노트 타입이 따로다 — 한 노트에서 나오는 카드 수는 카드 템플릿 수로 고정된다.
COMPOSE_NOTE_TYPE = build_note_type(
    name="SP 문법 작문",
    fields=["Key", "Grammar", "Level", "Meaning", "Text", "Data"],
    static_dir=PATHS.static,
    renderer=RENDERER,
    cards=[("작문", "produce-front", "produce-back")],
    options=CARD_OPTIONS,
)


DECK = DeckSpec(
    name="bunpo",
    title="문법",
    data_path=DATA_PATH,
    record_label="표현 문형 하나",
    validate_record=validate_record,
    validate_payload=validate_payload,
    sort_record=sort_record,
    project_record=project_record,
    statistics=statistics,
    index_row=index_row,
    order_record=order_record,
    search_priorities={'key': 0, 'head': 0, 'meaning': 2,
                       'span': 2, 'connect': 3, 'level': 3},
    static_dir=PATHS.static,
    renderer=RENDERER,
    modes=MODES,
    anki_deck=ANKI_DECK,
    anki_notes=[AnkiNotes(READING_NOTE_TYPE, build_notes),
                AnkiNotes(COMPOSE_NOTE_TYPE, build_compose_notes)],
    load_payload=load_payload,
)
