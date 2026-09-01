# -*- coding: utf-8 -*-
"""Stage 2: toeic_senses.json — 낱말마다 TOEIC 에 필요한 뜻을 일본어로 받는다.

**왜 사전이 아니라 모델인가.**  네 원천을 4,059 낱말 전부로 재 보았다.
Japanese WordNet 은 뜻을 sense 로 갈라 주지만 낱말당 일본어가 붙은 sense 가 평균
4.5 개(``run`` 은 38 개)이고 그 안의 일본어에 순위가 없어 「韋編」이 「本」 앞에 온다.
읽기도 없다.  JMdict 를 뒤집으면 후보가 평균 18 개(최대 242)인데 뜻 축이 아예 없다.
EJDict 는 산문 한 덩이에 뜻 열한 개가 들어 있고 어휘가 낡았다.

**'이 영어 낱말의 어느 뜻이 TOEIC 에 자주 나오는가' 를 담은 사전이 없다.**  그것을
아는 것은 모델뿐이므로 뜻은 모델에게 묻고, 대신 **돌려준 일본어의 실재와 읽기는
JMdict 로 전수 검증한다**(stage 3).  이 저장소가 문법 구간에 쓰는 방법과 같다.

호출은 전부 ``data/cache.json`` 에 남는다.  다시 돌리면 신규 호출이 0 이다.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from decks.toeic.pipeline import paths  # noqa: E402
from shared.gemini import Cache, Gemini, chunk, dump_json_atomic  # noqa: E402
from shared.paths import GEMINI_KEY  # noqa: E402

BATCH = 20                     # 한 번에 묻는 낱말 수.  20 개에 26 초였다
WORKERS = 4                    # 동시에 띄우는 호출 수.  4,059 낱말이 203 묶음이다
MAX_SENSES = 3

PROMPT = """You are building a Japanese vocabulary deck for a learner who studies
English *through* Japanese, aiming at the TOEIC test.

For each English word below give the senses a TOEIC learner actually needs.
Rules:
- At most %(max)d senses per word, ordered by how often that sense appears in
  TOEIC-style business and daily English. Most words need only 1 or 2.
- Drop archaic, dialectal, literary and narrowly technical senses.
- Keep senses that are genuinely different in Japanese. Do not split a sense
  just because English grammar books would.
- For function words (articles, modals, conjunctions) give the usage patterns a
  learner must recognise, expressed the way a Japanese textbook would.

For each sense give exactly these fields:
  "ja"    : the Japanese equivalent in dictionary form, **plain, no furigana,
            no parentheses**. Use the form a dictionary would list
            (e.g. 搭乗する, 取締役会, 払い戻す).
  "kana"  : the complete reading of "ja" in hiragana (katakana only where the
            word itself is katakana). It must read the whole of "ja".
  "pos"   : one of noun, verb, adjective, adverb, function
  "gloss" : a Japanese gloss of 12 characters or fewer
  "en"    : a short English gloss that separates this sense from the others

Words: %(words)s

Answer as JSON only:
{"<word>": [{"ja":"...","kana":"...","pos":"...","gloss":"...","en":"..."}]}
"""

FIELDS = ("ja", "kana", "pos", "gloss", "en")
POS = {"noun", "verb", "adjective", "adverb", "function"}


def clean(senses) -> list[dict]:
    """모델이 낸 것을 계약대로 다듬는다.  모양이 아니면 버린다."""
    out = []
    if not isinstance(senses, list):
        return out
    for sense in senses[:MAX_SENSES]:
        if not isinstance(sense, dict):
            continue
        row = {name: str(sense.get(name, "")).strip() for name in FIELDS}
        if not row["ja"] or not row["kana"]:
            continue
        if row["pos"] not in POS:
            row["pos"] = "noun"
        out.append(row)
    return out


def main() -> None:
    entries = json.loads(paths.RAW.read_text(encoding="utf-8"))
    cache = Cache(paths.CACHE, "toeic_senses")
    gemini = Gemini(GEMINI_KEY)

    missing = [word for word in entries if cache.get(word) is None]
    groups = list(chunk(missing, BATCH))
    print(f"표제어 {len(entries)} · 캐시에 없는 것 {len(missing)}"
          f" · 묶음 {len(groups)} · 동시 {WORKERS}")

    def ask(group: list[str]) -> tuple[list[str], dict]:
        answer = gemini.json(PROMPT % {"max": MAX_SENSES,
                                       "words": json.dumps(group)})
        if not isinstance(answer, dict):
            raise ValueError(f"응답이 object 가 아니다: {str(answer)[:200]}")
        return group, answer

    # 호출은 나눠 띄우되 **캐시 쓰기는 이 자리 하나뿐이다.**  받는 족족 남기므로
    # 중간에 끊겨도 이미 받은 것은 잃지 않는다.
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for group, answer in pool.map(ask, groups):
            for word in group:
                # 모델이 대소문자를 바꿔 돌려주는 일이 있다.  둘 다 본다.
                senses = answer.get(word)
                if senses is None:
                    senses = answer.get(word.capitalize(), answer.get(word.upper()))
                cache[word] = clean(senses)
            cache.flush()
            done += len(group)
            print(f"  [{done}/{len(missing)}] {group[0]} … {group[-1]}", flush=True)

    empty = []
    for word, entry in entries.items():
        senses = cache.get(word) or []
        entry["senses"] = senses
        if not senses:
            empty.append(word)
    dump_json_atomic(paths.SENSES, entries)
    total = sum(len(e["senses"]) for e in entries.values())
    print(f"뜻 {total}개 · 낱말당 {total/len(entries):.2f}개 · 빈 낱말 {len(empty)}"
          f" {empty[:10]} | -> {paths.SENSES.name}")


if __name__ == "__main__":
    main()
