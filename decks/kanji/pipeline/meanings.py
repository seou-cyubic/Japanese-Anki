# -*- coding: utf-8 -*-
"""용례 뜻의 계약 — 파이프라인과 시험이 함께 쓰는 단일 정의.

Stage 4 는 뜻을 **두 번** 묻는다.  1 패스가 초안을 짓고, 2 패스가 그것을 감수한다.
카드에 실리는 것은 감수본이고, 감수를 못 받은 자리에서만 초안이다.  그 규칙이 여기
한 곳에만 있어야 스테이지와 시험이 갈리지 않는다 — ``ordering.py`` 와 같은 이유다.

**괄호는 여기서 막는다.**  '두 뜻이 같은 말인가' 는 기계가 못 재지만 '괄호를 썼는가'
는 잰다.  프롬프트에만 적어 두면 지켜졌는지 알 수 없고, 캐시가 어긴 답을 그대로
굳혀 고침이 데이터에 영영 닿지 못한다.  ``clean()`` 이 거부하면 그 항목은 캐시에
들어가지 않으므로 다음 실행이 다시 묻는다.
"""
from __future__ import annotations

import hashlib
import re

from decks.kanji.model import MAX_SENSES

__all__ = ["AGREE_SLOT", "CLAUDE_REVIEWER", "DRAFT_SLOT", "MAX_SENSES", "PAREN",
           "REVIEW_MODEL", "REVIEW_SLOT", "agree_key", "claude_key", "clean",
           "claude_reasons", "final_ko", "load_claude_review", "pro_ko",
           "review_key", "top_level_semicolon"]

# 캐시 칸 이름.  스테이지·감사·시험이 모두 여기서 읽는다.
#
# ``v4`` 는 프롬프트의 최우선 규칙(A: 뜻 하나에 한 마디, B: 한국인이 실제로 쓰는 말)을
# 새로 세우며 판 칸이다.  ``v3`` 의 답에는 ``四日 -> 나흘 / 4일``, ``雨量 -> 우량``,
# ``再三 -> 재삼`` 이 그대로 있었다 — 프롬프트만 고치면 캐시가 옛 답을 내주므로 칸을 판다.
DRAFT_SLOT = "word_ko_v4"
REVIEW_SLOT = "word_ko_review_v2"
AGREE_SLOT = "word_ko_agree_v2"
REVIEW_MODEL = "gemini-3.1-pro-preview"
# 마지막 감수는 모델 호출이 아니라 Claude Code 세션이 전건을 읽고 남긴 파일이다.
CLAUDE_REVIEWER = "claude-opus-5"

# 괄호는 뜻을 적다 만 자리다 — 읽는 쪽은 괄호 밖만 뜻으로 받아들이므로 안에 담은
# 것은 전달되지 않는다.  풀어 쓰거나 버려야 한다(stage4 프롬프트의 규칙 8).
PAREN = re.compile(r"[(（][^)）]*[)）]")


def top_level_semicolon(value):
    """괄호 밖의 세미콜론.  ``일위(계급의 하나; 대위)`` 의 것은 경계가 아니다."""
    depth = 0
    for character in value:
        if character in "(（[［":
            depth += 1
        elif character in ")）]］":
            depth = max(0, depth - 1)
        elif character == ";" and depth == 0:
            return True
    return False


def clean(answer):
    """모델이 낸 것을 계약대로 다듬는다.  규약을 어기면 None — 캐시에 넣지 않는다."""
    if isinstance(answer, str):
        answer = [answer]
    if not isinstance(answer, list):
        return None
    lines = []
    for piece in answer:
        text = str(piece).strip().rstrip(".").strip()
        if not text or "\n" in text or top_level_semicolon(text):
            return None
        if PAREN.search(text):
            return None
        lines.append(text)
    if not lines or len(lines) > MAX_SENSES:
        return None
    return lines


def review_key(key, draft):
    """감수 열쇠.

    감수는 **그 초안에 대한** 답이다.  초안이 바뀌면 감수도 다시 받아야 하므로
    열쇠에 초안을 함께 싣는다 — 그러지 않으면 새 초안에 옛 감수가 붙는다.
    """
    digest = hashlib.sha1("\n".join(draft).encode("utf-8")).hexdigest()[:10]
    return f"{key}|{digest}"


def agree_key(key, settled):
    """맞춤 열쇠.  감수본이 바뀌면 맞춤도 다시 받는다 — ``review_key`` 와 같은 이유다."""
    digest = hashlib.sha1("\n".join(settled).encode("utf-8")).hexdigest()[:10]
    return f"{key}|{digest}"


def claude_key(key, pro):
    """Claude 감수 열쇠.  pro 단계의 답이 바뀌면 그 감수는 더 이상 붙지 않는다."""
    digest = hashlib.sha1("\n".join(pro).encode("utf-8")).hexdigest()[:10]
    return f"{key}|{digest}"


def load_claude_review(path):
    """``{"reviewer": ..., "items": {claude_key: {"ko": [...], "fix": ...}}}``.  없으면 빈 표."""
    import json
    try:
        with open(path, encoding="utf-8") as stream:
            return json.load(stream).get("items", {})
    except (OSError, ValueError):
        return {}


def claude_reasons(claude):
    """Claude 감수가 남긴 '요미카타가 달라도 뜻이 같은 까닭'.  ``{한자|읽기|표기: why}``."""
    return {item_key.rsplit("|", 1)[0]: value["why"]
            for item_key, value in claude.items()
            if isinstance(value, dict) and value.get("why")}


def final_ko(key, draft, reviews, agreements=None, claude=None):
    """카드에 실리는 뜻.  **Claude 감수본 > 맞춤본 > 감수본 > 초안** 순으로 고른다."""
    pro = pro_ko(key, draft, reviews, agreements)
    if claude:
        checked = clean((claude.get(claude_key(key, pro)) or {}).get("ko"))
        if checked is not None:
            return checked
    return pro


def pro_ko(key, draft, reviews, agreements=None):
    """모델 단계가 내놓은 뜻.  **맞춤본 > 감수본 > 초안** 순으로 고른다.

    한 낱말이 여러 한자 카드에 실린다.  값이 겹치는 것은 손해가 아니지만 **어긋나는
    것은 손해다** — 한쪽이 틀렸다는 뜻이다(``傾倒`` 가 한 카드에서는 '몰두함',
    다른 카드에서는 '경도' 였다).  3 패스가 그 줄들을 한자리에 놓고 다시 답한다.

    감수나 맞춤을 못 받았다고 그 용례를 버리지 않는다 — 뜻이 아예 없는 것과 달리
    앞 단계의 답도 쓸 수 있는 답이다.  Stage 4 가 그 수를 알리고, 다시 돌리면
    그것만 다시 묻는다.
    """
    reviewed = clean((reviews.get(review_key(key, draft)) or {}).get("ko"))
    settled = reviewed if reviewed is not None else draft
    if agreements:
        agreed = clean((agreements.get(agree_key(key, settled)) or {}).get("ko"))
        if agreed is not None:
            return agreed
    return settled
