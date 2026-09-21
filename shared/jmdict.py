# -*- coding: utf-8 -*-
"""JMdict 표기 -> 읽기.  세 덱이 함께 쓴다.

후리가나가 틀리면 학습자가 그대로 잘못 외운다.  모델이 단 읽기를 **사전에 대 보는**
자리는 토익 덱의 예문 검사와 한자 덱의 용례 후리가나 두 곳이고, 둘이 같은 사전을
같은 방식으로 읽어야 판정이 갈리지 않는다.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict

from shared.paths import JMDICT

__all__ = ["readings"]


def readings() -> dict[str, set[str]]:
    """표기 -> 읽기 집합.  가나만인 낱말은 자기 자신이 읽기다."""
    found: dict[str, set[str]] = defaultdict(set)
    for _event, entry in ET.iterparse(JMDICT, events=("end",)):
        if entry.tag != "entry":
            continue
        kebs = [k.findtext("keb") for k in entry.findall("k_ele")]
        rebs = [r.findtext("reb") for r in entry.findall("r_ele")]
        for keb in kebs:
            found[keb].update(r for r in rebs if r)
        if not kebs:
            for reb in rebs:
                if reb:
                    found[reb].add(reb)
        entry.clear()
    return found
