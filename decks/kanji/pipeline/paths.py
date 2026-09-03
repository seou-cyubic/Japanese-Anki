# -*- coding: utf-8 -*-
"""한자 덱의 경로.  스테이지들은 여기서만 경로를 얻는다.

공용 자원(코퍼스·자격 증명)은 ``shared.paths`` 에서, 덱 고유 자료는 ``DeckPaths``
에서 온다.  스테이지 안에 경로 리터럴을 쓰지 않는다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from shared.paths import (  # noqa: E402
    BCCWJ,
    DeckPaths,
    GEMINI_KEY,
    JMDICT,
    ROOT,
    UNIHAN,
)

DECK = DeckPaths("kanji").ensure()

BASE = DECK.base
DATA = DECK.data
TMP = DECK.tmp

# --- 원천 ---
JOYO_PDF = BASE / "J_20101130.pdf"           # 상용한자표 (2010 개정)
JOYO_OLD_PDF = BASE / "J_19811001.pdf"       # 구 상용한자표 (1981)
HYOGAI_PDF = BASE / "H_20000901.pdf"         # 표외한자 자체표
HYOGAI_DATA_PDF = BASE / "H_20000901_data.pdf"
SCHOOL_TXT = BASE / "S.txt"                  # 학년별 배당 한자
HYOGAI_TXT = BASE / "H.txt"                  # 표외한자 목록
KOREAN_XLS = BASE / "K.xls"                  # 한국 교육용 한자 훈음

# --- 생성 ---
CACHE = DECK.cache
D1_RAW = DATA / "data.json"
D2_KOREAN = DATA / "data_korean.json"
D3_EXAMPLE = DATA / "data_example.json"
D4_TRANSLATE = DATA / "data_translate.json"
D5_JAPANESE = DATA / "data_japanese.json"

# --- 중간 ---
S1_JOYO = TMP / "s1_joyo.json"               # 본표 4열 원문 + 付表 페어

__all__ = [
    "BASE", "DATA", "TMP", "ROOT", "DECK",
    "JOYO_PDF", "JOYO_OLD_PDF", "HYOGAI_PDF", "HYOGAI_DATA_PDF",
    "SCHOOL_TXT", "HYOGAI_TXT", "KOREAN_XLS",
    "JMDICT", "BCCWJ", "UNIHAN", "GEMINI_KEY",
    "CACHE", "D1_RAW", "D2_KOREAN", "D3_EXAMPLE", "D4_TRANSLATE", "D5_JAPANESE",
    "S1_JOYO",
]
