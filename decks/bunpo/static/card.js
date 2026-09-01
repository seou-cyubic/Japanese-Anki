'use strict';

/* 문법 카드 렌더러.
 *
 * 한자 카드가 '한 글자와 그 읽기들' 을 보여 준다면, 문법 카드는 '한 문형과 그것이
 * 쓰인 문장들' 을 보여 준다.  예문마다 문법 구간이 `*` 로 표시되어 있으므로
 * split 한 번으로 갈라 강조한다.
 *
 * 면은 둘이다.  뜻 앞면은 일본어 예문만 보고 뜻을 떠올리게 하고, 작문 앞면은
 * 한국어만 보고 일본어를 짓게 한다.  어느 쪽이든 문법 구간은 강조한 채로 둔다 —
 * 어느 부분이 그 문형인지 보면서 연습하는 것이 이 카드의 요점이다.
 *
 * **무엇을 가릴지는 렌더러가 정하지 않는다.**  DOM 은 언제나 같고 카드 요소의
 * 모드 클래스 하나로 갈리며, 가리는 일은 card.css 가 한다.  그래서 앞뒤 전환이
 * 클래스 토글로 끝나고, 같은 렌더러가 편집기와 Anki 양쪽을 그릴 수 있다. */

(() => {
  const MARK = '*';

  const node = (tag, cls, text) => {
    const value = document.createElement(tag);
    if (cls) value.className = cls;
    if (text !== undefined) value.textContent = text;
    return value;
  };

  /* 후리가나는 표기 안에 실린다.  반각 (…) 만 생성분이다. */
  const plainSurface = (annotated) => {
    if (typeof annotated !== 'string') return '';
    let out = '';
    let index = 0;
    while (index < annotated.length) {
      if (annotated[index] === '(') {
        const closeAt = annotated.indexOf(')', index + 1);
        if (closeAt === -1) { out += annotated[index]; index += 1; continue; }
        index = closeAt + 1;
        continue;
      }
      out += annotated[index];
      index += 1;
    }
    return out;
  };

  /* `앞*문법*뒤` 를 셋으로.  표시가 없으면 가운데가 빈다. */
  const splitMarked = (marked) => {
    const parts = String(marked || '').split(MARK);
    if (parts.length >= 3) return [parts[0], parts[1], parts.slice(2).join(MARK)];
    return [String(marked || ''), '', ''];
  };

  /* 주석 표기를 루비로 그린다.  ``空港(くうこう)`` -> <ruby>空港<rt>くうこう</rt></ruby> */
  function rubyInto(parent, annotated) {
    let index = 0;
    let plain = '';
    const flush = () => {
      if (plain) { parent.append(document.createTextNode(plain)); plain = ''; }
    };
    while (index < annotated.length) {
      const open = annotated.indexOf('(', index);
      if (open === -1) { plain += annotated.slice(index); break; }
      const close = annotated.indexOf(')', open + 1);
      if (close === -1) { plain += annotated.slice(index); break; }
      /* 괄호 바로 앞의 한자런이 루비를 인다. */
      const head = annotated.slice(index, open);
      let cut = head.length;
      while (cut > 0 && /[㐀-鿿豈-﫿々〆]/.test(head[cut - 1])) cut -= 1;
      if (cut === head.length) {
        /* **읽기를 일 한자런이 없으면 루비가 아니다.**  빈 <ruby> 를 만들면 읽기가
         * 걸릴 글자 없이 허공에 뜨고 그 자리가 벌어져, 문장 한가운데에 설명할 수
         * 없는 틈이 생긴다.  표시가 `後*(あと)` 처럼 한자와 그 읽기 사이로 끼어든
         * 조각을 받았을 때가 그렇다 — 데이터에서 막지만(문법 덱의 `marking.groups`)
         * 사람이 편집기에서 직접 고칠 수도 있으므로, 그럴 때는 글자 그대로 싣는다. */
        plain += annotated.slice(index, close + 1);
        index = close + 1;
        continue;
      }
      plain += head.slice(0, cut);
      flush();
      const ruby = node('ruby');
      ruby.append(document.createTextNode(head.slice(cut)));
      const rt = document.createElement('rt');
      rt.textContent = annotated.slice(open + 1, close);
      ruby.append(rt);
      parent.append(ruby);
      index = close + 1;
    }
    flush();
  }

  function exampleRow(example, position, options) {
    const row = node('div', 'bn-ex');
    const line = node('div', 'bn-ja');
    line.append(node('span', 'bn-no', example.no || String(position)));
    const [before, grammar, after] = splitMarked(example.marked || example.ja || '');
    const body = node('span', 'bn-body');
    rubyInto(body, before);
    if (grammar) {
      const span = node('span', 'bn-span');
      rubyInto(span, grammar);
      body.append(span);
    }
    rubyInto(body, after);
    line.append(body);
    row.append(line);
    row.append(node('div', 'bn-ko', example.ko || ''));
    /* 문법 구간이 비었다는 표시는 **편집기의 진단**이다.  학습 카드에 띄울 것이
     * 아니므로 Anki 는 diagnostics:false 로 끈다. */
    if (!grammar && options.diagnostics !== false) {
      row.append(node('div', 'bn-unmarked', '문법 구간 미표시'));
    }
    return row;
  }

  /* 레코드 하나를 카드가 읽는 모양으로.  **편집기와 Anki 가 같은 이 함수를 쓴다.**
   *
   * 편집기는 사람이 고치는 중인 레코드를, Anki 는 노트의 Data 필드에서 푼 레코드를
   * 넣는다.  둘 다 `{key, record, derived}` 라는 같은 봉투이므로 같은 카드가 나온다.
   * `derived` 에서 읽는 것은 **급수 표기 하나뿐**이다 — 원전의 옛 급수(1~4級)와 현행
   * N 등급의 대응은 `decks/bunpo/deck.py` 의 LEVEL_LABEL 한 곳에서만 정한다. */
  function noteFrom(envelope) {
    const record = (envelope && envelope.record) || {};
    const derived = (envelope && envelope.derived) || {};
    return {
      head: record.head || (envelope && envelope.key) || '',
      level: derived.level || '',
      meaning: record.gloss_ko || '',
      glossJa: record.gloss_ja || '',
      connect: record.connect || [],
      note: record.note_ko || '',
      examples: record.examples || []
    };
  }

  function render(note, options = {}) {
    const mode = options.mode || 'reading-front';
    const card = node('article', `bunpo-card preview-card ${mode}`);

    const head = node('header', 'bn-head');
    const title = node('div', 'bn-title');
    title.append(node('span', 'bn-grammar', note.head || ''));
    if (note.level) title.append(node('span', 'bn-level', note.level));
    head.append(title);
    const side = node('div', 'bn-side');
    side.append(node('div', 'bn-meaning', note.meaning || ''));
    if (note.glossJa) {
      const gloss = node('div', 'bn-gloss');
      rubyInto(gloss, note.glossJa);
      side.append(gloss);
    }
    if ((note.connect || []).length) {
      side.append(node('div', 'bn-connect', note.connect.join('  /  ')));
    }
    head.append(side);
    card.append(head);

    const list = node('div', 'bn-examples');
    (note.examples || []).forEach((example, index) => {
      list.append(exampleRow(example, index + 1, options));
    });
    card.append(list);

    // 해설은 앞뒤 어디서나 보인다.  문형을 이해하는 데 쓰는 참고 자료다.
    if (note.note) card.append(node('div', 'bn-note', note.note));
    return card;
  }

  window.BunpoCard = { render, noteFrom, plainSurface, splitMarked, MARK };
})();
