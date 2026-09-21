# -*- coding: utf-8 -*-
"""Stage 3: toeic_japanese.json — 모델이 낸 일본어를 사전으로 검증한다.

**방향이 정확히 갈린다.**  '영어 낱말의 어느 뜻이 TOEIC 에 자주 나오는가' 는 사전이
모르지만, '이 일본어 낱말이 실재하는가, 읽기가 이게 맞는가' 는 일-영 사전인 JMdict 가
가장 잘 안다.  그래서 뜻은 모델이 고르고 표기와 읽기는 사전이 확인한다.

읽기 검증이 특히 중요하다.  후리가나가 틀리면 학습자가 그대로 잘못 외우는데, 그 사고를
전수로 막을 수 있는 곳이 여기뿐이다.

검증을 통과하면 표기와 읽기를 이 저장소의 **주석 표기**로 합친다
(``搭乗する`` + ``とうじょうする`` → ``搭乗(とうじょう)する``).  한자 덱·문법 덱과 같은
문법이므로 렌더러의 루비 처리가 그대로 돈다.

모델을 부르지 않는다.  몇 번을 돌려도 공짜다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from decks.toeic.pipeline import paths  # noqa: E402
from shared.furigana import annotate, to_hiragana  # noqa: E402
from shared.gemini import dump_json_atomic  # noqa: E402
from shared import jmdict as shared_jmdict  # noqa: E402

# ``する`` 처럼 사전 표제어 뒤에 붙는 꼬리.  표제어는 ``搭乗`` 이지만 낱말로 쓸 때는
# ``搭乗する`` 다.  꼬리를 떼어 보고 다시 찾는다.
TAILS = ("する", "した", "して", "な", "に", "と", "だ", "の")

# 검증 등급.  데이터에 그대로 남는다 — 무엇이 확인됐고 무엇이 아닌지는 숨길 것이 아니다.
CHECKED = "jmdict"      # 표기가 JMdict 에 있고 읽기도 맞는다
PHRASE = "phrase"       # 사전 표제어가 아닌 구(句).  기능어 용법이 대부분이다
UNSURE = "unsure"       # 표기는 있으나 읽기가 사전과 다르다 — 사람이 봐야 한다


def jmdict_readings() -> dict[str, set[str]]:
    """표기 -> 읽기 집합.  ``shared.jmdict`` 가 한자 덱과 함께 쓰는 정의다."""
    return shared_jmdict.readings()


def heads(surface: str) -> list[tuple[str, str]]:
    """(사전에서 찾을 표기, 떼어 낸 꼬리) 후보들.  긴 꼬리부터 본다."""
    out = [(surface, "")]
    for tail in TAILS:
        if surface.endswith(tail) and len(surface) > len(tail):
            out.append((surface[: -len(tail)], tail))
    return out


def verify(surface: str, kana: str, readings: dict[str, set[str]]) -> tuple[str, str]:
    """(검증 등급, 사전이 아는 읽기).  읽기는 꼬리를 붙여 되돌린 전체 읽기다."""
    for head, tail in heads(surface):
        known = readings.get(head)
        if not known:
            continue
        wanted = to_hiragana(kana)
        for reading in known:
            if to_hiragana(reading) + to_hiragana(tail) == wanted:
                return CHECKED, kana
        # 표기는 있는데 읽기가 다르다.  사전 쪽 읽기를 대안으로 들려 보낸다.
        best = sorted(known, key=len)[0]
        return UNSURE, best + tail
    return PHRASE, kana


def main() -> None:
    entries = json.loads(paths.SENSES.read_text(encoding="utf-8"))
    readings = jmdict_readings()
    print(f"JMdict 표기 {len(readings)}종")

    tally = {CHECKED: 0, PHRASE: 0, UNSURE: 0}
    annotated_ok = 0
    fixed = 0
    for word, entry in entries.items():
        senses = []
        for sense in entry["senses"]:
            surface, kana = sense["ja"], sense["kana"]
            state, known = verify(surface, kana, readings)
            tally[state] += 1
            if state == UNSURE and known != kana:
                # 사전이 아는 읽기로 고쳐 붙이고, 고쳤다는 사실을 남긴다.
                kana = known
                fixed += 1
            written = annotate(surface, kana) or surface
            if written != surface:
                annotated_ok += 1
            senses.append({
                "ja": written,          # 후리가나가 실린 표기 (shared/furigana.py)
                "pos": sense["pos"],
                "gloss": sense["gloss"],
                "en": sense["en"],
                "checked": state,
            })
        entry["senses"] = senses
    dump_json_atomic(paths.CHECKED, entries)

    total = sum(tally.values())
    print(f"뜻 {total}개")
    for state in (CHECKED, PHRASE, UNSURE):
        print(f"  {state:8} {tally[state]:6}  ({tally[state]/total:.1%})")
    print(f"읽기를 사전 것으로 고친 것 {fixed}개")
    print(f"후리가나를 실은 것 {annotated_ok}개 "
          f"(나머지는 가나뿐이라 실을 것이 없다)")
    print(f"-> {paths.CHECKED.name}")


if __name__ == "__main__":
    main()
