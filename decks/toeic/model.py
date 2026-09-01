# -*- coding: utf-8 -*-
"""토익 덱의 레코드 계약.

레코드 하나는 **영어 낱말 하나**이고, 그 안에 뜻이 하나에서 셋까지 들어 있다.
한 낱말의 여러 뜻은 나란히 놓고 견주어야 '이 낱말이 어떤 자리에 쓰이는가' 가
보이므로, 한자 덱의 요미카타와 같은 자리를 차지한다.

일본어 표기는 다른 두 덱과 **같은 주석 문법**을 쓴다 — 후리가나가 표기 안에 실린다
(``搭乗(とうじょう)する``).  그래서 ``shared/furigana.py`` 와 렌더러의 루비 처리가
그대로 돈다.
"""
from __future__ import annotations

from typing import Any

from shared.furigana import parse_annotated, plain_surface
# 레코드 지문은 덱에 종속되지 않는다.  저장소가 낙관적 잠금에 쓰는 바로 그 함수를
# 그대로 써야 한다 — 따로 만들면 같은 레코드에 다른 열쇠가 나와 저장이 거절된다.
from shared.persistence import record_etag

POS_LABELS = {
    "noun": "명사", "verb": "동사", "adjective": "형용사",
    "adverb": "부사", "function": "기능어",
}
CHECK_LABELS = {
    "jmdict": "사전 확인", "phrase": "구", "unsure": "읽기 미확인",
}
BAND_LABELS = {
    "1-1000": "NGSL 1-1000", "1001-2000": "NGSL 1001-2000",
    "2001-2809": "NGSL 2001-2809", "TSL": "TOEIC 전용",
}
REQUIRED = ("list", "rank", "band", "family", "senses")
SENSE_FIELDS = ("ja", "pos", "gloss", "en", "checked")
SENSE_ORDER = ("ja", "pos", "gloss", "en", "checked", "example")
FIELD_ORDER = ("list", "rank", "sfi", "band", "family", "senses")


def is_written(ja: str) -> bool:
    """일본어 표기가 쓸 만한 모양인가.

    **온전한 주석이거나, 아예 주석이 없거나 둘 중 하나여야 한다.**  반쪽짜리 주석은
    허용하지 않는다 — 어떤 한자에는 읽기가 있고 어떤 한자에는 없으면 학습자가 그
    빠진 곳을 '읽기가 필요 없는 글자' 로 오해한다.

    주석이 아예 없는 것은 허용한다.  ``第２の`` 처럼 숫자가 섞여 읽기를 글자에 맞출
    수 없는 표기가 있고, 그런 것은 억지로 붙이는 것보다 없는 편이 낫다.
    """
    if "(" not in ja and ")" not in ja:
        return True
    return parse_annotated(ja) is not None


def ordered_record(record: dict[str, Any]) -> dict[str, Any]:
    """저장 파일의 필드 순서를 고정한다.  진단 diff 가 읽기 쉬워진다."""
    ordered = {name: record[name] for name in FIELD_ORDER if name in record}
    ordered.update({name: value for name, value in record.items()
                    if name not in ordered})
    return ordered


def sort_record(record: dict[str, Any]) -> dict[str, Any]:
    """뜻의 순서는 **모델이 매긴 빈도 순서**다.  다시 정렬하지 않는다.

    '이 낱말의 어느 뜻이 TOEIC 에 자주 나오는가' 가 이 덱의 알맹이인데, 그 순서를
    글자 수 같은 기계적 기준으로 뒤집으면 알맹이가 사라진다.
    """
    return record


def validate_record(word: str, record: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, dict):
        return [f"{word}: 레코드는 object 여야 한다"]
    for field in REQUIRED:
        if field not in record:
            errors.append(f"{word}: 필수 필드 없음 — {field}")
    if not isinstance(record.get("rank"), int) or record.get("rank", 0) < 1:
        errors.append(f"{word}: rank 는 1 이상의 정수여야 한다")
    if record.get("list") not in ("ngsl", "tsl"):
        errors.append(f"{word}: list 는 ngsl 또는 tsl 이다")
    if record.get("band") not in BAND_LABELS:
        errors.append(f"{word}: 모르는 빈도대 — {record.get('band')!r}")
    family = record.get("family")
    if not isinstance(family, list) or not family:
        errors.append(f"{word}: family 는 비어 있지 않은 목록이어야 한다")
    senses = record.get("senses")
    if not isinstance(senses, list):
        return errors + [f"{word}: senses 는 목록이어야 한다"]
    for index, sense in enumerate(senses):
        spot = f"{word}[{index}]"
        if not isinstance(sense, dict):
            errors.append(f"{spot}: 뜻은 object 여야 한다")
            continue
        for field in SENSE_FIELDS:
            if field not in sense:
                errors.append(f"{spot}: 필수 필드 없음 — {field}")
        if not sense.get("ja"):
            errors.append(f"{spot}: 일본어가 비었다")
        elif not is_written(sense["ja"]):
            errors.append(f"{spot}: 주석이 온전하지 않다 — {sense['ja']!r}")
        if sense.get("pos") not in POS_LABELS:
            errors.append(f"{spot}: 모르는 품사 — {sense.get('pos')!r}")
        if sense.get("checked") not in CHECK_LABELS:
            errors.append(f"{spot}: 모르는 검증 등급 — {sense.get('checked')!r}")
        errors.extend(validate_example(spot, sense.get("example")))
    return errors


def validate_example(spot: str, example: Any) -> list[str]:
    """예문은 **영·일 한 쌍이 온전하거나 아예 없거나** 둘 중 하나다.

    한쪽만 있으면 카드가 반쪽이 된다 — 뜻 뒷면은 두 줄을 나란히 놓아 대조하는
    자리이고, 철자 앞면은 일문만 보고 영문을 짓는 자리다.
    """
    if example is None:
        return []
    if not isinstance(example, dict):
        return [f"{spot}: 예문은 object 여야 한다"]
    errors = []
    if not example.get("en"):
        errors.append(f"{spot}: 영어 예문이 비었다")
    japanese = example.get("ja")
    if not japanese:
        errors.append(f"{spot}: 일본어 예문이 비었다")
    elif not is_written(japanese):
        errors.append(f"{spot}: 예문의 주석이 온전하지 않다 — {japanese[:40]!r}")
    if set(example) - {"en", "ja"}:
        errors.append(f"{spot}: 예문에 모르는 필드 — {sorted(set(example) - {'en', 'ja'})}")
    return errors


def validate_payload(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["토익 데이터 최상위는 object 여야 한다"]
    errors: list[str] = []
    for word, record in payload.items():
        errors.extend(validate_record(word, record))
    return errors


def payload_statistics(payload: dict[str, dict[str, Any]]) -> dict[str, Any]:
    senses = [s for record in payload.values() for s in record["senses"]]
    bands: dict[str, int] = {}
    for record in payload.values():
        bands[record["band"]] = bands.get(record["band"], 0) + 1
    checks: dict[str, int] = {}
    for sense in senses:
        checks[sense["checked"]] = checks.get(sense["checked"], 0) + 1
    return {
        "records": len(payload),
        "words": len(payload),
        "senses": len(senses),
        "examples": sum(1 for s in senses if s.get("example")),
        "empty": sum(1 for r in payload.values() if not r["senses"]),
        "bands": bands,
        "checked": checks,
    }


def derived_senses(record: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for position, sense in enumerate(record.get("senses", []), 1):
        out.append({
            **sense,
            "position": position,
            "plain": plain_surface(sense.get("ja", "")),
            "pos_label": POS_LABELS.get(sense.get("pos", ""), sense.get("pos", "")),
            "check_label": CHECK_LABELS.get(sense.get("checked", ""), ""),
        })
    return out


def project_record(word: str, record: dict[str, Any], *, edited: bool) -> dict[str, Any]:
    """화면이 쓸 봉투.  두 덱과 같은 모양이라 프론트엔드가 덱을 가리지 않는다."""
    senses = derived_senses(record)
    return {
        "schema_version": 1,
        "key": word,
        "record_etag": record_etag(record),
        "edited": edited,
        "record": record,
        "derived": {
            "word": word,
            "band": record.get("band", ""),
            "band_label": BAND_LABELS.get(record.get("band", ""), ""),
            "rank": record.get("rank", 0),
            "list": record.get("list", ""),
            "family": record.get("family", []),
            "senses": senses,
            # 사전으로 확인되지 않은 뜻이 몇인가.  뱃지로 뜬다.
            "unverified": sum(1 for s in senses if s["checked"] != "jmdict"),
        },
    }


def index_row(word: str, record: dict[str, Any]) -> dict[str, Any]:
    """낱말 하나를 검색 색인 한 줄로."""
    terms = [(word, "key", "낱말")]
    for form in record.get("family", []):
        if form.lower() != word:
            terms.append((form, "family", "어형"))
    for sense in record.get("senses", []):
        terms.append((plain_surface(sense.get("ja", "")), "sense", "일본어"))
        terms.append((sense.get("ja", ""), "annotation", "일본어"))
        if sense.get("gloss"):
            terms.append((sense["gloss"], "gloss", "뜻풀이"))
        if sense.get("en"):
            terms.append((sense["en"], "en", "영어 뜻풀이"))
    band = record.get("band", "")
    if band:
        terms.append((BAND_LABELS.get(band, band), "band", "빈도대"))
    first = record.get("senses", [{}])[0] if record.get("senses") else {}
    return {
        "key": word,
        "title": word,
        "subtitle": plain_surface(first.get("ja", "")) or "(뜻 없음)",
        "weight": -record.get("rank", 0),      # 자주 쓰는 낱말이 먼저 온다
        "band": band,
        "senses": len(record.get("senses", [])),
        "_terms": terms,
    }
