# -*- coding: utf-8 -*-
"""예문 두 문장이 정말 같은 것을 말하는가 — 표본 감사.

Stage 4 의 세 검사(후리가나 복원·영문에 낱말·일문에 그 뜻)는 기계가 보증한다.  그러나
**뉘앙스가 같은지는 기계가 볼 수 없다.**  볼 수 없는 것을 본 척하지 않되, 모르는
채로 두지도 않는다 — 무작위 표본을 모델에게 다시 보여 주고 점수를 받아 **데이터가
아니라 보고서에 남긴다.**

데이터를 고치지 않는다.  이 파일은 아무것도 쓰지 않는다.
"""
from __future__ import annotations

import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from decks.toeic.pipeline import paths  # noqa: E402
from shared.furigana import plain_surface  # noqa: E402
from shared.gemini import Cache, Gemini, chunk  # noqa: E402
from shared.paths import GEMINI_KEY  # noqa: E402

SAMPLE = 200
BATCH = 25
WORKERS = 4
SEED = 20260829          # 표본은 재현 가능해야 한다.  숫자를 다시 셀 수 있어야 하므로

PROMPT = """You are auditing a bilingual vocabulary deck. Each item below has an
English sentence and a Japanese sentence that are supposed to say **exactly the same
thing** — same meaning, same register, same nuance — and to read as natural writing
in their own language.

Judge each pair. Be strict: if a Japanese reader and an English reader would come
away with a different impression, it is not a match.

  "verdict" : "same"      — same meaning, same nuance, both natural
              "shade"     — same meaning but the register or emphasis drifts
              "different" — the meaning differs, or one of them is unnatural
  "note"    : if not "same", one short clause saying what drifted (in Korean)

Pairs: %(pairs)s

Answer as JSON only: {"<id>": {"verdict": "...", "note": "..."}}
"""


def main() -> None:
    # 콘솔이 UTF-8 이 아닐 수 있다.  글자가 깨질지언정 멈추지는 않는다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    payload = json.loads(paths.FINAL.read_text(encoding="utf-8"))
    items = [(f"{word}#{index}", word, sense)
             for word, record in payload.items()
             for index, sense in enumerate(record["senses"])
             if sense.get("example")]
    random.Random(SEED).shuffle(items)
    sample = items[:SAMPLE]
    print(f"예문 {len(items)}개 중 {len(sample)}개를 감사한다 (seed {SEED})")

    cache = Cache(paths.CACHE, "toeic_audit")
    gemini = Gemini(GEMINI_KEY)
    missing = [row for row in sample if cache.get(row[0]) is None]

    def ask(group):
        pairs = [{"id": key, "word": word,
                  "en": sense["example"]["en"],
                  "ja": plain_surface(sense["example"]["ja"])}
                 for key, word, sense in group]
        answer = gemini.json(PROMPT % {"pairs": json.dumps(pairs, ensure_ascii=False)},
                             temperature=0.0)
        return group, (answer if isinstance(answer, dict) else {})

    if missing:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for group, answer in pool.map(ask, chunk(missing, BATCH)):
                for key, _word, _sense in group:
                    cache[key] = answer.get(key) or {}
                cache.flush()
                print(f"  {len(cache)}개 채점", flush=True)

    tally: dict[str, int] = {}
    drifted = []
    for key, word, sense in sample:
        got = cache.get(key) or {}
        verdict = got.get("verdict", "?")
        tally[verdict] = tally.get(verdict, 0) + 1
        if verdict not in ("same", "?"):
            drifted.append((key, verdict, got.get("note", ""),
                            sense["example"]["en"]))

    print(f"\n표본 {len(sample)}개")
    for verdict in ("same", "shade", "different", "?"):
        if verdict in tally:
            print(f"  {verdict:10} {tally[verdict]:4}  ({tally[verdict]/len(sample):.1%})")
    print("\n어긋난 것 (앞의 15개):")
    for key, verdict, note, english in drifted[:15]:
        print(f"  [{verdict}] {key}: {note}")
        print(f"        {english}")


if __name__ == "__main__":
    main()
