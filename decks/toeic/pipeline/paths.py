# -*- coding: utf-8 -*-
"""토익 덱의 경로.  경로 리터럴은 여기와 ``shared/paths.py`` 에만 적는다."""
from shared.paths import DeckPaths

PATHS = DeckPaths("toeic").ensure()

BASE = PATHS.base
DATA = PATHS.data
CACHE = PATHS.cache

# --- 원전 (읽기 전용) ---
NGSL_STATS = BASE / "NGSL_12_stats.csv"
NGSL_FAMILY = BASE / "NGSL_12_lemmatized_for_teaching.csv"
TSL_STATS = BASE / "TSL_12_stats.csv"
TSL_FAMILY = BASE / "TSL_12_lemmatized_for_teaching.csv"

# --- 생성물 ---
RAW = DATA / "toeic.json"                 # stage 1: 표제어·순위·어족
SENSES = DATA / "toeic_senses.json"       # stage 2: 모델이 고른 뜻
CHECKED = DATA / "toeic_checked.json"     # stage 3: 사전으로 검증한 것
FINAL = DATA / "toeic_japanese.json"      # stage 4: 예문까지 붙인 최종본
