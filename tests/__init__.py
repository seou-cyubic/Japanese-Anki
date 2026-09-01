"""Tests for the current-schema frontend.

**산출물이 없으면 터지는 것이 아니라 건너뛴다.**

파이프라인이 만드는 ``decks/*/data/*.json`` 은 저장소에 없다 — 원전의 파생물이라
올리지 않기 때문이다.  그래서 갓 받은 저장소에는 그 파일들이 없고, 그것을 읽는
시험은 ``FileNotFoundError`` 로 터지는 대신 **건너뛰어야 한다.**  아직 파이프라인을
돌리지 않은 것은 정상적인 상태이지 고장이 아니고, 진짜 실패와 섞이면 처음 받은
사람이 무엇이 잘못됐는지 알 수 없다.

산출물이 필요한 시험은 ``load()`` 로 읽는다.  없으면 그 자리에서 skip 이 된다 —
``setUpClass`` 에서 부르면 그 클래스가, 시험 안에서 부르면 그 시험 하나가 빠진다.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def deck_data(deck: str, name: str) -> Path:
    """덱 산출물의 경로.  아직 만들어지지 않았으면 부르는 시험을 건너뛴다."""
    path = ROOT / "decks" / deck / "data" / name
    if not path.exists():
        raise unittest.SkipTest(
            f"{deck}/{name} 이 아직 없다 — 파이프라인을 먼저 돌린다")
    return path


def load(deck: str, name: str) -> Any:
    """덱 산출물 하나를 읽는다.  아직 없으면 건너뛴다."""
    return json.loads(deck_data(deck, name).read_text(encoding="utf-8"))
