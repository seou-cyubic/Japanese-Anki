# -*- coding: utf-8 -*-
"""Stage 4: toeic_japanese.json — 뜻마다 영·일 예문 한 쌍을 붙인다.

짧은 뜻풀이(``gloss``·``en``)는 '이 뜻이 무엇인가' 를 가르는 표찰이고, 예문은 '그
뜻이 어떻게 쓰이는가' 를 보여 주는 다른 물건이다.  둘 다 남긴다.

**후리가나를 모델에게 시키지 않는다.**  시켜 보면 오쿠리가나가 있는 낱말에서 괄호를
낱말 뒤에 붙이고 남는 칸을 공백으로 메운다 — ``新しい(あたら　)``(올바른 자리는
``新(あたら)しい``).  그래서 문장과 **문장 전체의 읽기**만 받고 정렬은
``shared.furigana.annotate`` 에 맡긴다.  문장에는 조사와 오쿠리가나가 촘촘해 앵커가
많으므로 낱말보다 오히려 잘 맞물리고, 맞물리지 않으면 ``None`` 이라 **잘못된
후리가나가 데이터에 들어갈 길이 없다.**

실측(뜻 253 개)에서 정렬 실패는 전부 모델이 읽기를 틀린 경우였다 — 한자가 그대로
남거나, 로마자가 섞이거나(``ほんかんに hairu まえに``), 데바나가리가 들어오기도 했다.
그 전부를 정렬기가 걸러 냈다.

**호출은 전부 캐시에 남는다.**  키에 회차를 붙이므로(``낱말#순번@1``) 검사에 걸려
다시 물은 것도 버려지지 않는다.
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from decks.toeic.pipeline import paths  # noqa: E402
from decks.toeic.pipeline.stage3_verify import jmdict_readings  # noqa: E402
from shared.furigana import (  # noqa: E402
    annotate_candidates, is_cjk_run, parse_annotated, plain_surface, to_hiragana,
)
from shared.gemini import Cache, Gemini, chunk, dump_json_atomic  # noqa: E402
from shared.paths import GEMINI_KEY  # noqa: E402

BATCH = 20                     # 한 번에 묻는 낱말 수.  뜻으로는 30 개 안팎이다
WORKERS = 8                    # 예문은 뜻 추출보다 호출이 무겁다.  더 나눠 띄운다
ROUNDS = 8                     # 검사에 걸린 것을 다시 묻는 횟수
# 연탁(れんだく).  뒤 낱말의 첫 모라가 흐려지는 일은 흔하므로 어긋남으로 세지 않는다.
VOICED = str.maketrans("かきくけこさしすせそたちつてとはひふへほ",
                       "がぎぐげござじずぜぞだぢづでどばびぶべぼ")
HALF_VOICED = str.maketrans("はひふへほ", "ぱぴぷぺぽ")
LEGACY_MODELS = ("gemini-3.7-flash",)   # 읽기만 하는 옛 모델 캐시 칸
TEMPERATURE = 0.1              # 0.4 에서 "All department heads" 가
                               # "すべての場合の部門長" 이 되는 사고가 났다

PROMPT = """You are writing example sentences for a vocabulary deck. The learner is
Korean, studies English *through* Japanese, and is preparing for the TOEIC test.

For every sense listed below write ONE pair of sentences:

  "en"   : an English sentence using the headword (any inflected form).
  "ja"   : the Japanese sentence that says **exactly the same thing** — same meaning,
           same register, same nuance. It must contain the Japanese word given for
           that sense (an inflected form is fine). Write plain Japanese: **no
           furigana, no parentheses, no romaji.**
  "kana" : the reading of the whole "ja" sentence. Copy "ja" character by character
           and replace only the kanji with their readings in hiragana. Keep every
           kana, every katakana word, every punctuation mark and every digit exactly
           as they appear in "ja". Do not add or remove anything else.

Both sentences must read as natural, idiomatic writing in their own language.
Neither may read like a translation of the other; write the thought once and say it
in both languages.

Keep sentences short (8-16 English words) and TOEIC-flavoured: offices, travel,
shopping, schedules, contracts, daily life. No proper names of real people or
companies.

Senses: %(senses)s

Answer as JSON only, keyed by the sense id:
{"<id>": {"en": "...", "ja": "...", "kana": "..."}}
"""


def sense_id(word: str, index: int) -> str:
    return f"{word}#{index}"


def ask_rows(entries: dict, ids: list[str]) -> list[dict]:
    """모델에게 보여 줄 뜻 한 줄씩.  뜻을 가르는 데 필요한 것만 담는다."""
    rows = []
    for key in ids:
        word, index = key.rsplit("#", 1)
        sense = entries[word]["senses"][int(index)]
        rows.append({
            "id": key,
            "word": word,
            "ja": plain_surface(sense["ja"]),
            "pos": sense["pos"],
            "gloss": sense["gloss"],
            "means": sense["en"],
        })
    return rows


def japanese_stem(word: str) -> str:
    """일본어 낱말에서 활용하지 않는 앞부분.

    ``書く`` 는 문장에서 ``書いて`` 로 나타난다.  꼬리는 변하지만 한자런은 남으므로,
    첫 한자런까지만 끊어 그것을 찾는다.  가나뿐인 낱말은 앞의 두 글자를 본다.

    뜻풀이가 ``〜の間``·``〜に違いない`` 처럼 **틀 기호 〜 로 시작하면** 그 기호는 문장에
    나타날 수 없다.  예전에는 ``〜の`` 를 찾다가 while·must 의 예문 다섯 개를 모두
    버렸다.  기호를 걷고, 안에 한자런이 있으면 그것을 찾는다.
    """
    word = word.lstrip("〜～~")
    if not word:
        return word
    start = next((index for index, character in enumerate(word)
                  if is_cjk_run(character)), None)
    if start is not None:
        end = start
        while end < len(word) and is_cjk_run(word[end]):
            end += 1
        return word[start:end]
    return word[:2]


_STEMS: dict[int, dict[str, set[str]]] = {}


def stem_readings(readings: dict[str, set[str]]) -> dict[str, set[str]]:
    """한자런 -> 오쿠리가나를 뗀 어간 읽기.  ``見込む/みこむ`` 에서 ``見込 -> みこ``.

    문장 속 동사는 활용해서 나타난다(``見込(みこ)んで``, ``支払(しはら)われる``).
    그 꼬리(``んで``·``われる``)는 사전 표제어의 꼬리와 다르므로, 꼬리를 붙여 찾는
    방식으로는 표제어에 닿지 못하고 ``支払``(しはらい) 같은 **다른 낱말**에만 닿는다.
    그래서 표제어에서 어간 읽기를 미리 뽑아 둔다.
    """
    key = id(readings)
    if key not in _STEMS:
        stems: dict[str, set[str]] = {}
        for surface, known in readings.items():
            end = len(surface)
            while end and not is_cjk_run(surface[end - 1]):
                end -= 1
            okurigana = to_hiragana(surface[end:])
            if not end or not okurigana:
                continue
            for entry in known:
                plain = to_hiragana(entry)
                if plain.endswith(okurigana) and len(plain) > len(okurigana):
                    stems.setdefault(surface[:end], set()).add(plain[: -len(okurigana)])
        _STEMS[key] = stems
    return _STEMS[key]


def voiced_forms(plain: str) -> set[str]:
    """사전 읽기와, 첫 소리가 연탁으로 흐려진 꼴.  ``かいしゃ`` -> ``がいしゃ``."""
    forms = {plain}
    if plain and plain[0] in "かきくけこさしすせそたちつてとはひふへほ":
        forms.add(plain[0].translate(VOICED) + plain[1:])
    if plain and plain[0] in "はひふへほ":
        forms.add(plain[0].translate(HALF_VOICED) + plain[1:])
    return forms


def reading_fits(surface: str, reading: str, tail: str,
                 readings: dict[str, set[str]]) -> bool:
    """이 한자런의 읽기가 사전과 맞는가.

    표제어는 오쿠리가나까지 포함할 수 있으므로(``新しい``) 꼬리를 한 글자씩 붙여 보고,
    그중 하나라도 사전에 있으면 그 읽기와 맞춰 본다.  사전에 아예 없으면 물을 수
    없는 것이므로 통과시킨다 — 모르는 것을 틀렸다고 하지 않는다.

    **꼬리를 붙인 모든 꼴을 본 뒤에 판정한다.**  짧은 꼴에서 바로 거절하면 안 된다 —
    ``格上げ`` 는 ``格上``(かくうえ) 라는 **다른 표제어**가 먼저 걸려, ``格上(かくあ)げ``
    가 사전과 다르다고 떨어졌다.  그 한 가지로 upgrade 의 예문 다섯 개가 전부 버려졌다.

    **연탁은 사전 쪽을 흐려서 맞춘다.**  예전에는 모델의 읽기를 흐렸는데, 이미 흐려진
    ``会社(がいしゃ)``·``菓子(がし)`` 는 그대로라 사전의 ``かいしゃ``·``かし`` 와 끝내
    맞지 않았다.  활용한 동사는 ``stem_readings`` 의 어간 읽기로 맞춘다.
    """
    given_run = to_hiragana(reading)
    looked_up = False
    for cut in range(len(tail) + 1):
        known = readings.get(surface + tail[:cut])
        if not known:
            continue
        looked_up = True
        given = given_run + to_hiragana(tail[:cut])
        if any(given in voiced_forms(to_hiragana(entry)) for entry in known):
            return True
    stems = stem_readings(readings).get(surface)
    if stems:
        looked_up = True
        if any(given_run in voiced_forms(stem) for stem in stems):
            return True
    # 표제어가 있었는데 어느 꼴과도 맞지 않으면 틀린 읽기다.  아예 없으면 물을 수 없다.
    return not looked_up


def readings_fit(annotated: str, readings: dict[str, set[str]],
                 single: bool = False) -> bool:
    """문장의 모든 한자런을 사전에 물어본다.

    기본으로는 두 자 이상인 런만 본다.  한 자짜리는 훈독이 갈래가 많아 사전 표제어와
    어긋나는 것이 정상인 경우가 흔하고, 틀린 읽기가 몰리는 곳도 아니다.
    ``single`` 은 **정렬 후보를 가려낼 때만** 켠다(``choose_annotation``).
    """
    parsed = parse_annotated(annotated)
    if not parsed:
        return False
    segments = parsed["segments"]
    for position, segment in enumerate(segments):
        if segment["reading"] is None or (len(segment["surface"]) < 2 and not single):
            continue
        following = segments[position + 1] if position + 1 < len(segments) else None
        tail = following["surface"] if following and following["reading"] is None else ""
        if not reading_fits(segment["surface"], segment["reading"], tail, readings):
            return False
    return True


def choose_annotation(japanese: str, kana: str,
                      readings: dict[str, set[str]]) -> str | None:
    """문장과 읽기를 맞물린다.  해가 여럿이면 **사전과 어긋나지 않는 해** 하나를 고른다.

    ``音楽が流れています`` + ``おんがくがながれています`` 는 조사 が 가 おんがく 안에도
    있어서 ``音楽(おん)が流(くがなが)れ`` 라는 해가 하나 더 생긴다.  정렬기는 해가
    둘이면 물러나므로, 生活·音楽·親 같은 흔한 낱말의 예문이 다섯 번 모두 버려졌다.

    가려내는 순서: 두 자 이상 런을 사전에 대 보고, 그래도 여럿이면 한 자 런까지 대
    본다.  **끝까지 하나로 좁혀지지 않으면 고르지 않는다** — 잘못된 후리가나를
    싣느니 예문을 버린다.
    """
    candidates = annotate_candidates(japanese, kana)
    if len(candidates) == 1:
        return candidates[0]
    fitting = [one for one in candidates if readings_fit(one, readings)]
    if len(fitting) > 1:
        fitting = [one for one in fitting if readings_fit(one, readings, single=True)]
    return fitting[0] if len(fitting) == 1 else None


def check(row: dict, got: dict, family: list[str],
          readings: dict[str, set[str]]) -> tuple[str | None, str | None]:
    """(영문, 주석을 실은 일문) 또는 (None, 사유).

    넷을 본다 — 후리가나가 표기를 복원하는가, 영문에 그 낱말이 있는가, 일문에 그 뜻이
    있는가, **읽기가 사전과 맞는가.**  뉘앙스가 같은지는 기계가 볼 수 없으므로
    보지 않는다.
    """
    english = (got.get("en") or "").strip()
    japanese = (got.get("ja") or "").strip()
    kana = (got.get("kana") or "").strip()
    if not english or not japanese or not kana:
        return None, "빈 응답"
    lowered = english.lower()
    if not any(re.search(rf"\b{re.escape(form.lower())}", lowered) for form in family):
        return None, "영문에 낱말이 없다"
    # 기능어(that·must·while…)의 뜻풀이는 낱말이 아니라 문법 설명이다(``関係代名詞``).
    # 문장에 그 글자가 나타나지 않는 것이 정상이므로 이 검사를 걸지 않는다.
    if row.get("pos") != "function" and japanese_stem(row["ja"]) not in japanese:
        return None, "일문에 그 뜻이 없다"
    written = choose_annotation(japanese, kana, readings)
    if written is None:
        return None, "읽기가 표기와 맞물리지 않는다"
    if not readings_fit(written, readings):
        return None, "읽기가 사전과 다르다"
    return english, written


def main() -> None:
    entries = json.loads(paths.CHECKED.read_text(encoding="utf-8"))
    # 모델을 바꿔도 **이미 받은 답은 버리지 않는다.**  캐시는 모델별로 칸이 갈리므로
    # 새 칸만 보면 6,000 개가 넘는 뜻을 전부 다시 묻게 된다.  옛 칸은 읽기만 한다.
    cache = Cache(paths.CACHE, "toeic_examples", fallback_models=LEGACY_MODELS)
    answer_of = cache.get
    gemini = Gemini(GEMINI_KEY)
    readings = jmdict_readings()
    print(f"JMdict 표기 {len(readings)}종")

    wanted = [sense_id(word, index)
              for word, entry in entries.items()
              for index in range(len(entry["senses"]))]
    print(f"뜻 {len(wanted)}개")

    # 회차마다 캐시 칸이 따로다.  검사에 걸려 다시 물은 답도 버리지 않는다.
    accepted: dict[str, dict] = {}
    reasons: dict[str, str] = {}

    # **이미 카드에 실린 예문은 바꾸지 않는다.**  검사를 고치면 예전에 떨어졌던 앞
    # 회차의 답이 통과하게 되고, 회차 순서대로 고르면 멀쩡한 예문 수백 개가 다른
    # 문장으로 갈린다.  학습 중인 카드의 예문이 까닭 없이 바뀌면 안 된다.  그래서
    # 직전 산출물의 예문이 **지금의 검사도 통과하면** 그것을 먼저 채택한다.
    previous: dict[str, dict] = {}
    if paths.FINAL.exists():
        for word, entry in json.loads(paths.FINAL.read_text(encoding="utf-8")).items():
            for index, sense in enumerate(entry.get("senses", [])):
                if sense.get("example"):
                    previous[sense_id(word, index)] = sense["example"]
    kept = 0
    for key in wanted:
        if key not in previous:
            continue
        word, _index = key.rsplit("#", 1)
        row = ask_rows(entries, [key])[0]
        for attempt in range(1, ROUNDS + 1):
            got = answer_of(f"{key}@{attempt}")
            if got is None:
                continue
            english, written = check(row, got, entries[word]["family"], readings)
            if english is not None and {"en": english, "ja": written} == previous[key]:
                accepted[key] = previous[key]
                kept += 1
                break
    print(f"직전 예문 유지 {kept}/{len(previous)}")
    for attempt in range(1, ROUNDS + 1):
        todo = [key for key in wanted if key not in accepted]
        if not todo:
            break
        missing = [key for key in todo if answer_of(f"{key}@{attempt}") is None]
        print(f"\n[{attempt}회차] 남은 뜻 {len(todo)} · 물어볼 것 {len(missing)}")

        if missing:
            # 한 낱말의 뜻들은 한 묶음에 함께 넣는다 — 서로 다른 뜻이 서로를 갈라
            # 준다.  묶음은 낱말 수로 센다.
            by_word: dict[str, list[str]] = {}
            for key in missing:
                by_word.setdefault(key.rsplit("#", 1)[0], []).append(key)
            groups = [[key for word in words for key in by_word[word]]
                      for words in chunk(list(by_word), BATCH)]

            def ask(group: list[str]) -> tuple[list[str], dict]:
                rows = ask_rows(entries, group)
                answer = gemini.json(
                    PROMPT % {"senses": json.dumps(rows, ensure_ascii=False)},
                    temperature=TEMPERATURE)
                return group, (answer if isinstance(answer, dict) else {})

            done = 0
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                for group, answer in pool.map(ask, groups):
                    for key in group:
                        cache[f"{key}@{attempt}"] = answer.get(key) or {}
                    cache.flush()          # 받는 족족 남긴다
                    done += len(group)
                    print(f"  [{done}/{len(missing)}]", flush=True)

        for key in todo:
            got = answer_of(f"{key}@{attempt}") or {}
            word, index = key.rsplit("#", 1)
            row = ask_rows(entries, [key])[0]
            english, written = check(row, got, entries[word]["family"], readings)
            if english is None:
                reasons[key] = written or "알 수 없음"
            else:
                accepted[key] = {"en": english, "ja": written}
                reasons.pop(key, None)

    for word, entry in entries.items():
        for index, sense in enumerate(entry["senses"]):
            example = accepted.get(sense_id(word, index))
            if example:
                sense["example"] = example
            else:
                sense.pop("example", None)
    dump_json_atomic(paths.FINAL, entries)

    left = [key for key in wanted if key not in accepted]
    print(f"\n예문을 붙인 뜻 {len(accepted)}/{len(wanted)} "
          f"({len(accepted)/len(wanted):.1%}) · 못 붙인 것 {len(left)}")
    tally: dict[str, int] = {}
    for key in left:
        tally[reasons.get(key, "?")] = tally.get(reasons.get(key, "?"), 0) + 1
    for reason, count in sorted(tally.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")
    print(f"-> {paths.FINAL.name}")


if __name__ == "__main__":
    main()
