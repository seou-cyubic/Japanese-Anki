# -*- coding: utf-8 -*-
"""용례의 한국어 뜻이 요구대로 나왔는지 **전건**에 대고 잰다.  모델을 부르지 않는다.

무엇을 재는가
------------
1. **요미카타가 다르면 뜻도 달라야 한다.**  이것이 이 감사의 본론이다.
   ``音(おと)`` 와 ``音(ね)``, ``下(した)``·``下(しも)``·``下(もと)`` 는 표기가 같지만 다른
   낱말이다.  예전 파이프라인은 작업 단위가 표기 하나였으므로 그 셋이 **구조적으로**
   같은 뜻일 수밖에 없었다 — 실제로 같은 한자 안에서 표기가 겹치는 용례군 44 개가
   전부 같은 뜻이었고, 다른 뜻인 것은 하나도 없었다.  그 수를 여기서 다시 센다.

   같은지 다른지는 글자만 보아서는 모자란다.  ``소리, 음`` 과 ``소리`` 는 다른 문자열이지만
   같은 답이다.  그래서 네 겹으로 본다 — 글자 그대로 · 정규화 후 · 첫 뜻 · 자소 겹침.

2. **뜻의 경계는 줄바꿈 하나다.**  세미콜론이 경계로 남아 있으면 옛 표기가 그대로
   실려 온 것이다.  쉼표·가운뎃점은 한 뜻 안의 글자로 허용하되, 한 뜻에 여럿 있으면
   뜻이 덜 갈린 것일 수 있으므로 사람에게 보인다.

3. **모델이 스스로 남긴 근거와 결과가 어긋나지 않는가.**  프롬프트는 두 요미카타의
   뜻이 정말 같을 때만 ``why`` 에 이유를 적게 한다.  뜻이 같은데 근거가 없으면 그냥
   갈라 쓰지 못한 것이고, 뜻이 다른데 '같다' 고 적혀 있으면 답이 흔들린 것이다.

FAIL 은 규칙으로 확실한 것만이고 나머지는 WARN 이다.  되돌아오는 값은 FAIL 의 수다.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import ordering  # noqa: E402
import paths  # noqa: E402

from decks.kanji.model import MAX_SENSES, senses  # noqa: E402

# 자소가 이만큼 겹치면 '갈랐다' 고 보기 어렵다.
SIMILAR = 0.8
# 한 뜻 안에 이보다 많은 쉼표류가 있으면 아직 덜 갈린 것일 수 있다.
COMMAS = 2

_TRIM = re.compile(r"[()（）\[\]\s,·/]+")


def normalise(meaning: str) -> str:
    """군더더기를 걷어낸 비교용 꼴.  ``소리, 음`` 과 ``소리·음`` 을 같게 만든다."""
    return _TRIM.sub("", meaning)


def overlap(left: str, right: str) -> float:
    """두 뜻의 자소 겹침.  둘 다 비면 1.0(같다)."""
    a, b = set(normalise(left)), set(normalise(right))
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def compare(left: str, right: str,
            why_left: str = "", why_right: str = "") -> tuple[str, str] | None:
    """두 뜻이 갈렸는가.  갈렸으면 None, 아니면 ``(심각도, 사유)``.

    **뜻이 같다고 곧 고장은 아니다.**  ``行く`` 는 ``いく``·``ゆく`` 두 읽기가 있는 한
    낱말이고, ``梅雨`` 는 ``ばいう``·``つゆ`` 로 읽히는 한 낱말이다 — 한국어로 옮기면
    같은 말이 되는 것이 옳다.  프롬프트가 그런 때 ``why`` 에 이유를 적게 해 둔 것은
    이 자리에서 가르기 위해서다.  근거가 서로 다르게 적혀 있으면 모델이 두 읽기를
    **보고서** 같다고 한 것이므로 사람이 볼 일(WARN)이고, 근거가 없으면 그냥 갈라
    쓰지 못한 것이므로 고장(FAIL)이다.

    첫 뜻만 같은 것도 고장이 아니다 — ``汚す`` 는 ``けがす``(도덕적)·``よごす``(물질적)
    가 한국어로는 둘 다 '더럽히다' 로 시작하고, 갈리는 것은 그 뒤의 뜻이다.
    """
    same = left == right or normalise(left) == normalise(right)
    if same:
        distinct = (why_left.strip() and why_right.strip()
                    and normalise(why_left) != normalise(why_right))
        if distinct:
            return "WARN", "뜻이 같다 — 읽기만 다른 한 낱말이라고 적혀 있다"
        return "FAIL", "뜻이 같은데 가르는 근거도 없다"
    if senses(left)[:1] == senses(right)[:1]:
        return "WARN", "첫 뜻이 같다 — 뒤의 뜻으로만 갈린다"
    if overlap(left, right) >= SIMILAR:
        return "WARN", f"뜻이 거의 같다 (겹침 {overlap(left, right):.0%})"
    return None


def _has_boundary_semicolon(meaning: str) -> bool:
    depth = 0
    for character in meaning:
        if character in "(（[［":
            depth += 1
        elif character in ")）]］":
            depth = max(0, depth - 1)
        elif character == ";" and depth == 0:
            return True
    return False


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    payload = json.loads(paths.D5_JAPANESE.read_text(encoding="utf-8"))
    try:
        cache = json.loads(paths.CACHE.read_text(encoding="utf-8"))
        why_of = {key: (value or {}).get("why", "")
                  for key, value in cache.get("gemini-3.7-flash", {})
                  .get("word_ko_v2", {}).items()}
    except (OSError, json.JSONDecodeError):
        why_of = {}

    fails: list[tuple[str, str]] = []
    warns: list[tuple[str, str]] = []
    total = 0
    sense_count: Counter[int] = Counter()

    # --- 2. 표기 규약 ---
    for kanji, record in payload.items():
        for bucket in ("readings", "except"):
            for reading, examples in record.get(bucket, {}).items():
                for example in examples:
                    total += 1
                    meaning = example.get("ko") or ""
                    lines = senses(meaning)
                    sense_count[len(lines)] += 1
                    spot = f"{kanji} {reading} {example.get('w')}"
                    if _has_boundary_semicolon(meaning):
                        fails.append((spot, f"세미콜론이 뜻 경계로 남아 있다 — {meaning!r}"))
                    if len(lines) > MAX_SENSES:
                        fails.append((spot, f"뜻이 {len(lines)}개다"))
                    for line in lines:
                        if len(re.findall(r"[,·/]", line)) >= COMMAS:
                            warns.append((spot, f"한 뜻 안에 쉼표류가 여럿이다 — {line!r}"))

    # --- 1. 요미카타별로 갈렸는가 ---
    groups: dict[str, dict[str, list[tuple[str, str]]]] = defaultdict(
        lambda: defaultdict(list))
    for kanji, record in payload.items():
        for bucket in ("readings", "except"):
            for reading, examples in record.get(bucket, {}).items():
                for example in examples:
                    surface = ordering.plain_surface(example.get("w") or "")
                    groups[kanji][surface].append((
                        reading, example.get("ko") or "",
                        why_of.get(f"{kanji}|{reading}|{surface}", "")))

    checked = 0
    split_ok = 0
    for kanji, surfaces in groups.items():
        for surface, rows in surfaces.items():
            if len(rows) < 2:
                continue
            checked += 1
            verdicts = []
            for index, (reading, meaning, why) in enumerate(rows):
                for other_reading, other, other_why in rows[index + 1:]:
                    found = compare(meaning, other, why, other_why)
                    if found:
                        verdicts.append((found, reading, other_reading, meaning, other))
            if not verdicts:
                split_ok += 1
                continue
            (severity, reason), one, two, left, right = verdicts[0]
            spot = f"{kanji} {surface} ({one} ↔ {two})"
            row = (spot, f"{reason} — {left.splitlines()[0]!r} / {right.splitlines()[0]!r}")
            (fails if severity == "FAIL" else warns).append(row)

    # --- 3. 모델이 남긴 근거 ---
    claimed_same = 0
    for kanji, surfaces in groups.items():
        for surface, rows in surfaces.items():
            if len(rows) < 2:
                continue
            for _reading, _meaning, why in rows:
                if why.strip():
                    claimed_same += 1
                    break

    print(f"용례 {total} | 뜻 개수 " + " · ".join(
        f"{count}개 {number}" for count, number in sorted(sense_count.items())))
    print(f"요미카타가 갈리는 표기 {checked}군 | 뜻이 갈린 것 {split_ok}"
          f" ({split_ok / checked:.0%})" if checked else "겹치는 표기 없음")
    print(f"모델이 근거를 남긴 표기군 {claimed_same}")
    print(f"\nFAIL {len(fails)} · WARN {len(warns)}")
    for label, rows in (("FAIL", fails), ("WARN", warns)):
        if not rows:
            continue
        print(f"\n--- {label} ---")
        for spot, reason in rows[:40]:
            print(f"  {spot}: {reason}")
        if len(rows) > 40:
            print(f"  … 그리고 {len(rows) - 40}건 더")
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())
