# -*- coding: utf-8 -*-
"""Stage 3의 읽기 범주 키를 만드는 순수 함수.

활용 읽기는 사전형 전체나 활용 어간이 아니라, 표기에서 대상 한자가 실제로
담당하는 요미카타에 ``ー``를 붙인다. 예: 生む -> うー, 生える -> はー.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, MutableMapping


UDAN = frozenset("うくぐすつぬぶむる")
NUMERALS = frozenset(
    {
        "ひとつ",
        "ふたつ",
        "みっつ",
        "よっつ",
        "いつつ",
        "むっつ",
        "ななつ",
        "やっつ",
        "ここのつ",
        "いくつ",
        "ます",
    }
)
RENYO_ENDING = {
    "う": "い",
    "く": "き",
    "ぐ": "ぎ",
    "す": "し",
    "つ": "ち",
    "ぬ": "に",
    "ぶ": "び",
    "む": "み",
    "る": "り",
}
_PRINTED_READING_RE = re.compile(r"（[ぁ-ゖゝゞァ-ヺヽヾー]+）")
_HIRAGANA_RE = re.compile(r"[ぁ-ゖゝゞー]")


def is_inflected_reading(reading: str) -> bool:
    """기존 Stage 3과 같은 범위에서 활용형 후보를 판정한다."""
    return bool(
        reading
        and (
            (reading[-1] in UDAN and reading not in NUMERALS)
            or reading[-1] == "い"
        )
    )


def is_jmdict_verb_pos(values: Iterable[str]) -> bool:
    """JMdict entity tag 집합에 실제 동사 품사가 있는지 판정한다."""
    return any(value.startswith("&v") or value == "&aux-v;" for value in values)


def _surface_without_printed_reading(value: str) -> str:
    return _PRINTED_READING_RE.sub("", value).replace("\u3000", "").strip()


def _following_hiragana(surface: str, position: int) -> str:
    end = position + 1
    while end < len(surface) and _HIRAGANA_RE.fullmatch(surface[end]):
        end += 1
    return surface[position + 1 : end]


def infer_actual_kanji_reading(
    kanji: str, reading: str, examples: Iterable[str]
) -> tuple[str, str]:
    """``(대상 한자가 읽는 부분, 판정 근거)``를 반환한다.

    공식표의 대표 용례에는 오쿠리가나가 표면에 남는다. 사전 읽기에서 그
    표면 suffix를 제외하면 대상 한자가 실제로 담당하는 읽기를 얻을 수 있다.
    ``生い立ち``처럼 오단 활용형이 쓰인 경우에는 ``う→い`` 대응을 허용한다.
    자료가 불충분한 행은 마지막 활용 어미 한 글자만 제외해 fail-open한다.
    """
    reading = reading.replace("\u3000", "").strip()
    if not reading:
        return reading, "empty"

    exact: list[tuple[str, int, int]] = []
    renyo: list[tuple[str, int, int]] = []
    order = 0
    for raw_example in examples:
        surface = _surface_without_printed_reading(str(raw_example))
        for position, character in enumerate(surface):
            if character != kanji:
                continue
            suffix = _following_hiragana(surface, position)
            if not suffix:
                continue
            order += 1
            if reading.endswith(suffix):
                prefix = reading[: -len(suffix)]
                if prefix:
                    exact.append((prefix, len(suffix), order))
                continue
            expected = RENYO_ENDING.get(reading[-1])
            if len(suffix) == 1 and expected == suffix:
                prefix = reading[:-1]
                if prefix:
                    renyo.append((prefix, 1, order))

    if exact:
        # 가장 긴 실제 오쿠리가나가 경계를 가장 구체적으로 보여 준다.
        prefix, _, _ = min(exact, key=lambda item: (-item[1], item[2]))
        return prefix, "surface"
    if renyo:
        prefix, _, _ = min(renyo, key=lambda item: item[2])
        return prefix, "renyo"

    fallback = reading[:-1] if len(reading) > 1 else reading
    return fallback, "fallback"


def reading_category_key(
    kanji: str, reading: str, examples: Iterable[str]
) -> tuple[str, str]:
    """원문 읽기를 native 범주 키와 판정 근거로 변환한다."""
    if not is_inflected_reading(reading):
        return reading, "plain"
    actual, method = infer_actual_kanji_reading(kanji, reading, examples)
    if method in {"fallback", "empty"}:
        # 끝 글자 모양만으로 位(くらい), 猿(さる) 같은 명사를 활용형으로
        # 만들지 않는다. 표면 오쿠리가나 근거가 있을 때만 ー를 붙인다.
        return reading, "uninflected"
    return actual + "ー", method


def merge_reading_rows(
    kanji: str,
    readings: dict[str, list[str]],
    stats: MutableMapping[str, int] | None = None,
    evidence: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    """같은 실제 한자 읽기로 귀착되는 활용 행을 순서 보존 병합한다.

    ``evidence``는 경계 판정에만 사용하며 출력 용례에는 절대 추가하지 않는다.
    """
    merged: dict[str, list[str]] = {}
    for reading, examples in readings.items():
        boundary_examples = [*examples, *(evidence or {}).get(reading, [])]
        key, method = reading_category_key(kanji, reading, boundary_examples)
        merged.setdefault(key, []).extend(examples)
        if stats is not None:
            stats[method] = stats.get(method, 0) + 1
    return merged
