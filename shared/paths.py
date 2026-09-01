# -*- coding: utf-8 -*-
"""프로젝트 경로 단일 정의.

루트에 있는 것은 **주제에 종속되지 않는 것**뿐이다 — 외부 코퍼스와 자격 증명.
덱 고유 자료는 전부 ``decks/<이름>/`` 아래에 있고, 그 경로는 각 덱의 ``deck.py``
가 ``DeckPaths`` 로 선언한다.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CORPORA = ROOT / "corpora"       # 공용 외부 코퍼스 (주제 무관·대용량)
SECRETS = ROOT / "secrets"       # 자격 증명
DECKS = ROOT / "decks"           # 덱 모음
APP_STATIC = ROOT / "app" / "static"

# --- 공용 코퍼스 ---
JMDICT = CORPORA / "JMdict"
BCCWJ = CORPORA / "bccwj_luw" / "BCCWJ_frequencylist_luw_ver1_1.tsv"
UNIHAN = CORPORA / "unihan"

# --- 자격 증명 ---
GEMINI_KEY = SECRETS / "gen-lang-client-0725026382-c8b424fd4cfa.json"


class DeckPaths:
    """한 덱의 표준 경로 배치.

    ``base/`` 원천(읽기 전용) · ``data/`` 생성물 · ``data/tmp/`` 중간 산출물 ·
    ``static/`` 그 덱 전용 렌더러.
    """

    def __init__(self, name: str):
        self.name = name
        self.root = DECKS / name
        self.base = self.root / "base"
        self.data = self.root / "data"
        self.tmp = self.data / "tmp"
        self.static = self.root / "static"
        self.cache = self.data / "cache.json"

    def ensure(self) -> "DeckPaths":
        self.tmp.mkdir(parents=True, exist_ok=True)
        return self

    def __repr__(self) -> str:
        return f"DeckPaths({self.name!r})"
