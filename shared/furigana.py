"""Pure helpers for the Stage 5 Japanese annotation format.

The pipeline deliberately gives half-width and full-width parentheses different
meanings.  Half-width ``(...)`` is generated ruby and disappears when the source
word is reconstructed.  Full-width ``（...）`` was already printed in the source
word and therefore remains part of ``w``.
"""

from __future__ import annotations

from typing import Any


KATAKANA_TO_HIRAGANA = str.maketrans(
    {chr(codepoint): chr(codepoint - 0x60) for codepoint in range(0x30A1, 0x30F7)}
)


def is_cjk_run(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x2E80 <= codepoint <= 0x2EFF
        or 0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2FFFF
        or character in "々〆"
    )


def is_kana(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x3041 <= codepoint <= 0x309F
        or 0x30A1 <= codepoint <= 0x30FA
        or codepoint == 0x30FC
    )


def to_hiragana(value: str) -> str:
    return value.translate(KATAKANA_TO_HIRAGANA)


def normalized_reading(value: str) -> str:
    return to_hiragana(value).replace("ー", "").replace("っ", "つ").replace("ッ", "ツ")


def reading_kind(value: str) -> str | None:
    """Return the native display group without changing the raw key."""
    # The marker has priority: in this dataset a trailing ー means a conjugating
    # actual Kanji reading, not a Katakana long-vowel mark.  All 876 production markers trail a
    # Hiragana stem.
    if value.endswith("ー"):
        stem = value[:-1]
        if stem and all(0x3041 <= ord(char) <= 0x309F for char in stem):
            return "verb"
        return None
    if value and all(0x30A1 <= ord(char) <= 0x30FA for char in value):
        return "on"
    if value and all(0x3041 <= ord(char) <= 0x309F for char in value):
        return "kun"
    return None


def plain_surface(annotated: str) -> str:
    """주석에서 생성 후리가나를 걷어낸 원 표기.

    반각 ``(…)`` 만 파이프라인이 붙인 것이므로 그것만 지운다.  전각 ``（…）`` 는
    원전에 인쇄된 것이라 표기의 일부로 남는다 — ``一(いち)羽（わ）`` → ``一羽（わ）``.
    """
    if not isinstance(annotated, str):
        return ""
    out: list[str] = []
    index = 0
    while index < len(annotated):
        character = annotated[index]
        if character == "(":
            close_at = annotated.find(")", index + 1)
            if close_at == -1:
                out.append(character)
                index += 1
                continue
            index = close_at + 1
            continue
        out.append(character)
        index += 1
    return "".join(out)


# 소문자·촉음·장음은 조각의 첫 글자가 될 수 없다(모라 경계).
SMALL_KANA = set("ゃゅょぁぃぅぇぉっーャュョァィゥェォッ")


def annotate(surface: str, reading: str) -> str | None:
    """표기와 읽기를 합쳐 이 저장소의 주석 표기로 만든다.

    ``搭乗`` + ``とうじょう``      -> ``搭乗(とうじょう)``
    ``搭乗する`` + ``とうじょうする`` -> ``搭乗(とうじょう)する``
    ``払い戻す`` + ``はらいもどす``   -> ``払(はら)い戻(もど)す``

    **가나는 읽기 위의 고정점이다.**  표기를 [한자런 | 가나리터럴] 로 쪼개면 가나
    리터럴은 읽기 안에 그대로 나타나야 하므로, 그것을 앵커로 삼아 각 한자런이
    담당하는 구간을 정할 수 있다.  한자 덱의 付表 판정(``fuhyo.py``)이 쓰는 것과
    같은 착상이다.

    나눌 자리는 **모라 경계로 제한한다** — ``ゃゅょぁぃぅぇぉっー`` 는 조각의 첫
    글자가 될 수 없다.  이것이 없으면 ``空き状況`` + ``あきじょうきょう`` 에서
    ``空→あきじょう · 状況→ょう`` 라는 있을 수 없는 해가 하나 더 생겨 모호해진다.
    한자 덱의 付表 판정(``fuhyo.py``)이 쓰는 것과 같은 제한이다.

    맞물리지 않거나 해가 둘 이상이면 **조용히 하나를 고르지 않고 ``None`` 을 낸다.**
    부르는 쪽이 그것을 보고 사람에게 넘기거나 주석 없이 둔다.
    """
    found = annotate_candidates(surface, reading, limit=2)
    return found[0] if len(found) == 1 else None


def annotate_candidates(surface: str, reading: str, limit: int = 64) -> list[str]:
    """``annotate`` 가 찾은 **모든** 해.  최대 ``limit`` 개까지 모은다.

    해가 둘 이상이면 ``annotate`` 는 물러난다.  그런데 그 모호함은 대개 조사가
    낱말 읽기 안에도 들어 있어서 생긴다 — ``音楽が流れ`` + ``おんがくがながれ`` 는
    ``音楽→おんがく · 流→な`` 말고도 ``音楽→おん · が · 流→くがな`` 로도 맞물린다.
    그런 경우를 사전으로 가려낼 수 있도록, 부르는 쪽에 후보를 전부 넘긴다.
    """
    if not isinstance(surface, str) or not isinstance(reading, str):
        return []
    if not surface or not reading:
        return []
    if any(character in surface for character in "()（）"):
        return []                         # 이미 주석이 붙어 있다.  건드리지 않는다

    runs: list[tuple[bool, str]] = []      # (한자런인가, 글자들)
    for character in surface:
        kanji = is_cjk_run(character)
        if runs and runs[-1][0] == kanji:
            runs[-1] = (kanji, runs[-1][1] + character)
        else:
            runs.append((kanji, character))
    if not any(kanji for kanji, _text in runs):
        return [surface] if to_hiragana(surface) == to_hiragana(reading) else []

    target = to_hiragana(reading)
    solutions: list[list[str]] = []

    def walk(index: int, position: int, taken: list[str]) -> None:
        if len(solutions) >= limit:
            return                          # 충분히 모았다.  더 볼 것 없다
        if index == len(runs):
            if position == len(target):
                solutions.append(list(taken))
            return
        kanji, text = runs[index]
        if not kanji:
            piece = to_hiragana(text)
            if target.startswith(piece, position):
                taken.append(text)
                walk(index + 1, position + len(piece), taken)
                taken.pop()
            return
        # **한자의 읽기는 소문자·촉음·장음으로 시작할 수 없다**(모라 경계).
        # 이것이 없으면 ``空き状況`` 에서 ``状況→ょう`` 라는 있을 수 없는 해가
        # 하나 더 생겨 모호해진다.  가나 리터럴에는 이 제한을 걸지 않는다 —
        # ``真っ青`` 처럼 표기 자체가 촉음으로 시작하는 자리가 있다.
        if target[position] in SMALL_KANA:
            return
        # 한자런은 적어도 글자 수만큼의 가나를 진다.  뒤에 올 것들의 몫은 남긴다.
        rest = sum(len(chunk) for _is_kanji, chunk in runs[index + 1:])
        for length in range(len(text), len(target) - position - rest + 1):
            piece = target[position:position + length]
            taken.append(f"{text}({piece})")
            walk(index + 1, position + length, taken)
            taken.pop()

    walk(0, 0, [])
    joined = ("".join(solution) for solution in solutions)
    return [annotated for annotated in joined if parse_annotated(annotated)]


def parse_annotated(annotated: str) -> dict[str, Any] | None:
    """표기 하나만으로 주석을 검사한다.  원 표기는 주석에서 되찾는다."""
    return parse_annotation(plain_surface(annotated), annotated)


def parse_annotation(word: str, annotated: str) -> dict[str, Any] | None:
    """Parse a Stage 5 annotation and prove that it reconstructs ``word``.

    Returned segments are intentionally JSON-compatible so the same fixtures can
    be consumed by the browser renderer.
    """
    if not isinstance(word, str) or not isinstance(annotated, str) or not annotated:
        return None

    segments: list[dict[str, str | None]] = []
    reconstructed: list[str] = []
    generated_reading: list[str] = []
    full_reading: list[str] = []
    index = 0

    while index < len(annotated):
        character = annotated[index]
        if is_cjk_run(character):
            end = index
            while end < len(annotated) and is_cjk_run(annotated[end]):
                end += 1
            surface = annotated[index:end]
            if end >= len(annotated) or annotated[end] not in ("(", "（"):
                return None
            opening = annotated[end]
            closing = ")" if opening == "(" else "）"
            close_at = annotated.find(closing, end + 1)
            if close_at == -1:
                return None
            reading = annotated[end + 1 : close_at]
            if not reading or not all(is_kana(char) for char in reading):
                return None

            source = "generated" if opening == "(" else "printed"
            segments.append({"surface": surface, "reading": reading, "source": source})
            full_reading.append(reading)
            if source == "generated":
                reconstructed.append(surface)
                generated_reading.append(reading)
            else:
                reconstructed.append(surface + opening + reading + closing)
            index = close_at + 1
            continue

        end = index + 1
        while end < len(annotated) and not is_cjk_run(annotated[end]):
            end += 1
        literal = annotated[index:end]
        segments.append({"surface": literal, "reading": None, "source": "literal"})
        reconstructed.append(literal)
        for char in literal:
            if is_kana(char):
                generated_reading.append(char)
                full_reading.append(char)
        index = end

    rebuilt = "".join(reconstructed)
    if rebuilt != word:
        return None
    return {
        "segments": segments,
        "word": rebuilt,
        "new": "".join(generated_reading),
        "all": "".join(full_reading),
    }


def reading_matches(parsed: dict[str, Any], raw_key: str) -> bool:
    return normalized_reading(raw_key.replace("ー", "")) in normalized_reading(parsed["all"])


# ---------------------------------------------------------------------------
# Anki 후리가나 표기법
# ---------------------------------------------------------------------------
# Anki 의 Japanese Support 는 ``漢字[かんじ]`` 꼴로 루비를 읽는데, **읽기가 걸리는
# 범위는 "직전 공백 이후"** 다.  그래서 앞에 다른 글자가 붙어 있으면 공백을 하나
# 넣어 경계를 만들어 주어야 한다.
#
#   空港(くうこう)        -> 空港[くうこう]
#   承(うけたまわ)る      -> 承[うけたまわ]る
#   お巡(まわ)りさん      -> お 巡[まわ]りさん      ← 「お」 뒤에 공백이 필요하다
#   離(はな)れ離(ばな)れ  -> 離[はな]れ 離[ばな]れ
#
# 전각 ``（…）`` 는 원전에 인쇄된 읽기라 표기의 일부다.  Anki 루비로 바꾸지 않고
# 그대로 둔다 — 바꾸면 원전에 없던 읽기를 붙인 것이 된다.

def to_anki_ruby(annotated: str) -> str:
    """프로젝트 주석을 Anki 루비 표기로 옮긴다."""
    if not isinstance(annotated, str) or not annotated:
        return ""
    out: list[str] = []
    index = 0
    length = len(annotated)
    while index < length:
        character = annotated[index]
        if is_cjk_run(character):
            end = index
            while end < length and is_cjk_run(annotated[end]):
                end += 1
            surface = annotated[index:end]
            if end < length and annotated[end] == "(":
                close_at = annotated.find(")", end + 1)
                if close_at != -1:
                    reading = annotated[end + 1:close_at]
                    # 앞에 글자가 있으면 읽기 범위를 끊기 위해 공백을 넣는다.
                    if out and not out[-1].endswith(" "):
                        out.append(" ")
                    out.append(f"{surface}[{reading}]")
                    index = close_at + 1
                    continue
            out.append(surface)
            index = end
            continue
        out.append(character)
        index += 1
    return "".join(out)


def to_ruby_html(annotated: str, escape: bool = True) -> str:
    """주석을 ``<ruby>`` HTML 로.  **후리가나가 한자 위에 붙는다.**

    ``漢字[かんじ]`` 표기는 Anki 의 Japanese Support 애드온이 있어야 루비로 그려지고,
    없으면 대괄호가 글자 그대로 한자 **옆에** 찍힌다.  애드온 유무에 기대지 않도록
    HTML 을 직접 낸다 — 브라우저와 Anki 가 똑같이 위에 올려 준다.

    전각 ``（…）`` 는 원전에 인쇄된 읽기라 표기의 일부이므로 루비로 바꾸지 않는다.
    """
    if not isinstance(annotated, str) or not annotated:
        return ""

    def out(text: str) -> str:
        if not escape:
            return text
        return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    pieces: list[str] = []
    index = 0
    length = len(annotated)
    while index < length:
        character = annotated[index]
        if is_cjk_run(character):
            end = index
            while end < length and is_cjk_run(annotated[end]):
                end += 1
            surface = annotated[index:end]
            if end < length and annotated[end] == "(":
                close_at = annotated.find(")", end + 1)
                if close_at != -1:
                    reading = annotated[end + 1:close_at]
                    pieces.append(
                        f"<ruby>{out(surface)}<rt>{out(reading)}</rt></ruby>")
                    index = close_at + 1
                    continue
            pieces.append(out(surface))
            index = end
            continue
        pieces.append(out(character))
        index += 1
    return "".join(pieces)
