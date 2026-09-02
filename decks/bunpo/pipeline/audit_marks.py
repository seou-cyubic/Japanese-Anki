# -*- coding: utf-8 -*-
"""문법 구간 표시를 **예문 전건**에 대고 잰다.  모델을 부르지 않는다 — 공짜다.

메모가 짚은 두 고장은 예시가 아니라 부류였다.

  ``たい``            ``冷たいビール`` 의 ``たい`` 에 강조가 붙었다 — 낱말 한가운데다.
  ``たり～たりする``   ``たり`` 사이의 말이 통째로 강조됐다 — 그 사이는 문법이 아니다.

한 건씩 눈으로 보아서는 같은 고장이 어디에 또 있는지 알 수 없다.  그래서 여기서는
**전건을 규칙으로 훑는다.**  검사는 다섯이다.

  1. 표시를 걷으면 예문이 그대로 나온다              (표기 자체가 성립하는가)
  2. 별표가 짝을 이루고 덩이 가운데를 끊지 않는다     (루비가 갈라지지 않는가)
  3. 조각이 사전 낱말 한가운데가 아니다              (``冷たい`` 부류)
  4. ``～`` 표제형의 조각은 사이의 말을 삼키지 않는다  (``たり～たりする`` 부류)
  5. 표제형에 담긴 리터럴이 조각 안에 실제로 있다      (엉뚱한 자리를 짚지 않았는가)

3·4·5 는 **정도**를 재는 것이라 어긋난 것을 바로 고장이라 부르지 않는다.  FAIL 은
기계적으로 확실한 1·2 와, 4 의 명백한 초과분뿐이고 나머지는 WARN 으로 남긴다.
확실한 것만 실패로 세는 편이 보고서를 믿을 수 있게 만든다.

되돌아오는 값은 FAIL 의 개수다 — 파이프라인과 CI 가 그것으로 잡는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import lexicon as lexicon_module  # noqa: E402
import paths  # noqa: E402
from marking import (EMPTY_LEXICON, Lexicon, MARK, SPAN_SLACK,  # noqa: E402
                     groups, head_forms, marked_spans, overruns, views)

# ``～`` 자리를 삼켰는지 보는 자는 ``marking.SPAN_SLACK`` 이다.  파이프라인이 옛 답을
# 옮겨 심을 때 쓰는 것과 같아야 하므로 여기서 따로 정하지 않는다.  이 값을 한 번 더
# 넘긴 것만 FAIL 로 세운다 — 확실한 것만 실패라고 불러야 보고서를 믿을 수 있다.
SLACK = SPAN_SLACK


def _plain(annotated: str) -> str:
    return views(annotated)["plain"]


def _group_edges(annotated: str) -> set[int]:
    edges = {0, len(annotated)}
    for _surface, _reading, start, stop in groups(annotated):
        edges.add(start)
        edges.add(stop)
    return edges


def _mark_offsets(marked: str) -> list[int]:
    offsets = []
    position = marked.find(MARK)
    while position >= 0:
        offsets.append(position - len(offsets))
        position = marked.find(MARK, position + 1)
    return offsets


def audit_example(head, connect, example, lexicon):
    """이 예문 하나의 (심각도, 사유) 목록.  아무 문제가 없으면 빈 목록."""
    del connect                     # 지금 검사에는 쓰지 않는다.  자리는 남겨 둔다.
    found = []
    annotated = example.get("ja", "")
    marked = example.get("marked") or annotated
    spans = marked_spans(marked)

    # 1 · 2 — 표기 자체
    if marked.count(MARK) % 2:
        found.append(("FAIL", "별표가 짝을 이루지 않는다"))
    if marked.replace(MARK, "") != annotated:
        found.append(("FAIL", "표시를 걷어도 예문이 나오지 않는다"))
        return found                # 여기부터는 자리를 믿을 수 없다
    edges = _group_edges(annotated)
    if any(offset not in edges for offset in _mark_offsets(marked)):
        found.append(("FAIL", "표시가 한자와 그 후리가나 사이를 끊는다"))
    if not spans:
        return found                # 미표시는 고장이 아니라 미완이다.  따로 센다.

    flat = [_plain(piece) for piece in spans]

    # 3 — 낱말 한가운데인가 (``冷たい`` 부류)
    plain = _plain(annotated)
    spots = lexicon.occurrences(plain, "plain")
    cursor = 0
    for piece in flat:
        start = plain.find(piece, cursor)
        if start < 0:
            break
        if Lexicon.cuts(spots, start, start + len(piece)):
            found.append(("WARN", f"조각 「{piece}」 가 사전 낱말 한가운데다"))
        cursor = start + len(piece)

    # 4 · 5 — 표제형의 리터럴과 견준다
    forms = head_forms(head)
    if forms:
        # 자는 ``marking`` 이 쥐고 있다.  스테이지가 옛 답을 옮겨 심을 때 쓰는 것과
        # **같은 자여야** 한다 — 감사에서 걸릴 것을 파이프라인이 도로 심으면 안 된다.
        over = overruns(head, flat)
        if over:
            # **FAIL 은 「～」가 있는 표제형에만 준다.**  거기서는 사이의 말이 문형이
            # 아니라는 것을 표제형 자체가 말해 주므로 긴 표시는 확실히 틀렸다 —
            # 메모가 짚은 고장이 바로 그것이다.  「～」가 없는 표제형은 문형이 실제로
            # 길게 실현되기도 하므로(``くする`` -> ``きれいにしなさい``) 단정하지 않는다.
            wildcard = any(character in head for character in "～〜")
            severity = "FAIL" if wildcard and over > SLACK else "WARN"
            found.append((severity,
                          f"표시가 표제형보다 {over}자 길다 — 「{'…'.join(flat)}」"))
        form = min(forms, key=lambda pieces: abs(len(pieces) - len(flat)))
        if len(form) > 1 and len(flat) == 1:
            found.append(("WARN", "떨어져 실현되는 문형인데 조각이 하나다"))
        # 5 — 짚은 자리가 표제형과 상관이 있는가.
        #
        # **기계적 매칭에만 건다.**  모델에게 묻는 예문은 표제형이 표제어일 뿐이고
        # 예문은 그 어족을 보여 주는 경우다 — ``あげる`` 항목의 ``やる``, ``かいがあって``
        # 항목의 ``かいもなく``.  글자가 겹치지 않는 것이 정상이고, 그것을 알아보라고
        # 모델을 부른 것이다.  기계적 매칭은 그럴 수 없다 — 리터럴로 찾았으니 반드시
        # 겹쳐야 하고, 겹치지 않으면 표시가 옮겨 붙었다는 뜻이다.
        #
        # 표제형은 가나이고 예문은 한자다.  ``あいだ`` 의 표시는 ``間(あいだ)`` 이므로
        # 읽기 평면까지 함께 본다.  활용으로 꼬리가 갈리므로(``あげる``/``あげた``)
        # 견주는 것은 포함 관계가 아니라 **머리를 얼마나 같이 쓰는가**다.
        # ``connect-`` 로 시작하는 것은 표제형이 아니라 **접속형**에서 뽑은 꼴로 짚은
        # 것이다(``marking.connect_forms``).  표제형과 글자가 겹치지 않는 것이 정상이므로
        # — ``てくる`` 를 ``ていく`` 로 짚는다 — 이 검사에서 뺀다.
        method = str(example.get("mark_method") or "")
        if method and method != "model" and not method.startswith("connect-"):
            joined = "".join(flat)
            sounded = "".join(views(piece)["reading"] for piece in spans)
            if not any(_shares_a_head(piece, joined) or _shares_a_head(piece, sounded)
                       for piece in form):
                found.append(("WARN",
                              f"기계 표시인데 표제형과 겹치는 글자가 없다 — 「{joined}」"))
    return found


def _shares_a_head(literal: str, span: str) -> bool:
    """표제형 리터럴과 표시가 앞에서 두 글자 이상(짧으면 통째로) 같은가."""
    if not literal or not span:
        return False
    need = min(2, len(literal))
    for start in range(len(span) - need + 1):
        if span[start:start + len(literal)] == literal:
            return True
        if span[start:start + need] == literal[:need]:
            return True
    return False


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    payload = json.loads(paths.D3_KOREAN.read_text(encoding="utf-8"))
    if paths.JMDICT.exists():
        lexicon = lexicon_module.from_jmdict(paths.JMDICT)
    else:
        print(f"JMdict 가 없다({paths.JMDICT}) — 낱말 검사는 건너뛴다")
        lexicon = EMPTY_LEXICON

    total = 0
    unmarked = 0
    fails: list[tuple[str, str, str]] = []
    warns: list[tuple[str, str, str]] = []
    by_method: dict[str, int] = {}
    pieces_of: dict[int, int] = {}
    for key, record in payload.items():
        head = record["head"]
        for position, example in enumerate(record.get("examples", []), 1):
            total += 1
            method = example.get("mark_method") or "미표시"
            by_method[method] = by_method.get(method, 0) + 1
            count = len(marked_spans(example.get("marked") or ""))
            pieces_of[count] = pieces_of.get(count, 0) + 1
            if not count:
                unmarked += 1
            spot = f"{key}[{position}]"
            for severity, reason in audit_example(
                    head, record.get("connect"), example, lexicon):
                (fails if severity == "FAIL" else warns).append(
                    (spot, reason, _plain(example.get("ja", ""))))

    print(f"예문 {total} | 미표시 {unmarked}")
    print("  방법별 " + " · ".join(f"{name} {count}"
                                 for name, count in sorted(by_method.items())))
    print("  조각 수 " + " · ".join(f"{count}조각 {number}"
                                  for count, number in sorted(pieces_of.items())))
    print(f"\nFAIL {len(fails)} · WARN {len(warns)}")
    for label, rows in (("FAIL", fails), ("WARN", warns)):
        if not rows:
            continue
        print(f"\n--- {label} ---")
        for spot, reason, sentence in rows[:40]:
            print(f"  {spot}: {reason}")
            print(f"      {sentence[:70]}")
        if len(rows) > 40:
            print(f"  … 그리고 {len(rows) - 40}건 더")
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())
