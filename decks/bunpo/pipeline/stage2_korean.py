# -*- coding: utf-8 -*-
"""Stage 2: bunpo_korean.json — 예문에 한국어 해석과 문법 구간 표시를 붙인다.

두 가지가 한 번의 호출로 처리된다.

1. **한국어 해석** — 원전에는 해설만 한국어이고 예문 번역은 없다.
2. **문법 구간** — 기계적 매칭(``marking.py``)이 닿지 못한 예문만.

기계적 매칭이 먼저다.  표제형이 예문에 그대로(또는 후리가나를 거쳐) 나타나면
그것이 정답이고 결정적이며 공짜다.  전체의 3/4 가 여기서 끝난다.  나머지는
표제형이 표제어일 뿐이고 예문은 그 어족을 보여 주는 경우다 — ``あげる`` 항목의
``やる``·``さしあげる``, ``かいがあって`` 항목의 ``かいもなく`` 같은 것.  이건 사전적
지식이 있어야 하므로 모델에게 묻는다.

모델의 답은 **검증한 뒤에만** 쓴다.  돌려준 구간이 예문의 실제 부분 문자열이
아니면 버린다.  그래야 환각이 데이터에 들어오지 않는다.
"""
import json
import sys

sys.path.insert(0, __file__.rsplit("pipeline", 1)[0] + "pipeline")
sys.path.insert(0, __file__.rsplit("decks", 1)[0])

import paths  # noqa: E402
from marking import entry_keys, mark, mark_with_span, views  # noqa: E402
from shared.gemini import Cache, Gemini, chunk  # noqa: E402

BATCH = 15

PROMPT = (
    "너는 일본어 표현문형 사전의 예문을 한국어로 옮기고, 그 예문에서 지정된 문형이"
    " 실제로 실현된 부분을 집어내는 일을 한다.\n"
    "규칙:\n"
    "- ko: 자연스러운 한국어 번역. 직역투를 피하고 문장 부호는 한국어 관행을 따른다.\n"
    "- span: 예문에서 그 문형이 실현된 **연속된 부분 문자열**을 원문 그대로 옮겨 적는다."
    " 반드시 예문에 글자 그대로 들어 있어야 한다. 조사나 활용까지 포함해 자연스러운"
    " 최소 단위로 잡는다.\n"
    "- 문형이 그 예문에 나타나지 않으면 span 을 빈 문자열로 둔다.\n"
    "- 출력은 JSON 객체 {\"results\": [{\"i\": 번호, \"ko\": 번역, \"span\": 구간}]} 하나뿐이다."
    " 설명 금지.\n\n"
)


def main() -> None:
    entries = json.load(paths.D1_RAW.open(encoding="utf-8"))
    cache_ko = Cache(paths.CACHE, "example_ko")
    cache_span = Cache(paths.CACHE, "example_span")
    gemini = Gemini(paths.GEMINI_KEY)

    # --- 1. 기계적 표시 먼저 ---
    jobs = []                       # 모델에게 물어야 하는 것
    stats = {"mechanical": 0, "asked": 0, "cached": 0}
    for entry in entries:
        for example in entry["examples"]:
            annotated = example["ja"]
            marked, method = mark(annotated, entry["head"])
            example["marked"] = marked
            example["mark_method"] = method
            if method:
                stats["mechanical"] += 1
            key = f"{entry['head']}|{annotated}"
            example["_key"] = key
            if key in cache_ko and (method or key in cache_span):
                stats["cached"] += 1
                continue
            jobs.append((entry, example))

    print(f"예문 {sum(len(e['examples']) for e in entries)} | "
          f"기계 표시 {stats['mechanical']} | 호출 대상 {len(jobs)}", flush=True)

    # --- 2. 모자란 것만 모델에게 ---
    for index, group in enumerate(chunk(jobs, BATCH), 1):
        listing = []
        for number, (entry, example) in enumerate(group, 1):
            plain = views(example["ja"])["plain"]
            listing.append(f'{number}. 문형「{entry["head"]}」 예문: {plain}')
        answer = gemini.json(PROMPT + "\n".join(listing))
        rows = answer.get("results", answer if isinstance(answer, list) else [])
        by_number = {int(row.get("i", 0)): row for row in rows if isinstance(row, dict)}
        for number, (entry, example) in enumerate(group, 1):
            row = by_number.get(number)
            if not row:
                continue
            korean = str(row.get("ko", "")).strip()
            if korean:
                cache_ko[example["_key"]] = korean
            span = str(row.get("span", "")).strip()
            # 환각 방지: 돌려준 구간이 예문에 실제로 있어야 쓴다.
            if span and span in views(example["ja"])["plain"]:
                cache_span[example["_key"]] = span
        cache_ko.flush()
        cache_span.flush()
        print(f"  [{index}] {len(group)}건 처리", flush=True)

    # --- 3. 반영 ---
    unresolved = 0
    for entry in entries:
        for example in entry["examples"]:
            key = example.pop("_key")
            example["ko"] = cache_ko.get(key, "")
            if not example["mark_method"]:
                span = cache_span.get(key)
                marked, method = (mark_with_span(example["ja"], span)
                                  if span else (example["ja"], None))
                example["marked"] = marked
                example["mark_method"] = method
                if not method:
                    unresolved += 1
    keyed = {key: entry for key, entry in zip(entry_keys(entries), entries)}
    with paths.D3_KOREAN.open("w", encoding="utf-8") as stream:
        json.dump(keyed, stream, ensure_ascii=False, indent=1)
    total = sum(len(e["examples"]) for e in entries)
    empty = sum(1 for e in entries for x in e["examples"] if not x["ko"])
    print(f"{paths.D3_KOREAN.name} 기록 | 예문 {total} | 번역 공란 {empty} | "
          f"구간 미표시 {unresolved}")


if __name__ == "__main__":
    main()
