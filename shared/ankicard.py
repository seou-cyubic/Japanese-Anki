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
없다.**  Anki 쪽에만 있는 것은 노트 타입 껍데기(``.card`` 바탕색과 다크 모드 스위치)와, 카드 면을
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
THEME_ID = "sp-theme"
THEME_KEY = "sp-theme"

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

/* 다크 모드 스위치가 고른 종이.  Anki 자체의 야간 모드 규칙(.nightMode.card …)보다
 * 무거우므로 이긴다 — 야간 모드에서 '다크 OFF' 를 골라도 밝아진다. */
.card:has(.sp-dark),
.card:has(.sp-light) {
  background: var(--paper);
  color: var(--ink);
}

/* 다크 모드 스위치 — 카드 위, 오른쪽 끝에 제 줄을 차지하고 앉는다.  화면에 띄워 두면
 * (position: fixed) 넓은 한자 카드의 머리(「앞면」 표지)를 덮는다. */
.sp-theme {
  display: flex;
  width: fit-content;
  margin: 0 4px 6px auto;
  align-items: center;
  gap: 7px;
  padding: 5px 11px 5px 9px;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  background: var(--surface);
  color: var(--ink-3);
  font-family: var(--kr);
  font-size: 11.5px;
  font-weight: 500;
  line-height: 1.3;
  cursor: pointer;
}
/* 반쯤 칠한 동그라미 — 밝음과 어두움 사이의 스위치. */
.sp-theme::before {
  content: "";
  width: 9px;
  height: 9px;
  border: 1.5px solid currentColor;
  border-radius: 50%;
  background: linear-gradient(90deg, currentColor 0 50%, transparent 50%);
  box-sizing: border-box;
}
.sp-theme:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.sp-theme[aria-pressed="true"] {
  border-color: var(--ink);
  background: var(--ink);
  color: var(--surface);
}
/* 손을 올리면 켜짐·꺼짐 **어느 쪽이든** 한 단계 짙어진다 — 누를 수 있다는 표시가
 * 상태에 따라 있다 없다 하지 않게. */
.sp-theme[aria-pressed="false"]:hover { border-color: var(--ink-4); color: var(--ink); }
.sp-theme[aria-pressed="true"]:hover { border-color: var(--ink-2); background: var(--ink-2); }
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

# 다크 모드 켜고 끄기 — 토익 덱의 예문 스위치와 같은 방법이다.
#
# **스위치 하나가 모든 덱·모든 카드에 걸린다.**  Anki 는 카드를 넘길 때마다 스크립트를
# 처음부터 다시 돌리므로 고른 값은 스크립트 바깥에 남긴다.  저장소는 사다리다 —
# localStorage(앱을 닫아도 남는다) → sessionStorage(이번 실행 동안) → window(이 화면
# 동안).  막힌 칸은 건너뛰고, 전부 막혀도 카드는 그려진다.
#
# 고른 것이 없으면 **Anki 의 야간 모드를 따른다**(body 의 nightMode·night_mode).
# 고르면 **스위치 버튼 자신**에 sp-dark / sp-light 를 붙이고, tokens.css 가
# `:root:has(.sp-dark)` 처럼 그 표식을 찾아 페이지 전체의 토큰을 뒤집는다.  카드
# CSS 는 색을 전부 토큰으로 읽으므로 카드 쪽은 손댈 것이 없다.
#
# **표식을 body 에 달면 안 된다.**  Anki 는 카드를 넘길 때마다 body 의 class 를
# 통째로 다시 쓰고(`card card1 nightMode` …) 그 일을 이 스크립트가 돈 **뒤에** 한다.
# body 에 단 sp-dark 는 다음 카드에서 지워져 다크가 풀렸다.  버튼은 이 템플릿의
# 마크업이라 Anki 가 손대지 않는다 — 토익 예문 스위치가 제 카드 요소에 class 를
# 다는 것과 같은 이유다.
#
# 다크 모드는 카드가 아니라 **카드를 얹는 종이**의 일이라 Anki 껍데기가 맡는다.
# 편집기에는 이 스위치가 없다 — 편집기 셸은 언제나 주간이다.
THEME_JS = r"""
(function () {
  var KEY = %(key)s;
  var body = document.body;
  var button = document.getElementById(%(theme)s);
  var stores = [];
  try { if (window.localStorage) stores.push(window.localStorage); } catch (e) { /* 막혀 있다 */ }
  try { if (window.sessionStorage) stores.push(window.sessionStorage); } catch (e) { /* 막혀 있다 */ }
  var valid = function (value) { return value === 'dark' || value === 'light'; };
  function kept() {
    for (var i = 0; i < stores.length; i++) {
      try { var value = stores[i].getItem(KEY); if (valid(value)) return value; } catch (e) { /* 다음 칸 */ }
    }
    return valid(window.__spTheme) ? window.__spTheme : null;
  }
  function keep(value) {
    window.__spTheme = value;          /* 저장소가 전부 막혀도 이 화면에서는 듣는다 */
    for (var i = 0; i < stores.length; i++) {
      try { stores[i].setItem(KEY, value); } catch (e) { /* 다음 칸 */ }
    }
  }
  function ankiNight() {
    var list = body && body.classList;
    return !!list && (list.contains('nightMode') || list.contains('night_mode'));
  }
  function paint(value) {
    var dark = value ? value === 'dark' : ankiNight();
    if (button) {
      button.className = 'sp-theme' + (value ? ' sp-' + value : '');
      button.textContent = dark ? '다크 ON' : '다크 OFF';
      button.setAttribute('aria-pressed', dark ? 'true' : 'false');
    }
    return dark;
  }
  if (!button) return;
  var dark = paint(kept());
  /* 고른 것이 없을 때의 표시는 Anki 의 야간 표식을 읽는다.  그 표식은 이 스크립트가
   * 돈 뒤에 붙을 수 있으므로 한 박자 뒤에 한 번 더 읽는다. */
  if (typeof setTimeout === 'function') {
    setTimeout(function () { if (!kept()) dark = paint(null); }, 0);
  }
  button.onclick = function (event) {
    if (event && event.stopPropagation) event.stopPropagation();
    dark = !dark;
    var value = dark ? 'dark' : 'light';
    keep(value);
    paint(value);
  };
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
    mount = (f'<button type="button" class="sp-theme" id="{THEME_ID}"'
             f' aria-pressed="false">다크</button>'
             f'<div class="sp-mount" id="{MOUNT_ID}"></div>'
             f'<div id="{DATA_ID}" hidden>{{{{text:{DATA_FIELD}}}}}</div>')
    setup = MOUNT_JS % {
        "mount": json.dumps(MOUNT_ID),
        "data": json.dumps(DATA_ID),
        "renderer": json.dumps(renderer),
        "options": json.dumps({**options, "mode": mode}, ensure_ascii=False),
    } + THEME_JS % {
        "key": json.dumps(THEME_KEY),
        "theme": json.dumps(THEME_ID),
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
