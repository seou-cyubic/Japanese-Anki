# -*- coding: utf-8 -*-
"""常用漢字表 본표 **備考 칸**을 종류별로 갈라낸다.

배경
----
본표는 ``한자 | 음훈 | 例 | 備考`` 4열이다.  備考 칸에는 성격이 전혀 다른 것들이 한
칸에 섞여 들어 있다 — 付表 상호참조, 同訓異字, 자체(字體) 주석, 그리고 **다른 데
어디에도 없는 읽기 정보**가 그것이다.

    音 オン   「観音」は，「カンノン」。          <- 이 읽기는 표의 다른 곳에 없다
    貼 チョウ  「貼付」は，「テンプ」とも。
    側 がわ    「かわ」とも。
    下 もと    ⇔元，本，基                        <- 同訓異字
    下 カ      下手（へた）                        <- 付表 포인터

Stage 3 은 이 칸을 **용례를 캐는 데에만** 썼고, 용례로 보이지 않는 것은 통째로
버렸다.  ``「観音」は，「カンノン」。`` 은 ``は，`` 때문에 걸러져 사라졌다.  그래서
観音·貼付(テンプ)·側(かわ)·大望(タイボウ)·頰(ほほ) 같은 읽기가 산출물 어디에도 없다.

**어떻게 안전하게 넣는가**
--------------------------
두 가지 장치로 '쓸모없는 데이터가 섞이는' 일을 구조적으로 막는다.

1. **모르는 備考 를 만나면 빌드를 실패시킨다.**  ``fuhyo.ADJUDICATED`` 와 같은 방법이다.
   기계적으로 모양이 잡히는 것만 자동으로 가르고, 그러지 못한 것은 ``KNOWN_FREE_TEXT``
   에 **전수로 적어 둔다**(11 개).  둘 다 아니면 ``UnknownNote`` 를 던진다.  원전이
   바뀌거나 PDF 파싱이 흔들리면 조용히 오염되는 대신 시끄럽게 선다.

2. **읽기·용례 칸을 건드리지 않는다.**  여기서 나온 것은 레코드의 새 선택 필드
   ``note`` 에만 들어간다.  ``readings``·``except`` 의 계약은 한 글자도 바뀌지 않으므로,
   備考 가 용례로 새어 들어가는 사고가 일어날 자리 자체가 없다.

종류
----
``same_kun``        同訓異字.  ``⇔元，本，基``
``special_reading`` 그 낱말은 이 읽기다.  ``「観音」は，「カンノン」。``
``also_read``       그 낱말은 이 읽기로도 읽는다.  ``「貼付」は，「テンプ」とも。``
``also_reading``    이 요미카타는 이렇게도 읽는다.  ``「かわ」とも。``
``also_written``    이 낱말은 이렇게도 적는다.  ``「肝腎」は，「肝心」とも書く。``
``text``            위 어디에도 들지 않는 설명.  **원문 그대로** 싣는다.

용례로 쓰이는 것(都道府県名)과 자체 주석(``［餌］＝許容字体``), 付表 포인터는 여기서
아무것도 내놓지 않는다 — 각각 Stage 3 의 용례 추출, Stage 1 의 ``variant``,
``fuhyo`` 가 이미 맡고 있다.  **두 곳에 같은 것을 넣지 않는다.**
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fuhyo  # noqa: E402

KINDS = ("special_reading", "also_read", "also_reading", "also_written",
         "same_kun", "text")

# 자체(字體) 주석과 부표 참조 표시.  Stage 1 의 ``variant`` 가 이미 담고 있다.
_GLYPH_NOTE = re.compile(r"＊?［[^］]*］(?:＝許容字体)?")
# 「…」 안은 인용이므로 付表 참조 지우기를 적용하지 않는다 — ``「羽（は）」`` 처럼
# 인용된 낱말이 참조와 같은 모양이라 통째로 지워지는 일이 있다.
_QUOTED = re.compile(r"「[^」]*」")
_KANJI_RUN = re.compile(r"^[㐀-鿿豈-﫿々〆]+[県府都]?$")

_QUOTE = r"「([^」]+)」"
_BARE = r"「[^」]+」"
# 목록 안쪽은 **잡지 않는다** — 목록 전체를 한 그룹으로 잡아야 짝을 셀 수 있다.
_LIST = rf"{_BARE}(?:[，,]{_BARE})*"


def _quotes(value: str) -> list[str]:
    return re.findall(_QUOTE, value)


_ALSO_READING = re.compile(rf"^{_QUOTE}とも。$")
_PAIRED_ALSO_READ = re.compile(rf"^({_LIST})(?:など)?は，({_LIST})とも。$")
_PAIRED_SPECIAL = re.compile(rf"^({_LIST})(?:など)?は，({_LIST})。$")
_PAIRED_WRITTEN = re.compile(rf"^({_LIST})(?:など)?は，({_LIST})とも書く。$")
_SINGLE_WRITTEN = re.compile(rf"^{_QUOTE}とも書く。$")
_READ_ALSO = re.compile(rf"^{_QUOTE}は，{_QUOTE}と読むこともある。$")


class UnknownNote(ValueError):
    """분류표에 없는 備考.  조용히 버리지 않고 빌드를 세운다."""

    def __init__(self, kanji: str, reading: str, note: str):
        super().__init__(f"모르는 備考 — {kanji} {reading}: {note!r}")
        self.kanji = kanji
        self.reading = reading
        self.note = note


# 기계적으로 모양이 잡히지 않는 備考 **전수**.  뜻을 해석하지 않고 원문 그대로 싣는다 —
# 해석은 사람이 하는 것이 옳고, 여기서 필요한 것은 '이것을 이미 보았다' 는 확인뿐이다.
# 새 문장이 나타나면 이 표에 없으므로 빌드가 선다.
KNOWN_FREE_TEXT = frozenset({
    # 세는 말의 연탁·반탁.  읽기가 앞말에 따라 바뀐다는 설명이다.
    "「羽（は）」は，前に来る音によって「わ」，「ば」，「ぱ」になる。",
    "「把（ハ）」は，前に来る音によって「ワ」，「バ」，「パ」になる。",
    # 이 읽기가 쓰이는 자리를 말한다.  낱말 자체는 Stage 3 이 용례로 캔다.
    "「宮内庁」などと使う。",
    "「京浜」，「京阪」などと使う。",
    # 읽기의 유래·성격.
    "「猟」の字音の転用。",
    "「モウ」は，慣用音。",
    # 뜻이나 쓰임에 대한 주석.
    "「兄弟」は，「ケイテイ」と読むこともある。",
    "「身上」は，「シンショウ」と「シンジョウ」とで，意味が違う。",
    "「山頂」の意。",
    "多く文語の「亡き」で使う。",
    "「憂き」は，文語の連体形。",
})


def _clean(note: str) -> str:
    """자체 주석과 付表 포인터를 걷어낸 몸통.

    付表 포인터 지우기는 **인용부호 밖에만** 건다.  ``「羽（は）」`` 는 포인터와 모양이
    같지만 인용된 낱말이므로 지우면 문장이 무너진다.
    """
    body = _GLYPH_NOTE.sub("", note)
    out = []
    position = 0
    for match in _QUOTED.finditer(body):
        out.append(fuhyo.strip_reference_tokens(body[position:match.start()]))
        out.append(match.group(0))
        position = match.end()
    out.append(fuhyo.strip_reference_tokens(body[position:]))
    return "".join(out).strip().strip("，,、").strip()


def _looks_like_examples(body: str) -> bool:
    """都道府県名처럼 **용례 그 자체**인 備考.  Stage 3 이 이미 용례로 캔다."""
    tokens = [token.strip() for token in re.split(r"[，,]", body) if token.strip()]
    return bool(tokens) and all(_KANJI_RUN.match(token) for token in tokens)


_INLINE_READING = re.compile(r"（[^）]*）")


def _pairs(left: str, right: str) -> list[tuple[str, str]] | None:
    """``「A」，「B」`` 와 ``「가」，「나」`` 를 짝지어 준다.  셀 수 없으면 None.

    낱말 하나에 읽기가 여럿 달리기도 한다 —
    ``「法主（ホッス）」は，「ホウシュ」，「ホッシュ」とも。``  그때는 그 하나에 전부 붙인다.
    수가 둘 다 여럿인데 서로 다르면 짝을 셀 수 없으므로 분류하지 않는다.
    """
    words = [_INLINE_READING.sub("", word).strip() for word in _quotes(left)]
    readings = _quotes(right)
    if not words or not readings:
        return None
    if len(words) == 1:
        return [(words[0], reading) for reading in readings]
    if len(words) != len(readings):
        return None
    return list(zip(words, readings))


def classify(kanji: str, reading: str, note: str) -> list[dict]:
    """備考 하나를 항목들로.  모르는 모양이면 ``UnknownNote``."""
    raw = (note or "").strip()
    if not raw:
        return []

    found: list[dict] = []
    head, _, tail = raw.partition("⇔")
    if tail.strip():
        # 同訓異字.  ``⇔元，本，基`` — 오쿠리가나가 붙은 것도 있다(``⇔無い``).
        others = [piece.strip() for piece in re.split(r"[，,、]", tail) if piece.strip()]
        if others:
            found.append({"kind": "same_kun", "of": reading, "words": others})

    body = _clean(head)
    if not body or _looks_like_examples(body):
        return found

    match = _ALSO_READING.match(body)
    if match:
        found.append({"kind": "also_reading", "of": reading,
                      "reading": match.group(1)})
        return found

    for pattern, kind, field in (
        (_PAIRED_ALSO_READ, "also_read", "reading"),
        (_PAIRED_SPECIAL, "special_reading", "reading"),
        (_PAIRED_WRITTEN, "also_written", "written"),
    ):
        match = pattern.match(body)
        if not match:
            continue
        paired = _pairs(match.group(1), match.group(2))
        if paired is None:
            break
        for word, value in paired:
            found.append({"kind": kind, "of": reading, "word": word, field: value})
        return found

    match = _SINGLE_WRITTEN.match(body)
    if match:
        found.append({"kind": "also_written", "of": reading,
                      "word": kanji, "written": match.group(1)})
        return found

    match = _READ_ALSO.match(body)
    if match:
        found.append({"kind": "also_read", "of": reading,
                      "word": match.group(1), "reading": match.group(2)})
        return found

    if body in KNOWN_FREE_TEXT:
        found.append({"kind": "text", "of": reading, "body": body})
        return found

    raise UnknownNote(kanji, reading, note)


def collect(kanji: str, rows) -> list[dict]:
    """한 한자의 備考 행들을 모아 ``note`` 필드에 실을 목록으로.

    ``rows`` 는 Stage 1·3 이 본표에서 뽑은 ``{reading, ex, note}`` 들이다.  순서는
    표에 실린 순서 그대로 둔다 — 표의 순서가 곧 그 한자의 음훈 순서다.
    """
    found: list[dict] = []
    for row in rows or ():
        for entry in classify(kanji, (row.get("reading") or "").strip(),
                              row.get("note") or ""):
            if entry not in found:
                found.append(entry)
    return found
