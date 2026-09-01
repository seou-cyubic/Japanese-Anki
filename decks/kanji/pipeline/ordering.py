# -*- coding: utf-8 -*-
"""용례 정렬 규칙 — 파이프라인과 편집기가 공유하는 단일 정의.

한 요미카타 안의 용례는 다음 순서로 놓인다.

1. 한자 길이 오름차순            (표기 ``w`` 의 코드포인트 수)
2. 한국어 뜻 길이 오름차순        (``ko``)
3. 후리가나 길이 오름차순         (``ja`` 에서 복원한 전체 읽기)
4. 한국어 뜻 가나다순             (완성형 한글은 코드포인트 순서가 곧 사전순)

파이프라인 마지막 단계와 편집기 저장 경로 양쪽에서 호출한다.  그래야 사람이
용례를 새로 넣어도 순서가 무너지지 않는다.
"""
import re

_ANNOTATION_RE = re.compile(r"[㐀-鿿\U00020000-\U0002A6DF豈-﫿々〆]+[（(]([ぁ-ゟァ-ヿー]+)[）)]")
_KANA_RE = re.compile(r"[ぁ-ゟァ-ヿー]")
# 반각 괄호만 파이프라인이 붙인 후리가나다.  전각은 원전 인쇄분이라 표기에 남는다.
_GENERATED_RE = re.compile(r"\([^)]*\)")


def plain_surface(annotated):
    """주석에서 생성 후리가나(반각 괄호)를 걷어낸 원 표기.

    의미 정의는 ``frontend.annotations.plain_surface`` 와 같다.  여기서는 길이
    계산만 필요하므로 최소 구현을 두고, 두 구현이 실데이터 전건에서 일치하는지는
    ``test_ordering.py`` 가 검증한다.
    """
    return _GENERATED_RE.sub("", annotated or "")


def furigana_length(example):
    """용례의 전체 읽기 길이.

    표기 ``w`` 는 ``空港(くうこう)`` 처럼 한자런 뒤에 읽기를 괄호로 붙인 꼴이다.
    괄호 안의 읽기와 괄호 밖의 가나(오쿠리가나)를 합치면 전체 읽기가 된다.
    """
    annotated = example.get("w") or ""
    if not annotated:
        return 0
    total = 0
    position = 0
    for match in _ANNOTATION_RE.finditer(annotated):
        total += len(_KANA_RE.findall(annotated[position:match.start()]))
        total += len(match.group(1))
        position = match.end()
    total += len(_KANA_RE.findall(annotated[position:]))
    return total


def example_sort_key(example):
    # '한자 길이' 는 후리가나를 뺀 원 표기의 길이다.
    return (
        len(plain_surface(example.get("w") or "")),
        len(example.get("ko") or ""),
        furigana_length(example),
        example.get("ko") or "",
    )


def sort_examples(examples):
    """용례 리스트를 규칙대로 정렬한 새 리스트로 돌려준다."""
    return sorted(examples, key=example_sort_key)


def sort_record(record):
    """한 한자 레코드의 readings·except 를 제자리에서 정렬한다."""
    for bucket in ("readings", "except"):
        group = record.get(bucket)
        if not isinstance(group, dict):
            continue
        for key, examples in group.items():
            if isinstance(examples, list):
                group[key] = sort_examples(examples)
    return record


def sort_payload(payload):
    """전체 데이터의 모든 용례를 정렬한다."""
    for record in payload.values():
        sort_record(record)
    return payload
