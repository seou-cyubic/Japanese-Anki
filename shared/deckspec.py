# -*- coding: utf-8 -*-
"""덱 계약.

``decks/<이름>/deck.py`` 는 ``DeckSpec`` 하나를 ``DECK`` 이름으로 내놓는다.
``app`` 은 ``decks/*`` 를 열거해 이 선언만 읽으며, 어떤 덱 이름도 하드코딩하지
않는다.  덱을 하나 더 붙이는 일은 폴더 하나를 더하는 일이 된다.
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .anki import NoteTypeSpec


@dataclass
class AnkiNotes:
    """한 덱이 내놓는 노트 타입 하나와 그 노트를 만드는 방법.

    **덱 하나가 노트 타입 둘을 낼 수 있다.**  학습 단위가 다르면 노트도 갈라져야
    하기 때문이다 — 문법 덱의 읽기 카드는 문형 하나가 한 장이지만(예문을 나란히
    놓고 견주어야 뜻이 보인다), 작문 카드는 예문 하나가 한 장이다(문장 하나를
    지어 보는 연습이다).  한 노트에서 나오는 카드 수는 카드 템플릿 수로 고정되므로
    이 둘은 같은 노트에서 나올 수 없다.
    """
    note_type: NoteTypeSpec
    build: Callable[[Any], list[dict[str, str]]]


@dataclass
class DeckSpec:
    name: str                       # 폴더 이름.  "kanji"
    title: str                      # 사람이 읽는 이름.  "한자"
    data_path: Path                 # 프론트엔드가 읽는 최종 JSON
    record_label: str               # 레코드 하나가 무엇인지.  "한자 한 자"

    # --- 데이터 규칙 ---
    validate_record: Callable[[str, Any], list[str]]
    validate_payload: Callable[[Any], list[str]]
    sort_record: Callable[[dict], dict]
    project_record: Callable[..., dict]
    statistics: Callable[[dict], dict]
    # 레코드 하나를 검색 색인 한 줄로.  최소한 key·title·subtitle·weight·_terms 를 낸다.
    index_row: Callable[[str, Any], dict]

    # --- 화면 ---
    static_dir: Path                # 그 덱 전용 렌더러가 있는 곳
    renderer: str                   # 전역 JS 객체 이름.  "KanjiCard"
    modes: list[tuple[str, str]]    # [(모드 키, 표시 이름)]

    # --- Anki ---
    anki_deck: str                  # 그 덱의 Anki 뿌리.  "한자"
    anki_notes: list[AnkiNotes]     # 이 덱이 내놓는 노트 타입들

    # 검색 결과 정렬 우선순위.  작을수록 먼저.  없는 종류는 5.
    search_priorities: dict = field(default_factory=dict)

    # 저장 직전에 필드 순서를 고르는 방법.  덱마다 스키마가 다르므로 덱이 정한다.
    order_record: Callable[[dict], dict] = lambda record: record

    # 덱이 자기 데이터를 직접 읽는 방법.  편집 overlay 를 쓰는 덱(한자)은 비워 두고,
    # 파일에서 바로 읽는 덱(문법)은 여기에 읽기 함수를 준다.
    load_payload: Callable[[], Any] | None = None

    extras: dict = field(default_factory=dict)


def discover(decks_root: Path) -> dict[str, DeckSpec]:
    """``decks/`` 아래의 모든 덱 선언을 읽어들인다."""
    found: dict[str, DeckSpec] = {}
    for info in pkgutil.iter_modules([str(decks_root)]):
        if not info.ispkg:
            continue
        try:
            module = importlib.import_module(f"decks.{info.name}.deck")
        except ModuleNotFoundError:
            continue                # deck.py 가 아직 없는 작업 중인 덱
        spec = getattr(module, "DECK", None)
        if isinstance(spec, DeckSpec):
            found[spec.name] = spec
    return found
