# -*- coding: utf-8 -*-
"""프론트엔드 카드를 그대로 Anki 카드로 만든다.

**두 곳에서 같은 것을 그리는 방법은 두 가지가 있었다.**  하나는 파이썬이 카드
HTML 을 미리 만들어 필드에 넣는 것이고(그래서 CSS 를 손으로 옮겨 적었다), 다른
하나는 **데이터를 그대로 실어 보내고 화면과 똑같은 렌더러가 Anki 안에서 그리는
것**이다.  이 모듈은 후자다.

```
decks/<덱>/data/*.json  ──┬─→  편집기: /api/<덱>/record/<키>  →  card.js:render()
                          └─→  Anki:   Data 필드(그 레코드)   →  card.js:render()
```

같은 ``card.js`` 와 같은 ``card.css`` 가 양쪽을 그리므로 **디자인이 어긋날 자리가
없다.**  Anki 쪽에만 있는 것은 노트 타입 껍데기(``.card`` 바탕색)와, 카드 면을
고르는 모드 클래스 하나뿐이다.

``Data`` 는 **base64** 로 싣는다.  세 가지를 한 번에 해결한다.
  1. JSON 이 HTML 필드 안에서 깨지지 않는다 (Anki 편집기가 ``<br>`` 을 넣어도
     ``{{text:Data}}`` 와 공백 제거로 원문이 돌아온다).
  2. 저장되는 글자가 ASCII 뿐이라 **NFC 정규화가 손대지 않는다** — 이체자
     62 자(CJK 호환 한자)가 통합 한자로 접히는 사고가 여기서는 일어나지 않는다.
  3. 같은 레코드는 같은 문자열이 되므로 동기화가 멱등하다.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from .anki import CardTemplate, NoteTypeSpec
from .paths import APP_STATIC, ROOT

TOKENS = APP_STATIC / "tokens.css"
DATA_FIELD = "Data"
MOUNT_ID = "sp-mount"
DATA_ID = "sp-data"

# Anki 노트 타입 껍데기.  카드 자체의 디자인은 덱의 card.css 가 전부 낸다.
SHELL_CSS = """
/* --- Anki 껍데기 --------------------------------------------------------
 * 카드의 생김새는 아래 덱 card.css 가 낸다.  여기는 그 카드를 얹을 종이뿐이다. */
.card {
  background: var(--paper);
  color: var(--ink);
  font-family: var(--jp), var(--kr);
  text-align: left;
}
.sp-mount { display: flex; justify-content: center; padding: 4px; }
/* 편집기에서만 뜻이 있는 것들 — Anki 에서는 눌러도 뒤집히지 않는다. */
.sp-mount .preview-card { cursor: default; }
"""

# 카드 면을 그리는 스크립트.  ``Data`` 를 풀어 화면과 **같은 렌더러**에 넘긴다.
MOUNT_JS = r"""
(function () {
  var host = document.getElementById(%(mount)s);
  var carrier = document.getElementById(%(data)s);
  if (!host || !carrier) return;
  var packed = (carrier.textContent || '').replace(/\s+/g, '');
  if (!packed) return;              /* Data 가 없는 옛 노트.  빈 카드로 드러난다 */
  var bytes = Uint8Array.from(atob(packed), function (c) { return c.charCodeAt(0); });
  var envelope = JSON.parse(new TextDecoder('utf-8').decode(bytes));
  var renderer = window[%(renderer)s];
  if (!renderer) return;
  host.textContent = '';
  host.appendChild(renderer.render(renderer.noteFrom(envelope), %(options)s));
})();
"""


def pack(envelope: dict) -> str:
    """봉투 하나를 ``Data`` 필드 문자열로.  같은 레코드는 언제나 같은 문자열이다."""
    raw = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def unpack(field: str) -> dict:
    """``Data`` 를 되돌린다.  시험이 왕복을 확인할 때 쓴다."""
    return json.loads(base64.b64decode("".join(field.split())).decode("utf-8"))


def envelope(key: str, record: dict, derived: dict | None = None) -> dict:
    """렌더러가 받는 봉투.  **편집기가 넘기는 것과 같은 모양이다.**

    편집기는 ``{key, record, derived}`` 를 만들어 ``noteFrom`` 에 넘긴다
    (``app/static/app.js:noteFromModel``).  Anki 도 같은 모양을 받아야 같은 카드가
    나오므로, 서버가 계산해 주던 ``derived`` 중 **렌더러가 실제로 읽는 것만**
    덱이 여기에 담는다.
    """
    return {"key": key, "record": record, "derived": derived or {}}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def styling(static_dir: Path) -> str:
    """노트 타입 CSS = 공용 토큰 + 그 덱의 card.css + Anki 껍데기.

    **손으로 옮겨 적지 않는다.**  화면이 읽는 바로 그 파일을 그대로 싣는다.
    """
    # 경로는 저장소 기준으로 적는다.  절대 경로를 적으면 기계마다 CSS 가 달라져
    # 동기화가 멱등하지 않게 된다.
    source = static_dir.relative_to(ROOT).as_posix()
    return (f"/* 자동 생성 — 원본은 app/static/tokens.css 와 {source}/card.css 다.\n"
            " * 이 CSS 를 손으로 고치면 다음 동기화 때 덮인다. */\n"
            + _read(TOKENS) + SHELL_CSS + _read(static_dir / "card.css"))


def face(renderer: str, mode: str, script: str, options: dict) -> str:
    """카드 한 면.  데이터를 싣고, 렌더러를 싣고, 모드 하나로 그린다."""
    mount = (f'<div class="sp-mount" id="{MOUNT_ID}"></div>'
             f'<div id="{DATA_ID}" hidden>{{{{text:{DATA_FIELD}}}}}</div>')
    setup = MOUNT_JS % {
        "mount": json.dumps(MOUNT_ID),
        "data": json.dumps(DATA_ID),
        "renderer": json.dumps(renderer),
        "options": json.dumps({**options, "mode": mode}, ensure_ascii=False),
    }
    return (mount
            + "\n<script>\n" + script + "\n</script>\n"
            + "<script>" + setup + "</script>")


def build_note_type(*, name: str, fields: list[str], static_dir: Path,
                    renderer: str, cards: list[tuple[str, str, str]],
                    options: dict | None = None) -> NoteTypeSpec:
    """덱의 렌더러를 그대로 실은 노트 타입.

    ``cards`` 는 ``(카드 이름, 앞면 모드, 뒷면 모드)`` 다.  모드 이름은 편집기의
    모드 탭과 **같은 문자열**이어야 한다 — 그 문자열이 곧 카드 요소의 클래스이고,
    무엇을 가릴지는 card.css 가 그 클래스로 정하기 때문이다.
    """
    if DATA_FIELD not in fields:
        raise ValueError(f"{name}: {DATA_FIELD} 필드가 있어야 렌더러가 그릴 수 있다")
    script = _read(static_dir / "card.js")
    if "</script" in script.lower():
        raise ValueError(f"{name}: 렌더러에 </script> 가 있으면 템플릿이 끊긴다")
    options = options or {}
    templates = [
        CardTemplate(title,
                     front=face(renderer, front, script, options),
                     back=face(renderer, back, script, options))
        for title, front, back in cards
    ]
    return NoteTypeSpec(name=name, fields=fields, templates=templates,
                        css=styling(static_dir))
