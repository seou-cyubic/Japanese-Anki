# -*- coding: utf-8 -*-
"""용례의 한국어 뜻이 지키기로 한 것 둘.

1. **요미카타가 다르면 뜻도 다르다.**  ``音(おと)`` 와 ``音(ね)`` 는 표기가 같아도 다른
   낱말이다.  예전에는 파이프라인의 작업 단위가 표기 하나였으므로 그 둘이 **구조적으로**
   같은 뜻일 수밖에 없었다 — 프롬프트를 아무리 고쳐도 갈릴 수 없었다.  이 시험이
   잠그는 것은 그 구조가 돌아오지 않는다는 사실이다.

2. **뜻의 경계는 줄바꿈 하나다.**  쉼표와 세미콜론은 규약이었던 적이 없다 — 뜻을
   받아 오는 프롬프트에 구분자 이야기가 한 글자도 없었고, 그래서 세미콜론의 절반
   가까이가 다른 뜻이 아니라 앞 낱말의 우리말 풀이였다(``역내; 구역의 안``).
   이제 뜻을 가르는 것은 줄바꿈뿐이고, 세미콜론이 경계로 남아 있으면 옛 표기가 그대로
   실려 온 것이다.
"""
from __future__ import annotations

import sys
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "decks" / "kanji" / "pipeline"))

from tests import load  # noqa: E402

import audit_meanings  # noqa: E402
import ordering  # noqa: E402

from decks.kanji.model import (  # noqa: E402
    MAX_SENSES,
    first_sense,
    senses,
    validate_record,
)


class SenseSyntaxTest(unittest.TestCase):
    """뜻을 가르는 것은 줄바꿈 하나뿐이다."""

    def test_a_single_meaning_is_one_sense(self) -> None:
        self.assertEqual(senses("아래"), ["아래"])

    def test_newlines_separate_senses(self) -> None:
        self.assertEqual(senses("눈알\n(비유) 주요 상품"), ["눈알", "(비유) 주요 상품"])

    def test_commas_do_not_separate_senses(self) -> None:
        """쉼표·가운뎃점은 한 뜻 **안**의 글자다 — ``소나무·대나무·매화나무`` 는 한 뜻이다."""
        self.assertEqual(senses("송죽매, 소나무·대나무·매화나무"),
                         ["송죽매, 소나무·대나무·매화나무"])

    def test_the_first_sense_represents_the_example(self) -> None:
        self.assertEqual(first_sense("눈알\n(비유) 주요 상품"), "눈알")

    def test_a_boundary_semicolon_is_a_contract_error(self) -> None:
        errors = validate_record("音", _record(ko="역내; 구역의 안"))
        self.assertTrue(any("세미콜론" in message for message in errors), errors)

    def test_a_semicolon_inside_parentheses_is_content(self) -> None:
        """``일위(자위대 계급의 하나; 대위)`` 의 세미콜론은 뜻의 경계가 아니다."""
        self.assertEqual(validate_record("音", _record(ko="일위(계급의 하나; 대위)")), [])

    def test_too_many_senses_is_a_contract_error(self) -> None:
        errors = validate_record("音", _record(ko="\n".join("가나다라")))
        self.assertTrue(any("뜻이" in message for message in errors), errors)


class SenseComparisonTest(unittest.TestCase):
    """'갈렸는가' 는 글자만 보아서는 알 수 없다."""

    def test_identical_meanings_fail(self) -> None:
        self.assertEqual(audit_meanings.compare("소리", "소리")[0], "FAIL")

    def test_the_same_meaning_written_differently_fails(self) -> None:
        self.assertEqual(audit_meanings.compare("소리, 음", "소리·음")[0], "FAIL")

    def test_sharing_only_the_first_sense_is_a_warning(self) -> None:
        """``汚す`` 는 ``けがす``·``よごす`` 가 한국어로 둘 다 '더럽히다' 로 시작한다.

        갈리는 것은 그 뒤의 뜻이므로 고장이 아니라 사람이 볼 일이다.
        """
        self.assertEqual(audit_meanings.compare("소리\n음색", "소리\n울림")[0], "WARN")

    def test_the_same_meaning_with_a_recorded_reason_is_a_warning(self) -> None:
        """``行く`` 는 ``いく``·``ゆく`` 두 읽기를 가진 한 낱말이다 — 뜻이 같은 것이 옳다.

        프롬프트가 그럴 때 ``why`` 에 이유를 적게 해 둔 것은 이 자리에서 가르기 위해서다.
        """
        self.assertEqual(
            audit_meanings.compare("가다", "가다", "현대 구어", "문어적")[0], "WARN")

    def test_the_same_meaning_without_a_reason_fails(self) -> None:
        self.assertEqual(audit_meanings.compare("가다", "가다", "", "")[0], "FAIL")

    def test_genuinely_different_meanings_pass(self) -> None:
        self.assertIsNone(audit_meanings.compare(
            "귀에 들리는 소리", "정취가 실린 울림"))


class ProductionMeaningTest(unittest.TestCase):
    """산출물 전건.  아직 파이프라인을 돌리지 않았으면 건너뛴다."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = load("kanji", "data_japanese.json")

    def _examples(self):
        for kanji, record in self.payload.items():
            for bucket in ("readings", "except"):
                for reading, examples in record.get(bucket, {}).items():
                    for example in examples:
                        yield kanji, reading, example

    def test_no_meaning_keeps_a_boundary_semicolon(self) -> None:
        found = [f"{kanji} {reading} {example['w']}: {example['ko']!r}"
                 for kanji, reading, example in self._examples()
                 if audit_meanings._has_boundary_semicolon(example.get("ko") or "")]
        self.assertEqual(found[:5], [], f"{len(found)}건")

    def test_no_meaning_has_more_senses_than_the_contract_allows(self) -> None:
        found = [f"{kanji} {example['w']}"
                 for kanji, _reading, example in self._examples()
                 if len(senses(example.get("ko") or "")) > MAX_SENSES]
        self.assertEqual(found[:5], [], f"{len(found)}건")

    def test_the_same_spelling_under_two_readings_gets_two_meanings(self) -> None:
        """이 시험이 이 파일의 본론이다.

        ``音(おと)``·``音(ね)``, ``下(した)``·``下(しも)``·``下(もと)`` 처럼 한 한자 안에서
        표기가 겹치는 용례군이 55 개 있다.  옛 파이프라인에서는 그 **전부**가 같은
        뜻이었다 — 하나도 갈리지 않았다.
        """
        why_of = _reasons()
        groups: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)
        for kanji, reading, example in self._examples():
            surface = ordering.plain_surface(example.get("w") or "")
            groups[(kanji, surface)].append((
                reading, example.get("ko") or "",
                why_of.get(f"{kanji}|{reading}|{surface}", "")))

        collapsed = []
        for (kanji, surface), rows in groups.items():
            for index, (reading, meaning, why) in enumerate(rows):
                for other_reading, other, other_why in rows[index + 1:]:
                    verdict = audit_meanings.compare(meaning, other, why, other_why)
                    if verdict and verdict[0] == "FAIL":
                        collapsed.append(
                            f"{kanji} {surface} ({reading} ↔ {other_reading}): "
                            f"{verdict[1]}")
        self.assertEqual(collapsed[:5], [], f"{len(collapsed)}건")


def _reasons() -> dict:
    """모델이 남긴 '왜 같은가' 근거.  캐시가 없으면 빈 표."""
    try:
        cache = load("kanji", "cache.json")
    except Exception:                       # noqa: BLE001 — 없으면 없는 대로 본다
        return {}
    slot = cache.get("gemini-3.7-flash", {}).get("word_ko_v3", {})
    return {key: (value or {}).get("why", "") for key, value in slot.items()}


def _record(*, ko: str) -> dict:
    """계약 검사에 넣을 최소 레코드."""
    return {
        "tag": "j",
        "variant": {},
        "except": {},
        "readings": {"オン": [{"w": "発音(はつおん)", "ko": ko}]},
        "korean": {"본": ["소리 음"]},
    }


if __name__ == "__main__":
    unittest.main()
