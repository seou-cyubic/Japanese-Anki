# -*- coding: utf-8 -*-
"""표시 구간이 낱말 한가운데를 자르는지 보기 위한 사전 낱말 목록.

**왜 사전이 필요한가.**  ``たい`` 항목의 예문 ``ああ、暑い。冷たいビールが飲みたいなあ。``
에서 ``たい`` 는 두 번 나온다.  ``冷たい`` 의 것과 ``飲みたい`` 의 것이다.  둘의 **형태는
완전히 같다** — 한자 한 자에 ``たい`` 가 붙었다.  갈라 주는 것은 ``冷たい`` 가 사전에
실린 이형용사 한 낱말이고 ``飲みたい`` 는 낱말이 아니라 ``飲み＋たい`` 라는 사실뿐이다.
그것을 아는 것은 사전이다.

**무엇을 넣고 무엇을 빼는가.**  넣는 것은 **내용어**뿐이다 — 명사·동사·형용사·부사.
조사·조동사·연어(``に対して``)·접두사·접미사는 뺀다.  그것들은 우리가 찾으려는 문법
그 자체이므로, 목록에 들어가면 정답을 스스로 막아 버린다.

**한자 표기와 읽기를 나눠 담는다.**  마킹은 두 평면 위에서 벌어진다 — 후리가나를
뗀 표기(``建物``)와 한자를 읽기로 바꾼 것(``たてもの``).  같은 낱말이라도 어느 평면
위에서 찾느냐에 따라 글자가 다르므로 목록도 둘이다(``marking.Lexicon``).

이 모듈은 **스테이지가 아니다** — 코퍼스를 읽는 함수만 있고 최상위 본문이 없다.
``marking.py`` 는 이것을 import 하지 않는다.  코퍼스는 저장소에 없고, 시험은 갓 받은
저장소에서도 돌아야 하기 때문이다.  목록을 만들어 넣어 주는 것은 부르는 쪽의 몫이다.
"""
from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from marking import Lexicon  # noqa: E402  (같은 폴더의 모듈)

CJK = re.compile(r"[㐀-鿿\U00020000-\U0002A6DF豈-﫿々〆]")
KANA_ONLY = re.compile(r"^[ぁ-ゟァ-ヿー]+$")

# 문법 그 자체인 품사.  목록에 들어가면 찾으려는 것을 스스로 막는다.
GRAMMATICAL = (
    "particle", "auxiliary", "expressions", "conjunction",
    "prefix", "suffix", "interjection", "copula", "counter",
)
# 이 중 하나라도 있어야 '내용어' 다.
CONTENT = ("noun", "verb", "adjectiv", "adverb")

# 두 글자 미만은 어느 구간이든 품을 수 없고, 너무 긴 낱말은 두세 글자짜리 문법
# 조각을 품는 일이 실질적으로 없으면서 훑는 값만 비싸게 만든다.
MIN_LENGTH = 2
MAX_LENGTH = 12
MIN_READING_LENGTH = 3


def _is_content(tags: set[str]) -> bool:
    lowered = " ".join(tags).lower()
    if not any(mark in lowered for mark in CONTENT):
        return False
    # 명사·동사 표시가 있어도 항목 전체가 문법어인 것이 있다(``みたい``).
    return not all(any(bad in tag.lower() for bad in GRAMMATICAL) for tag in tags)


def from_jmdict(path) -> Lexicon:
    """JMdict 에서 내용어의 표기·읽기를 뽑아 ``Lexicon`` 을 만든다."""
    written: set[str] = set()
    spoken: set[str] = set()
    for _event, entry in ET.iterparse(str(path), events=("end",)):
        if entry.tag != "entry":
            continue
        tags: set[str] = set()
        for sense in entry.findall("sense"):
            for part in sense.findall("pos"):
                if part.text:
                    tags.add(part.text)
        if not _is_content(tags):
            entry.clear()
            continue
        kanji = [k.findtext("keb") or "" for k in entry.findall("k_ele")]
        kanji = [form for form in kanji
                 if MIN_LENGTH <= len(form) <= MAX_LENGTH and CJK.search(form)]
        if kanji:
            written.update(kanji)
            for reading in entry.findall("r_ele"):
                sound = reading.findtext("reb") or ""
                if (MIN_READING_LENGTH <= len(sound) <= MAX_LENGTH
                        and KANA_ONLY.match(sound)):
                    spoken.add(sound)
        entry.clear()
    return Lexicon(written, spoken)
