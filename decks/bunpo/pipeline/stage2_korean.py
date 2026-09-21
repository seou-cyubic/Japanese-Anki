# -*- coding: utf-8 -*-
"""Stage 2: bunpo_korean.json — 예문에 한국어 해석과 문법 구간 표시를 붙인다.

두 가지가 한 번의 호출로 처리된다.

1. **한국어 해석** — 원전에는 해설만 한국어이고 예문 번역은 없다.
2. **문법 구간** — 기계적 매칭(``marking.py``)이 닿지 못한 예문만.

기계적 매칭이 먼저다.  표제형이 예문에 그대로(또는 후리가나를 거쳐) 나타나면
그것이 정답이고 결정적이며 공짜다.  전체의 4/5 가 여기서 끝난다.  나머지는
표제형이 표제어일 뿐이고 예문은 그 어족을 보여 주는 경우다 — ``あげる`` 항목의
``やる``·``さしあげる``, ``かいがあって`` 항목의 ``かいもなく`` 같은 것.  이건 사전적
지식이 있어야 하므로 모델에게 묻는다.

모델의 답은 **검증한 뒤에만** 쓴다.  돌려준 조각이 예문에 차례대로 실제로 들어
있지 않으면 통째로 버린다.  그래야 환각이 데이터에 들어오지 않는다.

**구간은 여럿일 수 있다.**  ``たり～たりする`` 는 문장 안에서 떨어져 실현되므로
(``読んだり、テレビを見たりします``) 조각마다 따로 표시해야 한다.  예전에는 표기법이
구간 하나밖에 담지 못해 모델에게 '연속된 부분 문자열' 을 물었고, 그 결과 ``たり`` 사이의
말이 통째로 강조된 채 데이터에 들어왔다.  이제 조각들을 묻는다.

**기계적 매칭은 사전을 본다.**  ``たい`` 는 ``冷たいビールが飲みたい`` 에 두 번 나오고 앞의
것은 ``冷たい`` 라는 낱말의 일부다.  형태만으로는 ``見たい`` 와 구별할 수 없으므로 JMdict
에서 뽑은 내용어 목록으로 가른다(``lexicon.py``).  코퍼스가 없으면 목록 없이 돌아간다 —
그때는 자리 고르기가 예전만큼만 똑똑해지고 나머지는 그대로다.
"""
import json
import sys

sys.path.insert(0, __file__.rsplit("pipeline", 1)[0] + "pipeline")
sys.path.insert(0, __file__.rsplit("decks", 1)[0])

import lexicon as lexicon_module  # noqa: E402
import paths  # noqa: E402
from marking import (EMPTY_LEXICON, entry_keys, mark,  # noqa: E402
                     mark_from_connect, mark_with_spans, overruns, views)
from shared.gemini import Cache, Gemini, chunk  # noqa: E402

BATCH = 15
LEGACY_MODELS = ("gemini-3.7-flash",)   # 읽기만 하는 옛 모델 캐시 칸

PROMPT = (
    "너는 일본어 표현문형 사전의 예문을 한국어로 옮기고, 그 예문에서 지정된 문형이"
    " 실제로 실현된 부분을 집어내는 일을 한다.\n"
    "규칙:\n"
    "- ko: 자연스러운 한국어 번역. 직역투를 피하고 문장 부호는 한국어 관행을 따른다.\n"
    "- spans: 예문에서 **그 문형 자체인 부분만** 원문 그대로 옮겨 적은 문자열의 배열."
    " 각 원소는 반드시 예문에 글자 그대로 들어 있어야 하고, 예문에 나오는 순서대로 적는다.\n"
    "- **문형이 아닌 말을 구간에 넣지 않는다.** 표제형에 「～」가 있으면 그 자리는 문형이"
    " 아니라 문형이 감싸는 내용이므로 **조각을 나누어** 적는다.\n"
    "  예) 문형「たり～たりする」 예문「日曜日には、本を読んだり、テレビを見たりします。」\n"
    "      옳음: [\"だり\", \"たりします\"]\n"
    "      틀림: [\"だり、テレビを見たりします\"]  ← 사이의 말까지 삼켰다\n"
    "- 조각 하나하나는 조사나 활용까지 포함한 자연스러운 최소 단위로 잡는다.\n"
    "- 문형이 그 예문에 나타나지 않으면 spans 를 빈 배열로 둔다.\n"
    "- 출력은 JSON 객체 {\"results\": [{\"i\": 번호, \"ko\": 번역, \"spans\": [구간]}]}"
    " 하나뿐이다. 설명 금지.\n\n"
)


def build_lexicon():
    """자리 고르기에 쓸 내용어 목록.  코퍼스가 없으면 빈 목록으로 돌아간다."""
    if not paths.JMDICT.exists():
        print(f"  JMdict 가 없다({paths.JMDICT}) — 낱말 목록 없이 표시한다", flush=True)
        return EMPTY_LEXICON
    found = lexicon_module.from_jmdict(paths.JMDICT)
    print(f"  낱말 목록: 표기 {len(found.written)} · 읽기 {len(found.spoken)}",
          flush=True)
    return found


def has_wildcard(head: str) -> bool:
    return any(character in head for character in "～〜")


def main() -> None:
    entries = json.load(paths.D1_RAW.open(encoding="utf-8"))
    # 모델을 바꿔도 이미 받은 번역·구간은 다시 묻지 않는다 — 옛 칸은 읽기만 한다.
    cache_ko = Cache(paths.CACHE, "example_ko", fallback_models=LEGACY_MODELS)
    # 조각 **배열**을 담는 새 칸이다.  구간 하나만 담던 옛 칸(``example_span``)은
    # 지우지 않는다 — 그 답들은 대부분 그대로 쓸 수 있고, 다시 받으려면 돈이 든다.
    cache_span = Cache(paths.CACHE, "example_spans", fallback_models=LEGACY_MODELS)
    legacy_span = Cache(paths.CACHE, "example_span", fallback_models=LEGACY_MODELS)
    gemini = Gemini(paths.GEMINI_KEY)
    lexicon = build_lexicon()

    # --- 0. 옛 답 옮겨 심기 ---
    # 「～」가 없는 표제형은 문형이 한 덩이로 실현되므로 옛 답(연속 구간 하나)이 곧
    # 조각 하나다.  **「～」가 있는 표제형은 옮기지 않는다** — 사이의 말까지 삼킨 것이
    # 바로 그 답들이라, 그대로 두면 고치려는 것을 도로 심는 꼴이 된다.
    #
    # **길이로 답을 무르는 것은 「～」가 있는 표제형에만 건다.**  거기서는 사이의 말이
    # 문형이 아님을 표제형 자체가 말해 주므로 긴 답은 확실히 틀렸다.  「～」가 없는
    # 표제형은 다르다 — ``くする`` 가 ``きれいにしなさい`` 로 실현되듯 문형이 실제로 길게
    # 실현되기도 하고, 그때 답을 무르면 남는 것은 더 나은 표시가 아니라 **표시 없음**
    # 이다.  조금 긴 표시를 지우고 아무것도 안 남기는 것은 고침이 아니라 손실이다.
    # 그런 것은 감사가 WARN 으로 세어 사람에게 보인다.
    seeded = 0
    revoked = 0
    unfit = 0
    for entry in entries:
        wildcard = has_wildcard(entry["head"])
        for example in entry["examples"]:
            key = f"{entry['head']}|{example['ja']}"
            kept = cache_span.get(key)
            if kept is not None:
                # 이미 들어와 있는 답도 같은 자로 다시 잰다.  자를 고친 뒤에도 옛 답이
                # 캐시에 남아 있으면 고침이 데이터에 닿지 않는다.
                if wildcard and overruns(entry["head"], kept):
                    del cache_span[key]
                    revoked += 1
                continue
            if wildcard:
                continue
            old = legacy_span.get(key)
            if not isinstance(old, str) or not old.strip():
                continue
            cache_span[key] = [old.strip()]
            seeded += 1
    if seeded or revoked or unfit:
        cache_span.flush()
        print(f"옛 구간 캐시에서 옮겨 심은 것 {seeded} | 너무 길어 무른 것 {revoked}",
              flush=True)

    # --- 1. 기계적 표시 먼저 ---
    jobs = []                       # 모델에게 물어야 하는 것
    stats = {"mechanical": 0, "asked": 0, "cached": 0}
    for entry in entries:
        for example in entry["examples"]:
            annotated = example["ja"]
            marked, method = mark(annotated, entry["head"],
                                  connect=entry.get("connect") or [],
                                  lexicon=lexicon)
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
            # **이미 받은 번역은 덮어쓰지 않는다.**  구간을 기계로 못 찾은 예문은 실행할
            # 때마다 구간을 다시 묻는데, 그때 딸려 온 번역으로 바꾸면 카드의 번역이
            # 까닭 없이 달라진다(모델을 바꾼 뒤 18 개가 그렇게 바뀌었다).
            if korean and example["_key"] not in cache_ko:
                cache_ko[example["_key"]] = korean
            answer = row.get("spans", row.get("span", ""))
            if isinstance(answer, str):
                answer = [answer]
            pieces = [str(piece).strip() for piece in answer or ()
                      if str(piece).strip()]
            # 환각 방지: 돌려준 조각들이 **차례대로** 예문에 실제로 있어야 쓴다.
            # 하나라도 어긋나면 통째로 버린다 — 반쪽만 믿을 수는 없다.
            plain = views(example["ja"])["plain"]
            cursor = 0
            for piece in pieces:
                found = plain.find(piece, cursor)
                if found < 0:
                    pieces = []
                    break
                cursor = found + len(piece)
            if pieces:
                cache_span[example["_key"]] = pieces
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
                marked, method = (mark_with_spans(example["ja"], span)
                                  if span else (example["ja"], None))
                if not method:
                    # **마지막 수단.**  원전은 표제형을 대표 꼴 하나로 싣지만 접속형
                    # 칸에는 실제로 실현되는 꼴이 전부 적혀 있다 — ``てくる`` 의
                    # ``Ｖて ＋ いく``, ``と～た`` 의 ``Ｖたら ＋ ～た``.  표제형도 모델도
                    # 답하지 못한 예문은 그것으로 짚는다.  **모델보다 뒤에 두는 이유**는
                    # 리터럴만 주워 온 꼴이라 문형의 알맹이가 빠질 수 있어서다
                    # (``ようとする`` -> ``とする``) — 앞에 세우면 멀쩡한 답을 더 나쁜
                    # 것으로 바꾼다.
                    marked, method = mark_from_connect(
                        example["ja"], entry["head"],
                        connect=entry.get("connect") or [], lexicon=lexicon)
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
