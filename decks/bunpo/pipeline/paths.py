# -*- coding: utf-8 -*-
"""문법 덱의 경로."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from shared.paths import DeckPaths, GEMINI_KEY, JMDICT, ROOT  # noqa: E402

DECK = DeckPaths("bunpo").ensure()

BASE = DECK.base
DATA = DECK.data
TMP = DECK.tmp
CACHE = DECK.cache

BUNPO_PDF = BASE / "B.pdf"           # 日本語表現文型辞典 (ALC)

D1_RAW = DATA / "bunpo.json"         # Stage 1: PDF 에서 뽑은 원형
D2_MARKED = DATA / "bunpo_marked.json"   # Stage 2: 예문에 문법 구간 표시
D3_KOREAN = DATA / "bunpo_korean.json"   # Stage 3: 예문 한국어 해석까지

__all__ = ["BASE", "DATA", "TMP", "CACHE", "ROOT", "DECK", "GEMINI_KEY", "JMDICT",
           "BUNPO_PDF", "D1_RAW", "D2_MARKED", "D3_KOREAN"]
