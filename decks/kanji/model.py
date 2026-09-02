"""The exact native contract of ``data_japanese.json``.

Nothing in this module knows about the legacy envelope, JIS metadata, corpus
frequency, or legacy reading/example provenance.  Those values do not exist in
the current artifact and must not be invented by the editor.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from shared.persistence import record_etag as shared_record_etag
from shared.furigana import (
    parse_annotated,
    plain_surface,
    reading_kind,
    reading_matches,
    to_hiragana,
)


TAGS = ("s1", "s2", "s3", "s4", "s5", "s6", "j", "h")
TAG_LABELS = {
    "s1": "소학교 1학년",
    "s2": "소학교 2학년",
    "s3": "소학교 3학년",
    "s4": "소학교 4학년",
    "s5": "소학교 5학년",
    "s6": "소학교 6학년",
    "j": "학년 외 상용한자",
    "h": "표외한자",
}
VARIANT_LABELS = (
    "康熙字典体",
    "簡易慣用字体",
    "許容字体",
    "印刷標準字体（表外漢字字体表）",
)
REQUIRED_FIELDS = ("tag", "variant", "except", "readings", "korean")
OPTIONAL_FIELDS = ("korean_src", "note")

# 常用漢字表 본표 備考 칸에서 온 것.  **읽기·용례와 섞이지 않는 자리**다 —
# `decks/kanji/pipeline/notes.py` 참조.
NOTE_KINDS = {
    "special_reading": ("of", "word", "reading"),
    "also_read": ("of", "word", "reading"),
    "also_reading": ("of", "reading"),
    "also_written": ("of", "word", "written"),
    "same_kun": ("of", "words"),
    "text": ("of", "body"),
}
# 후리가나는 표기 `w` 안에 실린다.  별도의 `ja` 필드는 없다.
EXAMPLE_FIELDS = ("w", "ko")

# 한 용례가 가질 수 있는 뜻의 최대 개수.  그 이상은 카드 한 줄에 담기지 않고,
# 그만큼 갈라야 할 만큼 다의적인 낱말이면 용례로 삼은 것 자체를 다시 봐야 한다.
MAX_SENSES = 3
SENSE_SEPARATOR = "\n"


class ContractError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__(errors[0] if errors else "데이터 계약 위반")
        self.errors = errors


def is_one_codepoint(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 1


def codepoint_label(character: str) -> str:
    return f"U+{ord(character):04X}"


def senses(korean_meaning: str) -> list[str]:
    """용례의 뜻 문자열을 **뜻 하나씩**으로 가른다.

    **가르는 것은 줄바꿈 하나뿐이다.**  예전에는 이 자리에 쉼표와 세미콜론이 섞여
    있었는데, 그 둘의 뜻을 정한 곳이 어디에도 없었다 — 뜻을 받아 오는 프롬프트에
    구분자 이야기가 한 글자도 없었으므로, 그것은 규약이 아니라 모델의 그때그때의
    습관이었다.  실제로 세미콜론의 절반 가까이는 다른 뜻이 아니라 앞 낱말의 우리말
    풀이였고(``역내; 구역의 안``), 쉼표 쪽에는 명백히 다른 뜻이 들어 있었다
    (``눈알, 안구, (비유) 주요 상품``).  그래서 그 둘을 해석하는 대신 **뜻을 다시 받아**
    경계를 줄바꿈 하나로 못박았다.

    쉼표·가운뎃점은 이제 뜻의 경계가 아니라 **한 뜻 안의 글자**다 —
    ``송죽매, 소나무·대나무·매화나무`` 는 뜻 하나다.
    """
    return [line.strip() for line in str(korean_meaning or "").split(SENSE_SEPARATOR)
            if line.strip()]


def first_sense(korean_meaning: str) -> str:
    """대표 뜻.  정렬과 검색이 문자열 하나를 필요로 하는 자리에 쓴다."""
    found = senses(korean_meaning)
    return found[0] if found else ""


def _top_level_semicolon(value: str) -> bool:
    """괄호 **밖**의 세미콜론이 있는가.

    ``일위(자위대 계급의 하나; 대위)`` 처럼 괄호 안의 세미콜론은 뜻풀이의 글자이지
    뜻의 경계가 아니다.  경계로 쓰인 것만 잡는다.
    """
    depth = 0
    for character in value:
        if character in "(（[［":
            depth += 1
        elif character in ")）]］":
            depth = max(0, depth - 1)
        elif character == ";" and depth == 0:
            return True
    return False


def korean_display(korean: dict[str, list[str]]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for readings in korean.values():
        for value in readings:
            if value not in seen:
                seen.add(value)
                output.append(value)
    return output


# 레코드 지문은 덱에 종속되지 않는다.  ``shared/persistence.py`` 에 있고, 오래
# 여기 있었으므로 이름만 다시 내보낸다.
record_etag = shared_record_etag


def ordered_record(record: dict[str, Any]) -> dict[str, Any]:
    ordered: dict[str, Any] = {name: record[name] for name in REQUIRED_FIELDS}
    for name in OPTIONAL_FIELDS:
        if record.get(name) is not None:
            ordered[name] = record[name]
    return ordered


def _validate_example(
    example: Any,
    spot: str,
    errors: list[str],
    *,
    required_reading: str | None = None,
) -> None:
    if not isinstance(example, dict):
        errors.append(spot + "은 object여야 한다")
        return
    missing = [field for field in EXAMPLE_FIELDS if field not in example]
    unknown = [field for field in example if field not in EXAMPLE_FIELDS]
    if missing:
        errors.append(spot + " 필수 필드 누락: " + ", ".join(missing))
        return
    if unknown:
        errors.append(spot + " 현재 스키마에 없는 필드: " + ", ".join(unknown))
    for field in EXAMPLE_FIELDS:
        value = example.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(spot + f" `{field}`가 비었다")
        elif value != value.strip():
            errors.append(spot + f" `{field}` 앞뒤에 공백이 있다")
    meaning = example.get("ko")
    if isinstance(meaning, str) and meaning.strip():
        found = senses(meaning)
        if len(found) > MAX_SENSES:
            errors.append(spot + f" `ko`의 뜻이 {len(found)}개다 — {MAX_SENSES}개까지다")
        if any(line != line.strip() or not line.strip()
               for line in meaning.split(SENSE_SEPARATOR)):
            errors.append(spot + " `ko`에 빈 줄이나 줄 앞뒤 공백이 있다")
        if _top_level_semicolon(meaning):
            # 뜻을 가르는 것은 줄바꿈뿐이다.  세미콜론이 경계로 남아 있다는 것은
            # 옛 표기가 그대로 실려 왔다는 뜻이므로, 조용히 넘기지 않는다.
            errors.append(spot + " `ko`에 뜻을 가르는 세미콜론이 남아 있다")
    if not isinstance(example.get("w"), str):
        return
    # 후리가나는 별도 필드가 아니라 표기 안에 실린다.  주석 문법이 성립하는지만 본다.
    parsed = parse_annotated(example["w"])
    if parsed is None:
        errors.append(spot + " `w`의 후리가나 주석이 문법에 맞지 않는다")
    elif required_reading is not None and not reading_matches(parsed, required_reading):
        errors.append(spot + f" 전체 읽기에 특례 읽기 `{required_reading}`가 들어있지 않다")


def _validate_notes(character: str, note: Any) -> list[str]:
    """``note`` 는 備考 항목의 목록이고, 항목마다 종류가 필드를 정한다.

    종류마다 필드를 **정확히** 요구한다.  備考 는 성격이 다른 것들이 한 칸에 섞여
    있던 자리이므로, 무엇이 들어와도 되는 느슨한 칸을 하나 더 만들면 처음 문제가
    자리만 옮겨 되풀이된다.
    """
    prefix = f"{character}: note "
    if not isinstance(note, list) or not note:
        return [prefix + "는 비어 있지 않은 목록이어야 한다"]
    errors: list[str] = []
    for index, entry in enumerate(note):
        spot = prefix + f"{index + 1}번"
        if not isinstance(entry, dict):
            errors.append(spot + "은 object여야 한다")
            continue
        kind = entry.get("kind")
        if kind not in NOTE_KINDS:
            errors.append(spot + f" 모르는 종류 — {kind!r}")
            continue
        wanted = set(NOTE_KINDS[kind]) | {"kind"}
        missing = sorted(wanted - set(entry))
        unknown = sorted(set(entry) - wanted)
        if missing:
            errors.append(spot + " 필수 필드 없음: " + ", ".join(missing))
        if unknown:
            errors.append(spot + " 모르는 필드: " + ", ".join(unknown))
        for field, value in entry.items():
            if field == "words":
                if not isinstance(value, list) or not value or not all(
                        isinstance(word, str) and word.strip() for word in value):
                    errors.append(spot + " words 는 비어 있지 않은 문자열 배열이어야 한다")
            elif not isinstance(value, str) or not value.strip():
                errors.append(spot + f" `{field}`가 비었다")
    return errors


def validate_record(character: str, record: Any) -> list[str]:
    errors: list[str] = []
    prefix = f"{character}: "
    if not is_one_codepoint(character):
        return [prefix + "최상위 키는 유니코드 코드 포인트 한 글자여야 한다"]
    if not isinstance(record, dict):
        return [prefix + "레코드는 object여야 한다"]

    allowed = set(REQUIRED_FIELDS + OPTIONAL_FIELDS)
    missing = [field for field in REQUIRED_FIELDS if field not in record]
    unknown = [field for field in record if field not in allowed]
    if missing:
        errors.append(prefix + "필수 필드 누락: " + ", ".join(missing))
    if unknown:
        errors.append(prefix + "현재 스키마에 없는 필드: " + ", ".join(unknown))
    if missing:
        return errors

    if record["tag"] not in TAGS:
        errors.append(prefix + f"tag는 {', '.join(TAGS)} 중 하나여야 한다")

    variants = record["variant"]
    if not isinstance(variants, dict):
        errors.append(prefix + "variant는 {이체자: 라벨} object여야 한다")
        variants = {}
    else:
        for variant, label in variants.items():
            if not is_one_codepoint(variant):
                errors.append(prefix + f"variant 키 `{variant}`는 코드 포인트 한 글자여야 한다")
            if not isinstance(label, str) or label not in VARIANT_LABELS:
                errors.append(prefix + f"variant `{variant}`의 라벨이 허용 목록에 없다")

    exceptions = record["except"]
    if not isinstance(exceptions, dict):
        errors.append(prefix + "except는 {읽기 조각: [{w, ko, ja}]} object여야 한다")
    else:
        for reading, examples in exceptions.items():
            where = prefix + f"except `{reading}`"
            valid_reading = (
                isinstance(reading, str)
                and bool(reading)
                and all(0x3041 <= ord(char) <= 0x309F for char in reading)
            )
            if not valid_reading:
                errors.append(prefix + "except 읽기 키는 비어 있지 않은 히라가나여야 한다")
            if not isinstance(examples, list) or not examples:
                errors.append(where + "의 특례 용례 배열이 비었다")
                continue
            for index, example in enumerate(examples):
                _validate_example(
                    example,
                    where + f" 용례 {index + 1}",
                    errors,
                    required_reading=reading if valid_reading else None,
                )

    readings = record["readings"]
    if not isinstance(readings, dict) or not readings:
        errors.append(prefix + "readings는 하나 이상의 raw 읽기 키를 가진 object여야 한다")
    else:
        for raw_key, examples in readings.items():
            where = prefix + f"readings `{raw_key}`"
            if not isinstance(raw_key, str) or reading_kind(raw_key) is None:
                errors.append(where + "는 가타카나 음독, 히라가나 훈독 또는 동사 활용 키가 아니다")
            if not isinstance(examples, list) or not examples:
                errors.append(where + "의 용례 배열이 비었다")
                continue
            for index, example in enumerate(examples):
                _validate_example(example, where + f" 용례 {index + 1}", errors)

    if "note" in record:
        errors.extend(_validate_notes(character, record["note"]))

    korean = record["korean"]
    if not isinstance(korean, dict):
        errors.append(prefix + "korean은 {형태: [훈음]} object여야 한다")
    else:
        if "본" not in korean:
            errors.append(prefix + "korean에는 `본` 키가 반드시 있어야 한다")
        aggregate = 0
        for form, values in korean.items():
            where = prefix + f"korean `{form}`"
            if form != "본" and (not is_one_codepoint(form) or form not in variants):
                errors.append(where + "은 현재 variant에 선언된 한 글자여야 한다")
            if not isinstance(values, list):
                errors.append(where + "은 문자열 배열이어야 한다")
                continue
            if form != "본" and not values:
                errors.append(where + "은 비어 있으면 키 자체를 제거해야 한다")
            aggregate += len(values)
            for index, value in enumerate(values):
                if not isinstance(value, str) or not value.strip():
                    errors.append(where + f" 값 {index + 1}이 비었다")
                elif value != value.strip():
                    errors.append(where + f" 값 {index + 1} 앞뒤에 공백이 있다")
        if aggregate == 0:
            errors.append(prefix + "모든 형태를 합친 한국 훈음이 비었다")

    if "korean_src" in record and record["korean_src"] != "gemini":
        errors.append(prefix + "korean_src는 생략하거나 `gemini`여야 한다")
    return errors


def validate_payload(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["최상위 JSON은 {한자: 레코드} object여야 한다"]
    errors: list[str] = []
    for character, record in payload.items():
        errors.extend(validate_record(character, record))
    return errors


def payload_statistics(payload: dict[str, dict[str, Any]]) -> dict[str, Any]:
    tags = Counter(record["tag"] for record in payload.values())
    readings = sum(len(record["readings"]) for record in payload.values())
    regular_examples = sum(
        len(items)
        for record in payload.values()
        for items in record["readings"].values()
    )
    exception_examples = sum(
        len(items)
        for record in payload.values()
        for items in record["except"].values()
    )
    return {
        "characters": len(payload),
        "readings": readings,
        "examples": regular_examples + exception_examples,
        "regular_examples": regular_examples,
        "variants": sum(len(record["variant"]) for record in payload.values()),
        "exception_readings": sum(len(record["except"]) for record in payload.values()),
        "exception_examples": exception_examples,
        "tags": {tag: tags.get(tag, 0) for tag in TAGS},
    }


def project_record(character: str, record: dict[str, Any], *, edited: bool) -> dict[str, Any]:
    reading_rows = []
    warning_count = 0
    for raw_key, examples in record["readings"].items():
        parsed_examples = []
        for example in examples:
            parsed = parse_annotated(example["w"])
            matches = bool(parsed and reading_matches(parsed, raw_key))
            if not matches:
                warning_count += 1
            parsed_examples.append({**example, "annotation": parsed, "reading_matches": matches})
        reading_rows.append(
            {
                "raw_key": raw_key,
                "display": to_hiragana(raw_key),
                "group": reading_kind(raw_key),
                "examples": parsed_examples,
            }
        )
    regular_example_count = sum(len(items) for items in record["readings"].values())
    exception_example_count = sum(len(items) for items in record["except"].values())
    return {
        "schema_version": 1,
        "key": character,
        "character": character,
        "codepoint": codepoint_label(character),
        "record_etag": record_etag(record),
        "edited": edited,
        "record": record,
        "derived": {
            "tag_label": TAG_LABELS[record["tag"]],
            "korean_display": korean_display(record["korean"]),
            "reading_count": len(record["readings"]),
            "example_count": regular_example_count + exception_example_count,
            "regular_example_count": regular_example_count,
            "exception_example_count": exception_example_count,
            "annotation_warnings": warning_count,
            "readings": reading_rows,
        },
    }


def diff_values(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    if isinstance(before, dict) and isinstance(after, dict):
        keys = list(before) + [key for key in after if key not in before]
        for key in keys:
            child = f"{path}.{key}" if path else key
            if key not in before:
                changes.append({"path": child, "before": None, "after": after[key]})
            elif key not in after:
                changes.append({"path": child, "before": before[key], "after": None})
            else:
                changes.extend(diff_values(before[key], after[key], child))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        for index in range(max(len(before), len(after))):
            child = f"{path}[{index}]"
            if index >= len(before):
                changes.append({"path": child, "before": None, "after": after[index]})
            elif index >= len(after):
                changes.append({"path": child, "before": before[index], "after": None})
            else:
                changes.extend(diff_values(before[index], after[index], child))
        return changes
    if before != after:
        changes.append({"path": path, "before": before, "after": after})
    return changes


# ---------------------------------------------------------------------------
# 검색 색인
# ---------------------------------------------------------------------------

def index_row(character: str, record: dict[str, Any]) -> dict[str, Any]:
    """한 한자를 검색 색인 한 줄로.

    ``_terms`` 는 ``(찾을 문자열, 종류, 맥락)`` 의 목록이다.  종류는 검색 결과의
    우선순위를 정하는 데 쓰인다(``shared/deckspec.py`` 의
    ``DeckSpec.search_priorities``).
    """
    terms: list[tuple[str, str, str]] = [(character, "key", "본자")]
    for variant, label in record["variant"].items():
        terms.append((variant, "variant", label))
        terms.append((label, "variant_label", variant))
    terms.append((record["tag"], "tag", TAG_LABELS[record["tag"]]))
    terms.append((TAG_LABELS[record["tag"]], "tag", record["tag"]))
    for form, values in record["korean"].items():
        if form != "본":
            terms.append((form, "korean_form", form))
        terms.extend((value, "korean", form) for value in values)
    for raw_key, examples in record["readings"].items():
        terms.append((raw_key, "reading", raw_key))
        hira = to_hiragana(raw_key)
        if hira != raw_key:
            terms.append((hira, "reading_alias", raw_key))
        for example in examples:
            # 표기는 후리가나가 실린 꼴과 벗긴 꼴 둘 다로 찾을 수 있어야 한다.
            terms.append((plain_surface(example["w"]), "word", raw_key))
            terms.append((example["ko"], "meaning", raw_key))
            terms.append((example["w"], "annotation", raw_key))
    for fragment, examples in record["except"].items():
        terms.append((fragment, "exception", fragment))
        for example in examples:
            terms.append((plain_surface(example["w"]), "word", fragment))
            terms.append((example["ko"], "meaning", fragment))
            terms.append((example["w"], "annotation", fragment))
    if record.get("korean_src"):
        terms.append((record["korean_src"], "korean_src", "한국 훈음 출처"))

    examples = (sum(len(items) for items in record["readings"].values())
                + sum(len(items) for items in record["except"].values()))
    return {
        "key": character,
        "title": character,
        "subtitle": " · ".join(korean_display(record["korean"])),
        "weight": examples,
        "codepoint": codepoint_label(character),
        "tag": record["tag"],
        "tag_label": TAG_LABELS[record["tag"]],
        "readings": len(record["readings"]),
        "examples": examples,
        "variants": len(record["variant"]),
        "exceptions": len(record["except"]),
        "_terms": terms,
    }
