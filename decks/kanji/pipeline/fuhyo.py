# -*- coding: utf-8 -*-
"""付表(부표) 해석 — 어느 한자가 '예외 읽기'를 지는가를 판정한다.

배경
----
常用漢字表 본표는 ``한자 | 음훈 | 例 | 備考`` 4열이다.  付表 에 실린 숙자훈·
당て字 는 본표 備考 칸에 ``단어（よみ）`` 꼴로 상호참조만 걸려 있다.  이것은
용례가 아니라 포인터이므로 ``readings`` 에 들어가서는 안 된다.  예외 읽기의
authoritative 출처는 오직 付表(p.161-162) 와 본표 備考 의 都道府県名 뿐이다.

판정 규칙
--------
付表 항목 (S=표기, R=단어 전체 읽기) 에 대해

1. 가나 앵커링 — S 를 [한자런 | 가나리터럴] 로 쪼갠다.  가나리터럴은 R 위의
   고정점이므로 각 한자런이 담당하는 읽기 구간이 확정된다.
   예) お巡りさん / おまわりさん  ->  巡 = まわ
2. 런 분절 — 한자 n 개짜리 런의 읽기를 n 개 조각으로 전탐색한다.  분할점은
   모라 경계로 제한한다(ゃゅょ·っ·ー 는 조각의 첫 글자가 될 수 없다).
3. 채점 — 조각이 그 한자의 정규 읽기(연탁·반탁·촉음편 포함)이면 match.
   match 수가 최대인 분절을 채택한다.
4. 배정 — match 되지 않은 한자가 '예외'다.  예외 한자가 하나도 없으면 단어
   전체가 예외이므로 구성 한자 전부가 진다(순수 숙자훈 score=0 도 동일).
5. 키 — 조각이 아니라 **단어 전체 읽기 R** 을 키로 쓴다.  덕분에 조각 경계의
   모호성은 결과에 영향을 주지 않는다(さおとめ 를 어떻게 잘라도 예외 집합은
   {早, 乙} 로 같다).

최대 분절이 서로 다른 match 벡터를 낼 때만 진짜 모호이며, 그때는 ADJUDICATED
에 근거와 함께 못박는다.  표에 없는 새 모호가 나오면 빌드를 실패시킨다.
"""
import re
import itertools

CJK_RE = re.compile(r"[㐀-鿿\U00020000-\U0002A6DF豈-﫿]")
KANA_RE = re.compile(r"[ぁ-ゟ]+")

# 備考 칸의 付表 / 都道府県 상호참조.  용례가 아니므로 readings 에서 제거한다.
#
# 토큰 하나는 「표기（요미가나）」 이고, 표기에는 오쿠리가나와 「・」 가 섞일 수 있으며
# 괄호 뒤에 오쿠리가나나 県·府·都 가 더 붙을 수 있다(手伝（てつだ）う, 兄（にい）さん,
# 愛媛（えひめ）県).  경계 문자를 반드시 제외해야 한다 — 특히 「⇔」 를 넘어가면
# 뒤따르는 동음이의 주석이 용례로 새어 들어온다.
#   固唾（かたず）⇔堅い，硬い  ->  「固唾（かたず）」 만 지우고 「⇔堅い，硬い」 는 남긴다.
_EDGE = r"[^，,、。「」⇔（）()\s]"
FUHYO_REF_RE = re.compile(
    rf"{_EDGE}*[㐀-鿿]{_EDGE}*（[ぁ-ゟ]+）[ぁ-ゟァ-ヿ県府都]*")
PREF_READ_RE = re.compile(r"([㐀-鿿]+)（([ぁ-ゟ]+)）[県府都]")

# 소문자·촉음·장음은 조각의 첫 글자가 될 수 없다(모라 경계).
_SMALL = set("ゃゅょぁぃぅぇぉっー")

_RENDAKU = dict(zip("かきくけこさしすせそたちつてとはひふへほ",
                    "がぎぐげござじずぜぞだぢづでどばびぶべぼ"))
_HANDAKU = dict(zip("はひふへほ", "ぱぴぷぺぽ"))

# 최대 분절이 복수의 match 벡터를 내는 유일한 두 사례.  근거를 남긴다.
ADJUDICATED = {
    # う|わき(浮 정규) 와 うわ|き(気 정규) 가 동점이다.  気 = き 는 정식 음독이고
    # 浮 의 常用 훈은 う(く)·う(かぶ) 뿐이므로 うわ 를 지는 浮 가 예외다.
    ("うわき", "浮気"): ["浮"],
    # や|よい(弥 정규) 와 やよ|い(生 정규) 가 동점이다.  や 는 弥 의 유일한 읽기라
    # 弥 를 예외로 볼 수 없다.  よい 를 지는 生 가 예외다.
    ("やよい", "弥生"): ["生"],
}


def to_hiragana(value):
    return "".join(chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c
                   for c in value)


def phonetic_variants(reading):
    """연탁·반탁·촉음편의 실현형 닫힘.

    연탁은 첫 모라를, 촉음편은 끝 모라를 건드리므로 둘은 독립이고 함께 일어날
    수 있다(かつ -> がっ).  따라서 합성까지 모두 만든다.
    """
    if not reading:
        return {reading}
    heads = {reading[0]}
    if reading[0] in _RENDAKU:
        heads.add(_RENDAKU[reading[0]])
    if reading[0] in _HANDAKU:
        heads.add(_HANDAKU[reading[0]])
    tails = {reading[1:]}
    if len(reading) > 1 and reading[-1] in "つくきち":
        tails.add(reading[1:-1] + "っ")
    return {head + tail for head in heads for tail in tails}


def build_regular_readings(merged):
    """{한자: {정규 읽기}} — merged 는 stage3 가 확정한 {한자: {읽기키: [용례]}}."""
    regular = {}
    for kanji, readings in merged.items():
        found = set()
        for key in readings:
            stem = to_hiragana(key[:-1] if key.endswith("ー") else key)
            if stem:
                found |= phonetic_variants(stem)
        regular[kanji] = found
    return regular


def parse_fuhyo(doc):
    """付表 페이지에서 (읽기, [표기...]) 를 뽑는다.  116 읽기 / 123 표기."""
    tokens = []
    for page_number in (161, 162):
        for line in doc[page_number].get_text().splitlines():
            text = line.strip().replace("　", "")
            if text:
                tokens.append(text)
    entries, current = [], None
    for token in tokens:
        if token.startswith(("付表", "※", "例", "「")):
            continue
        token = re.sub(r"（[^）]*）", "", token)      # （「しはす」とも言う。）師走
        if not token:
            continue
        if KANA_RE.fullmatch(token):
            current = (token, [])
            entries.append(current)
        elif CJK_RE.search(token) and current is not None:
            current[1].append(token)
    return [(reading, surfaces) for reading, surfaces in entries if surfaces]


def parse_prefectures(joyo_rows):
    """본표 備考 의 都道府県名 특수 읽기.  付表 지면에는 없다."""
    found = {}
    for rows in joyo_rows.values():
        for row in rows:
            for match in PREF_READ_RE.finditer(row["note"]):
                found[match.group(1)] = match.group(2)
    return found


def strip_reference_tokens(note):
    """備考 에서 付表 상호참조를 걷어낸다.  나머지는 그대로 둔다.

    괄호 읽기가 붙은 토큰만 지운다.  괄호 없는 都道府県 표기(岡山県, 埼玉県,
    栃木県, 茨城県 …)는 **지우지 않는다** — 그 단어의 구성 한자가 모두 정규 읽기라
    예외가 아니고, 따라서 그 한자의 정당한 용례이기 때문이다.  岡 의 備考
    「岡山県，静岡県，福岡県」 이 바로 그것이다.
    """
    return FUHYO_REF_RE.sub("", note)


def _segment_runs(surface, reading):
    """표기를 [한자런] 으로 쪼개고 가나리터럴을 읽기 위에 고정한다."""
    parts, index = [], 0
    while index < len(surface):
        end = index
        if CJK_RE.match(surface[index]):
            while end < len(surface) and CJK_RE.match(surface[end]):
                end += 1
            parts.append(("kanji", surface[index:end]))
        else:
            while end < len(surface) and not CJK_RE.match(surface[end]):
                end += 1
            parts.append(("kana", surface[index:end]))
        index = end

    runs, cursor = [], 0
    for position, (kind, text) in enumerate(parts):
        if kind == "kana":
            if position == 0:
                if not reading.startswith(text):
                    return None
                cursor = len(text)
            else:
                found = reading.find(text, cursor)
                if found < 0:
                    return None
                runs.append((parts[position - 1][1], reading[cursor:found]))
                cursor = found + len(text)
        elif position == len(parts) - 1:
            runs.append((text, reading[cursor:]))
    if parts[-1][0] == "kana" and not reading.endswith(parts[-1][1]):
        return None
    return [(run, part) for run, part in runs if run and part]


def _splits(reading, count):
    points = [i for i in range(1, len(reading)) if reading[i] not in _SMALL]
    for cuts in itertools.combinations(points, count - 1):
        pieces, previous = [], 0
        for cut in cuts:
            pieces.append(reading[previous:cut])
            previous = cut
        pieces.append(reading[previous:])
        yield pieces


def irregular_kanji(surface, reading, regular):
    """(예외 한자 목록, 모호 여부).  판정 불가면 (None, 사유)."""
    runs = _segment_runs(surface, reading)
    if not runs:
        return None, "가나 앵커링 실패"

    exceptional, ambiguous = [], False
    for run, part in runs:
        kanji = list(run)
        if len(kanji) == 1:
            if part not in regular.get(kanji[0], ()):
                exceptional.append(kanji[0])
            continue
        candidates = list(_splits(part, len(kanji)))
        if not candidates:
            return None, "분절 불가"
        best, vectors = -1, set()
        for pieces in candidates:
            vector = tuple(piece in regular.get(char, ())
                           for piece, char in zip(pieces, kanji))
            score = sum(vector)
            if score > best:
                best, vectors = score, {vector}
            elif score == best:
                vectors.add(vector)
        if len(vectors) > 1:
            ambiguous = True
        vector = sorted(vectors)[0]
        if best == 0:
            exceptional.extend(kanji)
        else:
            exceptional.extend(char for char, ok in zip(kanji, vector) if not ok)

    # 예외 한자가 없다면 단어 전체가 예외다 — 구성 한자 전부가 진다.
    if not exceptional:
        exceptional = [c for c in surface if CJK_RE.match(c)]
    return list(dict.fromkeys(exceptional)), ambiguous


def compute_except(entries, regular):
    """付表 항목 -> {한자: {전체읽기: [표기...]}}.  모호는 예외를 던진다."""
    except_map, failures, unresolved = {}, [], []
    for reading, surfaces in entries:
        for surface in surfaces:
            fixed = ADJUDICATED.get((reading, surface))
            if fixed is not None:
                exceptional = fixed
            else:
                exceptional, note = irregular_kanji(surface, reading, regular)
                if exceptional is None:
                    failures.append((reading, surface, note))
                    continue
                if note is True:
                    unresolved.append((reading, surface, exceptional))
            for kanji in exceptional:
                bucket = except_map.setdefault(kanji, {}).setdefault(reading, [])
                if surface not in bucket:
                    bucket.append(surface)
    if failures:
        raise AssertionError(f"付表 판정 실패: {failures}")
    if unresolved:
        raise AssertionError(
            "새로운 모호 분절이 나왔다. 근거를 확인해 ADJUDICATED 에 등재하라: "
            f"{unresolved}")
    return except_map


def fuhyo_surfaces(entries):
    """付表 에 오른 표기 전체.  readings 오염 제거의 판단 근거."""
    return {surface for _, surfaces in entries for surface in surfaces}
