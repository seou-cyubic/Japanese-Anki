# -*- coding: utf-8 -*-
"""덱마다 Anki 카드 면과 노트 하나의 ``Data`` 를 내놓는다.

``tests/test_card.mjs`` 가 이것을 받아 **가짜 DOM 위에서 실제로 돌려 본다.**
템플릿이 파이썬에서 만들어지고 렌더러는 자바스크립트라, 그 이음매가 성립하는지는
두 쪽을 다 세워 봐야 알 수 있다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.ankicard import DATA_FIELD  # noqa: E402
from shared.deckspec import discover  # noqa: E402
from shared.paths import DECKS  # noqa: E402

# 카드 본문이 비지 않았는지 볼 때 세는 것.  덱마다 '한 덩이' 가 다르다.
BLOCK = {"kanji": "kc-reading", "bunpo": "bn-ex", "toeic": "tc-sense"}


def faces() -> dict:
    found = {}
    for name, spec in sorted(discover(DECKS).items()):
        # 파이프라인을 아직 안 돌린 덱은 건너뛴다 — 카드 면을 시험할 데이터가 없다.
        if not spec.data_path.exists():
            continue
        payload = (spec.load_payload() if spec.load_payload is not None
                   else json.loads(spec.data_path.read_text(encoding="utf-8")))
        for group in spec.anki_notes:
            notes = group.build(payload)
            templates = {}
            for template in group.note_type.templates:
                templates[f"{template.name} 앞면"] = template.front
                templates[f"{template.name} 뒷면"] = template.back
            found[group.note_type.name] = {
                "templates": templates,
                "data": notes[0][DATA_FIELD],
                # 카드를 넘겼을 때를 시험하려면 다음 레코드도 있어야 한다.
                "next": notes[1][DATA_FIELD],
                "block": BLOCK[name]}
    return found


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    json.dump(faces(), sys.stdout, ensure_ascii=False)
