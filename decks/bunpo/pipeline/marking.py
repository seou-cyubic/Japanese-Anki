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

**구간은 하나가 아니다.**  ``たり～たりする`` 처럼 표제형 가운데가 ``～`` 로 비어 있는
문형은 문장 안에서 **떨어져** 실현된다 — ``本を読んだり、テレビを見たりします``.  여기서
문법인 것은 ``たり`` 와 ``たりします`` 두 조각뿐이고 그 사이의 ``、テレビを見`` 은 문법이
아니라 그 문형이 잡아먹은 내용이다.  그래서 별표는 **짝수 개**이고 조각마다 한 쌍이
붙는다.  ``split('*')`` 한 뒤 홀수 번째가 문법이다(``marked_spans``).

    日(にち)曜(よう)日(び)には、本(ほん)を読(よ)んだり、テレビを見(み)*たり*します。
    → 조각 하나
    ...本(ほん)を読(よ)ん*だり*、テレビを見(み)*たりします*。
    → 조각 둘.  사이의 「、テレビを見」 은 강조되지 않는다.

**어떻게 찾는가.**  표제형은 가나로 적히는데 예문은 한자로 쓴다 —
``あいだ`` 항목의 예문은 ``夏の間``.  그래서 원문 그대로 찾으면 절반도 못 맞춘다.
뽑아 둔 후리가나가 다리가 된다: 한자를 읽기로 바꾼 '읽기 형태' 위에서 찾으면
``夏(なつ)の間(あいだ)`` 가 ``なつのあいだ`` 가 되어 표제형과 맞는다.

**어느 자리를 고르는가.**  표제형은 한 문장에 여러 번 나타난다.  가장 왼쪽을 그냥
집으면 틀린다 — ``たい`` 는 ``ああ、暑い。冷たいビールが飲みたいなあ。`` 에서 첫 자리가
``冷たい`` 안이다.  ``冷たい`` 는 이형용사 한 낱말이지 ``飲み＋たい`` 가 아니다.  그래서
후보를 **전부 모은 뒤 골라야** 한다(``find_spans``).  고르는 기준은

  1. 사전 낱말 한가운데를 자르지 않는다  (``Lexicon``.  ``冷たい`` 를 탈락시키는 것이
     이 규칙이다 — 형태만으로는 ``見たい`` 와 구별할 수 없고, 그것을 아는 것은 사전뿐이다)
  2. 조각 사이의 빈틈이 좁다        (문형이 실제로 실현된 자리는 흩어지지 않는다)
  3. 접속형이 요구하는 왼쪽 문맥이 있다 (``connect``.  문두나 구두점 바로 뒤는 아니다)
  4. 같으면 왼쪽                     (기존 데이터와의 흔들림을 줄인다)

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
_OPTIONAL_ONLY = re.compile(r"[（(][^）)]*[）)]")

# ``～`` 가 삼킬 수 있는 최대 길이.  ``たり～たりする`` 의 사이에 절 하나가 들어가므로
# 넉넉해야 하지만, 무한히 늘어나면 문장 전체를 한 문형으로 보게 된다.
MAX_GAP = 14

# 연탁·음편으로 조각의 **첫 글자**가 탁음이 되는 일이 있다 — ``読んだり`` 의 ``だり``.
# 이것을 허용하지 않아 ``たり～たりする`` 는 기계적 매칭이 통째로 실패했고, 그 자리를
# 모델이 메우면서 연속 구간이 데이터에 들어왔다.  교체는 조각의 첫 글자에만 건다.
_VOICED = dict(zip("かきくけこさしすせそたちつてとはひふへほ",
                   "がぎぐげござじずぜぞだぢづでどばびぶべぼ"))
_SEMI_VOICED = dict(zip("はひふへほ", "ぱぴぷぺぽ"))
# 한 글자짜리 조각(``て``·``し``·``が``)까지 탁음을 허용하면 아무 데나 걸린다.
_VOICE_MIN_LENGTH = 2

# 문두나 구두점 바로 뒤는 '앞에 무엇이 붙는' 문형이 실현될 자리가 아니다.
#
# **닫는 따옴표·괄호는 여기 넣지 않는다.**  ``「ミラノ」って`` 의 ``って`` 앞에는 인용
# 부호가 있지만 그 부호가 닫고 있는 것은 명사 ``ミラノ`` 다 — 앞에 아무것도 없는 자리가
# 아니라, 앞의 것이 마침 부호로 끝났을 뿐이다.  닫는 쪽을 감점하면 인용을 받는 문형
# (``って``·``と``)이 엉뚱한 자리로 밀린다.
_LEFT_BREAK = set("。、．，！？「『（(　 ")


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


# ---------------------------------------------------------------------------
# 표제형 -> 조각
# ---------------------------------------------------------------------------

def head_forms(head):
    """표제형 하나에서 시도할 **형태**들.  형태 하나는 리터럴 조각의 목록이다.

    ``たり～たりする``  -> ``[['たり', 'たりする']]``
    ``お～・ご～``      -> ``[['お'], ['ご']]``
    ``あまりの～に``    -> ``[['あまりの', 'に']]``

    앞뒤에 붙은 ``～`` 는 조각을 만들지 않는다 — 그쪽은 그냥 '무엇이든 온다' 는
    뜻이고, 그 무엇은 문법이 아니므로 표시할 것도 없다.
    """
    head = (head or "").strip()
    if not head:
        return []
    forms = []
    for form in dict.fromkeys(part for part in re.split(r"[・/｜|]", head) if part):
        segments = [piece for piece in re.split(r"[～〜]", form) if piece]
        # **통째로 괄호인 조각은 조각이 아니다.**  ``たら～（のに）`` 의 ``（のに）`` 는
        # 있어도 되고 없어도 되는 것이라, 조각으로 세우면 빈 문자열에만 맞아 형태
        # 전체가 성립하지 못한다.  그런 조각은 없는 셈 친다.
        segments = [piece for piece in segments
                    if _OPTIONAL_ONLY.sub("", piece).strip()]
        if segments:
            forms.append(segments)
    # **되풀이는 한 번으로 줄어들 수 있다.**  ``たり～たりする`` 의 예문에는
    # ``犬を飼ったりしたい`` 처럼 ``たり`` 가 한 번만 나오는 것이 있다.  넓은 형태(두 번)
    # 를 먼저 시도하고 닿지 않을 때만 줄인 형태를 본다 — 순서가 곧 우선순위다.
    for segments in list(forms):
        if len(segments) >= 2 and _repeated_core(segments) is not None:
            reduced = [segments[-1]]
            if reduced not in forms:
                forms.append(reduced)
    return forms


# ---------------------------------------------------------------------------
# 접속형에 실린 대체 표제형
# ---------------------------------------------------------------------------
#
# **원전이 이미 적어 두었다.**  표제형은 대표 꼴 하나뿐이지만 접속형 칸에는 그 문형이
# 실제로 실현되는 꼴이 전부 실려 있다.
#
#     てくる        Ｖて ＋ くる  Ｖて ＋ いく          -> ていく
#     と～た        Ｖると ＋ ～た  Ｖたら ＋ ～た       -> たら～た
#     というものは   Ｎ ＋ というものは  普通形 ＋ ということは  -> ということは
#     ことができる   Ｖる＋こと／Ｎ ＋ ができる            -> ができる
#
# 이것을 읽지 않아 ``…していきます``·``飲んだら…ました``·``…ということは`` 가 표시되지
# 못하고 모델에게 넘어갔다.  접속형은 고유값이 570 종인 자유 서술이라 통째로 해석하지
# 않는다 — **리터럴만 주워 온다.**  그리고 이렇게 얻은 꼴은 표제형이 닿지 못했을 때에만
# 마지막으로 시도한다(``find_spans``).  그래야 이미 붙은 표시가 흔들리지 않는다.

# 품사 자리 표시.  이 뒤에 남는 것이 리터럴이다.
_SLOT = re.compile(
    r"^(?:する動詞の[ＮN][のをに]?|普通形|丁寧形|数量|値段|[ＶV]|[ＮN]|イ[ＡA]|ナ[ＡA])")
# 자리 표시 뒤에 붙는 **활용 이름**.  ``Ｖます`` 의 ``ます`` 는 표면에 그대로 나오지
# 않는다(``生きがい`` 의 ``生き``).  이런 것은 리터럴이 아니다.
_CONJUGATION_NAME = {"", "る", "ます", "た", "ない", "よう", "ば"}
# 사전형의 ``る`` 는 동사마다 달라진다(``飲むと``·``行くと``).  뒤에 무엇이 붙어 있으면
# 그 ``る`` 만 떼어 낸다 — ``ると`` 는 ``と`` 다.
_DICTIONARY_TAIL = re.compile(r"^る(?=.)")
_ANNOTATION = re.compile(r"[（(][^）)]*[）)]")
_ALTERNATIVE = re.compile(r"[／/・]")
_CHAIN_BREAK = re.compile(
    r"(?<=\S)\s+(?=(?:する動詞の[ＮN]|普通形|丁寧形|数量|値段|[ＶVＮN]|イ[ＡA]|ナ[ＡA]))")


def _tail(piece):
    """접속형 조각에서 리터럴만.  자리 표시뿐이면 빈 문자열."""
    piece = _SLOT.sub("", piece.strip()).strip()
    if piece in _CONJUGATION_NAME:
        return ""
    return _DICTIONARY_TAIL.sub("", piece)


def connect_forms(connect, known=()):
    """접속형에서 대체 표제형들을 뽑는다.  이미 아는 꼴은 빼고 돌려준다.

    한 접속형 문자열에 사슬이 여럿 실릴 수 있고(``Ｖて ＋ くる Ｖて ＋ いく``), 사슬
    한 자리에 대안이 여럿 실릴 수 있다(``こと／Ｎ``).  둘 다 펼쳐 본다.
    """
    found = []
    for shape in connect or ():
        # 괄호 주석은 **가장 먼저** 걷는다.  안에 대안 구분자가 들어 있어(``（ナＡな／Ｎな）``)
        # 나중에 걷으면 괄호가 갈라져 쪼가리가 리터럴로 새어 나온다.
        shape = _ANNOTATION.sub("", str(shape))
        chains = [[]]
        for piece in shape.split("＋"):
            for index, part in enumerate(_CHAIN_BREAK.split(piece.strip())):
                if index:
                    chains.append([])
                chains[-1].append(part)
        for chain in chains:
            forms = [[]]
            for slot in chain:
                options = {_tail(option) for option in _ALTERNATIVE.split(slot)}
                forms = [current + [option]
                         for current in forms for option in sorted(options)]
                if len(forms) > 8:          # 대안이 폭발하면 보지 않는다
                    forms = forms[:8]
            for pieces in forms:
                form = "".join(pieces)
                if len(form.replace("～", "").replace("〜", "")) < 2:
                    continue
                segments = [piece for piece in re.split(r"[～〜]", form) if piece]
                if segments and segments not in known and segments not in found:
                    found.append(segments)
    return found


def _literal(segment, *, voiced):
    """리터럴 조각 하나를 정규식으로.  ``（は）`` 같은 괄호는 선택 사항이다."""
    pieces = []
    index = 0
    first = True
    while index < len(segment):
        char = segment[index]
        if char in "（(":
            close = segment.find("）" if char == "（" else ")", index)
            if close != -1:
                pieces.append("(?:" + re.escape(segment[index + 1:close]) + ")?")
                index = close + 1
                continue
        if first and voiced:
            alternatives = {char}
            if char in _VOICED:
                alternatives.add(_VOICED[char])
            if char in _SEMI_VOICED:
                alternatives.add(_SEMI_VOICED[char])
            pieces.append("[" + "".join(sorted(alternatives)) + "]"
                          if len(alternatives) > 1 else re.escape(char))
        else:
            pieces.append(re.escape(char))
        first = False
        index += 1
    return "".join(pieces)


# **어간이 바뀌는 동사는 가나를 이어 붙이는 것만으로 닿지 않는다.**  표제형
# ``たり～たりする`` 의 예문은 ``…たりします`` 라고 끝난다.  ``する`` 에서 ``る`` 를 떼면
# ``す`` 인데 실제로 온 것은 ``し`` 라, 아래의 일반 규칙으로는 영원히 맞지 않는다.
# 그래서 ``たり～たりする`` 는 기계적 매칭이 통째로 실패했고 모델이 그 자리를 메웠다.
# 어간이 바뀌는 동사는 둘뿐이므로 활용형을 그대로 적어 둔다.
_STEM_CHANGING = {
    "する": ("しなかった", "しました", "しません", "しないで", "しよう", "しない",
             "します", "して", "した", "すれ", "する", "し"),
    "くる": ("こなかった", "きました", "きません", "こない", "きます",
             "きて", "きた", "くる", "き"),
}

# ``ない``·``だ`` 는 사정이 다르다.  ``ではない``·``ものだ`` 처럼 **앞에 무엇이 붙어 있으면**
# 아래의 일반 규칙(끝 한 글자를 떼고 가나를 잇는다)이 이미 넉넉히 닿는다 —
# ``ものだ`` 는 그 규칙으로 ``ものな``·``ものに``·``ものです`` 를 전부 잡는다.  일반 규칙이
# 무너지는 것은 조각이 ``ない``·``だ`` **그 자체**일 때뿐이다.  ``ほど～ない`` 의 ``ない`` 는
# 끝 글자를 떼면 ``な`` 한 글자만 남아 아무 데나 걸리므로 규칙이 포기해 버리고,
# 그래서 ``…ほどおもしろくなかった`` 에 닿지 못했다.  그때만 활용형을 적어 둔다.
_BARE_ONLY = {
    "ない": ("ありません", "なかった", "なければ", "なくて", "ません",
             "ない", "なく", "なき"),
    # 계사에서 ``で``·``な`` 는 뺀다.  너무 짧고 흔해서 아무 자리에나 걸린다.
    "だ": ("でした", "だった", "である", "です", "だ"),
}
_IRREGULAR_ORDER = sorted(_STEM_CHANGING, key=len, reverse=True)


def _inflected_tail(segment):
    """마지막 조각의 활용형 정규식.  못 만들면 None."""
    if segment in _BARE_ONLY:
        return "(?:" + "|".join(
            sorted(_BARE_ONLY[segment], key=len, reverse=True)) + ")"
    for verb in _IRREGULAR_ORDER:
        if segment.endswith(verb):
            prefix = segment[: -len(verb)]
            body = "(?:" + "|".join(
                sorted(_STEM_CHANGING[verb], key=len, reverse=True)) + ")"
            return _literal(prefix, voiced=len(prefix) >= _VOICE_MIN_LENGTH) + body
    # 그 밖의 동사·형용사·조동사는 끝 한 글자를 떼고 뒤에 가나를 허용하면 닿는다.
    stem = re.sub(r"[るうだいなくきしてた]$", "", segment)
    if not stem or stem == segment or len(stem) < 2:
        return None
    return _literal(stem, voiced=len(stem) >= _VOICE_MIN_LENGTH) + r"[ぁ-ゟー]{0,4}"


def _repeated_core(segments):
    """``たり～たりする`` 처럼 **같은 조각이 되풀이되는** 문형의 마지막 조각에서
    뒤에 붙은 동사를 뗀 몸통.  없으면 None.

    ``…たり…たりです``·``…たり…たりでは`` 처럼 원전이 ``する`` 를 적어 두었는데 예문에서는
    그것이 생략되는 일이 있다.  그때도 되풀이되는 몸통(``たり``)은 반드시 두 번 다
    나타나므로, 그것만으로 문형을 짚을 수 있다.  **되풀이가 아닌 문형에는 쓰지
    않는다** — ``お～する`` 에서 ``する`` 를 떼면 남는 것이 ``お`` 뿐이라 아무 데나 걸린다.
    """
    if len(segments) < 2:
        return None
    last = segments[-1]
    for verb in _IRREGULAR_ORDER:
        if last.endswith(verb):
            core = last[: -len(verb)]
            if core and core in segments[:-1]:
                return core
    return None


def segment_patterns(segments):
    """``(방법, [조각 정규식])`` 들을 정확한 것부터 순서대로 낸다."""
    voiced = [len(piece) >= _VOICE_MIN_LENGTH for piece in segments]
    exact = [re.compile(_literal(piece, voiced=flag))
             for piece, flag in zip(segments, voiced)]
    out = [("exact", exact)]
    tail = _inflected_tail(segments[-1])
    if tail is not None:
        out.append(("inflected", exact[:-1] + [re.compile(tail)]))
    core = _repeated_core(segments)
    if core is not None:
        out.append(("repeat", exact[:-1] + [
            re.compile(_literal(core, voiced=len(core) >= _VOICE_MIN_LENGTH))]))
    return out


# 옛 이름.  ``(방법, 정규식)`` 하나짜리 계약을 쓰던 곳이 남아 있을 수 있다.
def head_patterns(head):
    """표제형 하나에서 시도할 (방법, 조각 정규식들) 을 넓은 것부터."""
    found = []
    for segments in head_forms(head):
        found.extend(segment_patterns(segments))
    return found


# ---------------------------------------------------------------------------
# 사전 낱말 — 조각이 낱말 한가운데를 자르는지 본다
# ---------------------------------------------------------------------------

class Lexicon:
    """표시 구간이 **사전에 있는 한 낱말의 한가운데**인지 판정한다.

    ``たい`` 가 ``冷たい`` 안에 있는지 ``飲みたい`` 안에 있는지는 형태만으로 갈리지
    않는다 — 둘 다 '한자 + たい' 다.  ``冷たい`` 는 사전에 실린 이형용사 한 낱말이고
    ``飲みたい`` 는 아니라는 사실만이 그 둘을 가른다.  그래서 여기서만 사전을 본다.

    **파이프라인 밖에서는 비어 있어도 된다.**  이 모듈은 코퍼스를 직접 읽지 않는다 —
    ``corpora/JMdict`` 는 저장소에 없고, 시험은 갓 받은 저장소에서도 돌아야 한다.
    낱말은 스테이지(``lexicon.from_jmdict``)가 만들어 넣어 준다.
    """

    __slots__ = ("written", "spoken", "both", "longest")

    def __init__(self, written=(), spoken=()):
        self.written = frozenset(written)
        self.spoken = frozenset(spoken)
        self.both = self.written | self.spoken
        self.longest = max((len(word) for word in self.both), default=0)

    def __bool__(self):
        return bool(self.written or self.spoken)

    def occurrences(self, surface, view):
        """``surface`` 안에 있는 사전 낱말의 자리들.

        표기 평면에서는 **읽기 목록까지 함께** 본다.  ``ひとつ``·``ください`` 처럼 한자로
        적을 수 있는 낱말이 예문에서는 가나로 적혀 있는 일이 흔하고, 그것도 낱말이라는
        사실은 달라지지 않는다.  읽기 평면에는 한자가 없으므로 표기 목록을 볼 것이 없다.
        """
        words = self.both if view == "plain" else self.spoken
        if not words:
            return ()
        found = []
        length = len(surface)
        for start in range(length):
            for size in range(2, min(self.longest, length - start) + 1):
                if surface[start:start + size] in words:
                    found.append((start, start + size))
        return tuple(found)

    @staticmethod
    def cuts(spots, start, end):
        """``[start, end)`` 를 **제 안에 품는 더 큰 낱말**이 있으면 참."""
        for word_start, word_end in spots:
            if word_start <= start and end <= word_end and (
                    word_start < start or end < word_end):
                return True
        return False


EMPTY_LEXICON = Lexicon()


# ---------------------------------------------------------------------------
# 접속형 — 왼쪽에 무엇이 와야 하는가
# ---------------------------------------------------------------------------

_ATTACHES_LEFT = re.compile(r"[ＶVＮNイナ]|普通形|丁寧形|数量|値段")


def attaches_to_something(connect):
    """이 문형이 **앞에 무엇이 붙어야** 성립하는가.

    원전의 접속형은 ``V ます ＋ たい`` 처럼 자유 서술이고 고유값이 570 종이라
    통째로 해석하지 않는다.  여기서 얻으려는 것은 하나뿐이다 — '앞에 붙는 것이
    있는가'.  있다면 문두나 구두점 바로 뒤는 그 문형이 실현될 자리가 아니다.
    """
    for shape in connect or ():
        head, _, _rest = str(shape).partition("＋")
        if _ATTACHES_LEFT.search(head):
            return True
    return False


def _left_penalty(surface, start, needs_left):
    if not needs_left:
        return 0
    if start == 0:
        return 1
    return 1 if surface[start - 1] in _LEFT_BREAK else 0


# ---------------------------------------------------------------------------
# 후보를 모아 고른다
# ---------------------------------------------------------------------------

def _placements(surface, patterns):
    """조각 패턴들을 순서대로 놓는 **모든** 배치.  각각 ``[(시작, 끝)]``."""
    found = []

    def walk(index, lower, chosen):
        pattern = patterns[index]
        upper = len(surface) if index == 0 else min(len(surface), lower + MAX_GAP)
        for position in range(lower, upper + 1):
            match = pattern.match(surface, position)
            if match is None or match.end() == match.start():
                continue
            spans = chosen + [(match.start(), match.end())]
            if index + 1 == len(patterns):
                found.append(spans)
            else:
                walk(index + 1, match.end(), spans)

    walk(0, 0, [])
    return found


def _score(spans, spots, surface, needs_left):
    """작을수록 좋다.  기준의 순서가 곧 우선순위다."""
    cut = sum(1 for start, end in spans if Lexicon.cuts(spots, start, end))
    gap = sum(nxt[0] - cur[1] for cur, nxt in zip(spans, spans[1:]))
    return (cut, _left_penalty(surface, spans[0][0], needs_left), gap, spans[0][0])


def _to_annotated(spans, offsets):
    """평면 문자열 기준의 구간을 주석 표기 기준으로 옮기고 붙은 것은 합친다.

    대응표가 덩이를 가리키므로 경계는 저절로 ``後(あと)`` 바깥으로 물러난다 —
    ``*後*(あと)`` 는 나올 수 없다(``groups`` 참조).
    """
    moved = []
    for start, end in spans:
        begin = offsets[start][0]
        finish = offsets[end - 1][1]
        if moved and begin <= moved[-1][1]:
            moved[-1] = (moved[-1][0], max(moved[-1][1], finish))
            continue
        moved.append((begin, finish))
    return moved


def find_spans(annotated, head, *, connect=(), lexicon=EMPTY_LEXICON,
               from_connect=False):
    """``([(시작, 끝)], 방법)`` 을 annotated 기준으로.  못 찾으면 None.

    구간은 여럿일 수 있다 — ``たり～たりする`` 는 둘이다.
    """
    view = views(annotated)
    needs_left = attaches_to_something(connect)
    declared = head_forms(head)
    if from_connect:
        # **접속형에서 뽑은 꼴은 맨 마지막 수단이다.**  리터럴만 주워 온 것이라
        # 표제형만큼 정확하지 않다 — ``ようとする`` 의 접속형에서 얻는 것은 ``とする`` 뿐이라
        # 정작 문형의 알맹이인 ``よう`` 가 빠진다.  그래서 표제형도, 모델도 답하지 못한
        # 예문에만 쓴다(``stage2_korean.py``).  그때는 반쪽 표시라도 없는 것보다 낫다.
        attempts = [(segments, "connect-")
                    for segments in connect_forms(connect, declared)]
    else:
        attempts = [(segments, "") for segments in declared]
    for segments, source in attempts:
        for method, patterns in segment_patterns(segments):
            for surface, offsets, tag in (
                (view["plain"], view["plain_map"], "plain"),
                (view["reading"], view["reading_map"], "reading"),
            ):
                placements = _placements(surface, patterns)
                if not placements:
                    continue
                spots = lexicon.occurrences(surface, tag)
                best = min(placements,
                           key=lambda spans: _score(spans, spots, surface, needs_left))
                return _to_annotated(best, offsets), f"{source}{method}/{tag}"
    return None


def find_span(annotated, head, *, connect=(), lexicon=EMPTY_LEXICON):
    """구간 하나만 쓰던 자리를 위한 좁은 창구.  첫 조각의 시작과 끝 조각의 끝."""
    found = find_spans(annotated, head, connect=connect, lexicon=lexicon)
    if found is None:
        return None
    spans, method = found
    return spans[0][0], spans[-1][1], method


# ---------------------------------------------------------------------------
# 표시하기 / 읽기
# ---------------------------------------------------------------------------

def apply_marks(annotated, spans):
    """구간들을 ``*`` 로 감싼 표기를 만든다.  구간은 앞에서부터 겹치지 않는다."""
    out = []
    position = 0
    for start, end in spans:
        out.append(annotated[position:start])
        out.append(MARK)
        out.append(annotated[start:end])
        out.append(MARK)
        position = end
    out.append(annotated[position:])
    return "".join(out)


def mark(annotated, head, *, connect=(), lexicon=EMPTY_LEXICON):
    """문법 구간을 ``*`` 로 감싼 표기와 쓰인 방법을 돌려준다."""
    found = find_spans(annotated, head, connect=connect, lexicon=lexicon)
    if found is None:
        return annotated, None
    spans, method = found
    return apply_marks(annotated, spans), method


def mark_from_connect(annotated, head, *, connect=(), lexicon=EMPTY_LEXICON):
    """**표제형도 모델도 답하지 못했을 때** 접속형에 실린 대체 꼴로 표시한다.

    원전은 표제형을 대표 꼴 하나로 싣지만 접속형 칸에는 실제로 실현되는 꼴을 전부
    적어 둔다 — ``てくる`` 의 접속형에 ``Ｖて ＋ いく`` 가 있고, ``と～た`` 에
    ``Ｖたら ＋ ～た`` 가 있다.  이것을 읽지 않아 ``…していきます``·``飲んだら…ました`` 가
    끝내 표시되지 못했다.

    **모델보다 뒤에 둔다.**  리터럴만 주워 온 꼴이라 문형의 알맹이가 빠질 수 있어
    (``ようとする`` -> ``とする``), 앞에 세우면 멀쩡한 모델 답을 더 나쁜 것으로 바꾼다.
    """
    found = find_spans(annotated, head, connect=connect, lexicon=lexicon,
                       from_connect=True)
    if found is None:
        return annotated, None
    spans, method = found
    return apply_marks(annotated, spans), method


def mark_with_spans(annotated, spans):
    """모델이 집어 준 **평문** 조각들을 주석 표기 위의 자리로 옮겨 표시한다.

    모델은 후리가나를 뗀 평문을 보고 답하므로(``祭りの後``) 그 끝이 한자에 떨어질
    수 있다.  대응표가 덩이를 가리키므로 경계는 저절로 ``後(あと)`` 바깥으로
    물러난다.  조각은 **예문에 나온 순서대로** 하나씩 앞에서부터 집는다 — 같은
    조각이 두 번 나오는 ``たり～たりする`` 가 제자리를 찾으려면 그래야 한다.
    """
    if isinstance(spans, str):
        spans = [spans]
    pieces = [str(piece).strip() for piece in spans or () if str(piece).strip()]
    if not pieces:
        return annotated, None
    view = views(annotated)
    flat = []
    cursor = 0
    for piece in pieces:
        start = view["plain"].find(piece, cursor)
        if start < 0:
            return annotated, None
        flat.append((start, start + len(piece)))
        cursor = start + len(piece)
    return apply_marks(annotated, _to_annotated(flat, view["plain_map"])), "model"


def mark_with_span(annotated, span):
    """조각 하나만 주던 옛 창구."""
    return mark_with_spans(annotated, [span])


# 표시가 표제형보다 얼마나 길어도 되는가.  활용 꼬리와 조사 정도는 붙는 것이 자연스럽다
# (``あげる`` -> ``あげましょう``).  그보다 길면 문형이 아닌 말을 데리고 온 것이다.
SPAN_SLACK = 4


def span_budget(head, pieces=1):
    """조각 ``pieces`` 개로 실현된 이 표제형의 표시가 넘어서는 안 되는 길이.

    표제형 하나가 여러 형태를 가질 수 있으므로(``お～・ご～``, 그리고 되풀이가 줄어든
    형태) **조각 수가 가장 가까운 형태**를 기준으로 삼는다.  그래야 ``たり～たりする``
    를 한 덩이로 표시한 옛 답이 ``[たりする]`` 형태(한 조각)에 견주어져 걸린다 —
    두 조각 형태에 견주면 예산이 두 배라 그냥 통과해 버린다.
    """
    forms = head_forms(head)
    if not forms:
        return None
    form = min(forms, key=lambda segments: abs(len(segments) - pieces))
    return sum(len(piece) for piece in form) + SPAN_SLACK * len(form)


def overruns(head, spans):
    """표시 조각들이 표제형이 허락하는 길이를 넘었는가.  넘은 글자 수.

    ``stage2`` 의 옛 답 이식과 ``audit_marks`` 가 **같은 자를 써야 한다** — 감사에서
    걸릴 것을 파이프라인이 도로 심으면 고쳐지지 않는다.
    """
    spans = list(spans)
    forms = head_forms(head)
    if not forms:
        return 0
    count = len(spans) or 1
    budget = span_budget(head, count)
    # **한 예문에 문형이 두 번 실현되기도 한다** — ``…することもあります。でも、…ことは
    # ありません。`` 처럼 두 문장이 한 예문에 들어 있을 때가 그렇다.  조각이 형태의
    # 조각 수보다 많으면 그만큼 되풀이된 것이므로 예산도 그만큼 늘어난다.
    form = min(forms, key=lambda segments: abs(len(segments) - count))
    budget *= max(1, -(-count // len(form)))
    return max(0, sum(len(piece) for piece in spans) - budget)


def marked_spans(marked):
    """표시된 문자열에서 문법 조각들을.  프론트엔드가 쓰는 것과 같은 방법."""
    parts = str(marked or "").split(MARK)
    if len(parts) < 3:
        return []
    return [piece for piece in parts[1::2] if piece]


def marked_span(marked):
    """조각들을 이어 붙인 것.  '문법 구간' 을 문자열 하나로 보던 자리를 위한 것."""
    return "".join(marked_spans(marked))


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
