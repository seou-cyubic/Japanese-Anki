# -*- coding: utf-8 -*-
"""예문 안에서 그 항목의 문법이 쓰인 구간을 찾아 표시한다.

**왜 표시하는가.**  한 예문만 보고는 그 문장이 어느 문형의 예인지 알 수 없다.
프론트엔드가 문법 부분을 짚어 보여 주려면 구간이 데이터에 있어야 한다.

**표기법.**  구간을 ``*`` 로 감싼다 — ``愛(あい)*あっての*結(けっ)婚(こん)…``.
문자 오프셋 배열도 후보였지만, 사람이 프론트엔드에서 예문을 한 글자라도 고치면
오프셋이 전부 어긋난다.  게다가 우리 표기는 후리가나를 본문 안에 싣기 때문에
'어느 문자열 기준의 오프셋인가' 라는 문제가 하나 더 생긴다.  인라인 표시는 편집을
견디고(사람이 문장을 고쳐도 별표는 문법에 붙어 따라간다) ``split('*')`` 한 번으로
읽을 수 있다.  원문 2,502 예문 어디에도 ``*`` 와 ``＊`` 가 없음을 확인했다.

**어떻게 찾는가.**  표제형은 가나로 적히는데 예문은 한자로 쓴다 —
``あいだ`` 항목의 예문은 ``夏の間``.  그래서 원문 그대로 찾으면 절반도 못 맞춘다.
뽑아 둔 후리가나가 다리가 된다: 한자를 읽기로 바꾼 '읽기 형태' 위에서 찾으면
``夏(なつ)の間(あいだ)`` 가 ``なつのあいだ`` 가 되어 표제형과 맞는다.

**어디를 끊는가.**  경계는 언제나 ``漢字런(よみ)`` 덩이의 바깥이다.  덩이 가운데를
끊으면 ``*後*(あと)`` 처럼 한자와 그 읽기가 갈라져 루비가 붙을 곳을 잃는다
(``groups`` 참조).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from shared.furigana import is_cjk_run  # noqa: E402

MARK = "*"
GENERATED = re.compile(r"\(([^)]*)\)")
KANA_RUN = re.compile(r"[ぁ-ゟァ-ヿー]+")


def groups(annotated):
    """주석 표기를 **덩이** 단위로 가른다.

    덩이는 ``漢字런(よみ)`` 한 벌이거나 글자 하나이고, ``(표기, 읽기, 시작, 끝)``
    으로 돌려준다.  시작·끝은 언제나 덩이 **전체**를 가리킨다.

    **덩이 가운데는 경계가 될 수 없다.**  후리가나는 한자런 전체에 걸리므로 한자와
    그 읽기 사이를 끊으면 읽기가 붙을 곳을 잃는다 — ``*後*(あと)`` 처럼 표시가
    가운데로 들어가면 렌더러는 루비 없는 ``後`` 와 걸릴 한자가 없는 ``(あと)`` 를
    받아, 읽기만 허공에 뜨고 그 자리가 벌어져 보인다.  그래서 위치 대응표는
    글자가 아니라 덩이를 가리킨다.  ``shared/furigana.py`` 의 주석 문법 해석과
    같은 훑기다.
    """
    found = []
    index = 0
    length = len(annotated)
    while index < length:
        if is_cjk_run(annotated[index]):
            end = index
            while end < length and is_cjk_run(annotated[end]):
                end += 1
            if end < length and annotated[end] == "(":
                close = annotated.find(")", end + 1)
                if close != -1:
                    found.append((annotated[index:end], annotated[end + 1:close],
                                  index, close + 1))
                    index = close + 1
                    continue
            # 루비가 붙지 않은 한자런.  글자 하나씩이 곧 덩이다.
            for position in range(index, end):
                found.append((annotated[position], annotated[position],
                              position, position + 1))
            index = end
            continue
        found.append((annotated[index], annotated[index], index, index + 1))
        index += 1
    return found


def views(annotated):
    """주석 표기에서 두 가지 평면 문자열과 원본 위치 대응표를 만든다.

    반환하는 ``plain`` 은 후리가나를 뗀 표기, ``reading`` 은 한자를 그 읽기로 바꾼
    것이다.  각각 글자마다 원본(annotated) 의 어느 구간에서 왔는지를 함께 준다.

    **대응표가 가리키는 것은 글자가 아니라 덩이다**(``groups``).  ``間(あいだ)`` 의
    ``間`` 도 ``あ`` 도 ``間(あいだ)`` 전체를 가리키므로, 이 표로 잘라 낸 구간은
    한자와 그 읽기를 결코 갈라놓지 않는다.
    """
    plain, plain_map = [], []
    reading, reading_map = [], []
    for surface, sound, start, stop in groups(annotated):
        for character in surface:
            plain.append(character)
            plain_map.append((start, stop))
        for character in sound:
            reading.append(character)
            reading_map.append((start, stop))
    return {
        "plain": "".join(plain), "plain_map": plain_map,
        "reading": "".join(reading), "reading_map": reading_map,
    }


def head_patterns(head):
    """표제형 하나에서 시도할 정규식들을 넓은 것부터 좁은 것 순으로 만든다."""
    head = head.strip()
    if not head:
        return []
    out = []

    def compile_form(form):
        pieces = []
        index = 0
        while index < len(form):
            char = form[index]
            if char in "（(":
                close = form.find("）" if char == "（" else ")", index)
                if close != -1:
                    pieces.append("(?:" + re.escape(form[index + 1:close]) + ")?")
                    index = close + 1
                    continue
            if char in "～〜":
                pieces.append(".{0,14}?")
                index += 1
                continue
            pieces.append(re.escape(char))
            index += 1
        return "".join(pieces)

    for form in dict.fromkeys(part for part in re.split(r"[・/｜|]", head) if part):
        body = compile_form(form)
        out.append(("exact", re.compile(body)))
        # 활용: 끝의 る·う·だ·い 를 떼고 뒤에 이어지는 가나를 허용한다.
        stem = re.sub(r"[るうだいなくきしてた]$", "", form)
        if stem and stem != form and len(stem) >= 2:
            out.append(("inflected", re.compile(compile_form(stem) + r"[ぁ-ゟー]{0,4}")))
    return out


def find_span(annotated, head):
    """(시작, 끝, 방법) 을 annotated 기준 위치로.  못 찾으면 None."""
    view = views(annotated)
    for method, pattern in head_patterns(head):
        for surface, offsets, tag in (
            (view["plain"], view["plain_map"], "plain"),
            (view["reading"], view["reading_map"], "reading"),
        ):
            match = pattern.search(surface)
            if not match or match.start() == match.end():
                continue
            start = offsets[match.start()][0]
            end = offsets[match.end() - 1][1]
            return start, end, f"{method}/{tag}"
    return None


def mark(annotated, head):
    """문법 구간을 ``*`` 로 감싼 표기와 쓰인 방법을 돌려준다."""
    found = find_span(annotated, head)
    if found is None:
        return annotated, None
    start, end, method = found
    return f"{annotated[:start]}{MARK}{annotated[start:end]}{MARK}{annotated[end:]}", method


def mark_with_span(annotated, span):
    """모델이 집어 준 **평문** 구간을 주석 표기 위의 위치로 옮겨 표시한다.

    모델은 후리가나를 뗀 평문을 보고 답하므로(``祭りの後``) 그 끝이 한자에 떨어질
    수 있다.  대응표가 덩이를 가리키므로 경계는 저절로 ``後(あと)`` 바깥으로
    물러난다 — ``*後*(あと)`` 는 나올 수 없다(``groups`` 참조).
    """
    view = views(annotated)
    start = view["plain"].find(span)
    if start < 0:
        return annotated, None
    end = start + len(span)
    begin = view["plain_map"][start][0]
    finish = view["plain_map"][end - 1][1]
    return (f"{annotated[:begin]}{MARK}{annotated[begin:finish]}{MARK}"
            f"{annotated[finish:]}"), "model"


def marked_span(marked):
    """표시된 문자열에서 문법 구간만 뽑는다.  프론트엔드가 쓰는 것과 같은 방법."""
    parts = marked.split(MARK)
    return parts[1] if len(parts) >= 3 else ""


def entry_keys(entries):
    """항목마다 안정된 식별자.

    사전에는 **동형이의 항목**이 있다 — ``から``·``うえで`` 처럼 표제형이 같고 뜻이
    다른 것이 64 개.  같은 쪽에 나란히 실린 것도 33 쌍이라 쪽 번호로도 가르지 못한다.
    그래서 같은 표제형 안에서의 등장 순서를 붙인다.  첫 번째는 접미사를 달지 않으므로
    (``あっての``) 나중에 두 번째 뜻이 추가되어도 기존 키가 흔들리지 않는다.
    """
    seen = {}
    keys = []
    for entry in entries:
        head = entry["head"]
        seen[head] = seen.get(head, 0) + 1
        keys.append(head if seen[head] == 1 else f"{head}#{seen[head]}")
    return keys
