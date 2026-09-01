'use strict';

/* 토익 카드 렌더러.
 *
 * 한자 카드가 '한 글자와 그 읽기들' 을, 문법 카드가 '한 문형과 그것이 쓰인 문장들' 을
 * 보여 준다면, 토익 카드는 **'한 영어 낱말과 그 뜻들'** 을 보여 준다.  뜻은 모델이
 * 매긴 TOEIC 빈도 순서 그대로 위에서 아래로 놓는다 — 그 순서가 이 덱의 알맹이다.
 *
 * 면은 둘이다.  뜻 앞면은 영어를 보고 일본어 뜻을 떠올리게 하고, 철자 앞면은 일본어를
 * 보고 영어 철자를 떠올리게 한다.  **무엇을 가릴지는 렌더러가 정하지 않는다** — DOM 은
 * 언제나 같고 카드 요소의 모드 클래스 하나로 갈리며, 가리는 일은 card.css 가 한다.
 * 그래서 앞뒤 전환이 클래스 토글로 끝나고, 같은 렌더러가 편집기와 Anki 를 함께 그린다. */

(() => {
  /* 품사마다 마커 색이 다르다.  한자 덱의 음독·훈독·동사·특례와 같은 색상환을 쓴다 —
   * 두 덱을 오갈 때 눈이 다시 적응하지 않아도 되게. */
  const POS_ORDER = ['noun', 'verb', 'adjective', 'adverb', 'function'];
  const POS_LABELS = {
    noun: '명사',
    verb: '동사',
    adjective: '형용사',
    adverb: '부사',
    function: '기능어'
  };
  const CHECK_LABELS = { phrase: '구', unsure: '읽기 미확인' };

  const node = (tag, cls, text) => {
    const value = document.createElement(tag);
    if (cls) value.className = cls;
    if (text !== undefined) value.textContent = text;
    return value;
  };

  /* 후리가나는 표기 안에 실린다.  반각 (…) 만 파이프라인이 붙인 것이다. */
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

  /* 주석 표기를 루비로 그린다.  ``搭乗(とうじょう)する`` -> <ruby>搭乗<rt>…</rt></ruby>する */
  function rubyInto(parent, annotated) {
    const text = String(annotated || '');
    let index = 0;
    let plain = '';
    const flush = () => {
      if (plain) { parent.append(document.createTextNode(plain)); plain = ''; }
    };
    while (index < text.length) {
      const open = text.indexOf('(', index);
      if (open === -1) { plain += text.slice(index); break; }
      const close = text.indexOf(')', open + 1);
      if (close === -1) { plain += text.slice(index); break; }
      /* 괄호 바로 앞의 한자런이 루비를 인다. */
      const head = text.slice(index, open);
      let cut = head.length;
      while (cut > 0 && /[㐀-鿿豈-﫿々〆]/.test(head[cut - 1])) cut -= 1;
      if (cut === head.length) {
        /* **읽기를 일 한자런이 없으면 루비가 아니다.**  빈 <ruby> 를 만들면 읽기가
         * 걸릴 글자 없이 허공에 뜨고 그 자리가 벌어져, 문장 한가운데에 설명할 수
         * 없는 틈이 생긴다.  표시가 `後*(あと)` 처럼 한자와 그 읽기 사이로 끼어든
         * 조각을 받았을 때가 그렇다 — 데이터에서 막지만(문법 덱의 `marking.groups`)
         * 사람이 편집기에서 직접 고칠 수도 있으므로, 그럴 때는 글자 그대로 싣는다. */
        plain += text.slice(index, close + 1);
        index = close + 1;
        continue;
      }
      plain += head.slice(0, cut);
      flush();
      const ruby = node('ruby');
      ruby.append(document.createTextNode(head.slice(cut)));
      const rt = document.createElement('rt');
      rt.textContent = text.slice(open + 1, close);
      ruby.append(rt);
      parent.append(ruby);
      index = close + 1;
    }
    flush();
  }

  /* 레코드 하나를 카드가 읽는 모양으로.  **편집기와 Anki 가 같은 이 함수를 쓴다.**
   *
   * 편집기는 사람이 고치는 중인 레코드를, Anki 는 노트의 Data 필드에서 푼 레코드를
   * 넣는다.  둘 다 `{key, record, derived}` 라는 같은 봉투다.  이 덱은 `derived` 에서
   * 아무것도 읽지 않는다 — 낱말과 뜻은 레코드 하나로 충분하다. */
  function noteFrom(envelope) {
    const record = (envelope && envelope.record) || {};
    return {
      word: (envelope && envelope.key) || '',
      band: record.band || '',
      rank: record.rank || 0,
      list: record.list || '',
      family: record.family || [],
      senses: record.senses || []
    };
  }

  /* 예문 켜고 끄기 — **카드 안의 스위치 하나가 모든 카드에 걸린다.**
   *
   * Anki 는 카드를 넘길 때마다 이 스크립트를 **처음부터 다시 돌린다.**  그래서 '지금
   * 예문을 보는가' 는 스크립트 바깥에 남겨야 다음 카드가 이어받는다.  필기판이 앞면의
   * 획을 뒷면으로 넘기는 것과 같은 방법이다(한자 덱의 `keepStrokes`).
   *
   * 칸은 하나뿐이고 값은 `on`/`off` 뿐이다 — 카드마다 다른 설정을 두지 않는다.
   * 그래야 '전역 스위치' 라는 말이 성립한다.
   *
   * 저장소는 **사다리**다.
   *   localStorage    앱을 닫았다 열어도 남는다
   *   sessionStorage  이번 실행 동안 남는다
   *   window          이 화면 동안만 남는다
   * 웹뷰에 따라 위쪽 칸이 막혀 있을 수 있으므로(사생활 모드, 오리진이 매번 바뀌는
   * 경우) 되는 데까지 내려간다.  전부 막혀도 카드는 그대로 그려지고, 스위치는 그
   * 카드 안에서만 듣는다. */
  const SWITCH = 'sp-toeic-examples';

  const stores = () => {
    const found = [];
    for (const name of ['localStorage', 'sessionStorage']) {
      try { if (window[name]) found.push(window[name]); } catch (error) { /* 막혀 있다 */ }
    }
    return found;
  };

  /* 지금 예문을 보여 주는가.  저장된 것이 없으면 덱이 정한 기본값을 따른다. */
  function examplesShown(options) {
    for (const store of stores()) {
      try {
        const kept = store.getItem(SWITCH);
        if (kept === 'on' || kept === 'off') return kept === 'on';
      } catch (error) { /* 다음 칸으로 */ }
    }
    if (typeof window.__toeicExamples === 'boolean') return window.__toeicExamples;
    return options.examples !== false;
  }

  function keepExamples(shown) {
    window.__toeicExamples = shown;      /* 저장소가 전부 막혀도 이 화면에서는 듣는다 */
    for (const store of stores()) {
      try { store.setItem(SWITCH, shown ? 'on' : 'off'); } catch (error) { /* 다음 칸 */ }
    }
  }

  /* 뜻 한 줄.
   *
   * 왼쪽은 **외울 것**이고 오른쪽은 **뜻풀이**다.  일본어 낱말 아래에 예문 두 줄이
   * 이어지고, 짧은 뜻풀이(일본어·영어)는 오른쪽 단에 쌓인다.  뜻풀이는 '이 뜻이
   * 무엇인가' 를 가르는 표찰이라 곁다리로 물러나고, 예문은 '그 뜻이 어떻게 쓰이는가'
   * 를 보여 주므로 낱말 바로 아래 본문 자리에 온다. */
  function senseRow(sense, options) {
    const row = node('div', `tc-sense pos-${sense.pos || 'noun'}`);

    const head = node('div', 'tc-sense-head');
    head.append(node('span', 'tc-dot', '●'));
    head.append(node('span', 'tc-pos', POS_LABELS[sense.pos] || sense.pos || ''));
    /* 사전으로 확인되지 않은 뜻은 편집기에서만 표시한다.  학습 카드에 띄울 진단이 아니다. */
    if (options.diagnostics !== false && CHECK_LABELS[sense.checked]) {
      head.append(node('span', 'tc-check', CHECK_LABELS[sense.checked]));
    }
    row.append(head);

    const body = node('div', 'tc-sense-body');
    const columns = node('div', 'tc-columns');

    const main = node('div', 'tc-main');
    const spell = node('span', 'tc-ja');
    rubyInto(spell, sense.ja || '');
    main.append(spell);
    const example = sense.example || {};
    if (example.en || example.ja) {
      const pair = node('div', 'tc-example');
      if (example.en) pair.append(node('div', 'tc-ex-en', example.en));
      if (example.ja) {
        const line = node('div', 'tc-ex-ja');
        rubyInto(line, example.ja);
        pair.append(line);
      }
      main.append(pair);
    }
    columns.append(main);

    const aside = node('div', 'tc-aside');
    if (sense.gloss) aside.append(node('div', 'tc-gloss', sense.gloss));
    if (sense.en) aside.append(node('div', 'tc-en', sense.en));
    columns.append(aside);

    body.append(columns);
    row.append(body);
    return row;
  }

  function render(note, options = {}) {
    const mode = options.mode || 'reading-front';
    const base = `toeic-card preview-card ${mode}`;
    const card = node('article', base);

    /* 예문을 보는지는 **클래스 하나로** 드러낸다.  무엇을 가릴지는 여기서 정하지
     * 않고 card.css 가 그 클래스로 정한다 — 앞뒤 모드와 같은 방법이다. */
    let shown = examplesShown(options);
    const toggle = node('button', 'tc-switch');
    toggle.setAttribute('type', 'button');
    const paint = () => {
      card.className = `${base} ${shown ? 'examples-on' : 'examples-off'}`;
      toggle.textContent = shown ? '예문 ON' : '예문 OFF';
      toggle.setAttribute('aria-pressed', shown ? 'true' : 'false');
    };
    toggle.onclick = (event) => {
      /* 카드를 누르면 뒤집히는 화면이 있다.  스위치는 그 클릭이 아니다. */
      if (event && event.stopPropagation) event.stopPropagation();
      shown = !shown;
      keepExamples(shown);
      paint();
    };
    paint();

    const head = node('header', 'tc-head');
    const title = node('div', 'tc-title');
    title.append(node('span', 'tc-en-word', note.word || ''));
    if (note.band) title.append(node('span', 'tc-band', note.band));
    head.append(title);

    const side = node('div', 'tc-side');
    side.append(toggle);
    /* 어족은 표제어를 빼고 보여 준다 — 표제어는 이미 위에 크게 있다. */
    const forms = (note.family || []).filter((form) => form.toLowerCase() !== note.word);
    if (forms.length) side.append(node('div', 'tc-family', forms.join(' · ')));
    if (note.rank) {
      side.append(node('div', 'tc-rank',
        `${note.list === 'tsl' ? 'TSL' : 'NGSL'} ${note.rank}`));
    }
    head.append(side);
    card.append(head);

    const list = node('div', 'tc-senses');
    const senses = [...(note.senses || [])];
    if (!senses.length) {
      list.append(node('div', 'tc-empty', '뜻이 없다'));
    }
    for (const sense of senses) list.append(senseRow(sense, options));
    card.append(list);
    return card;
  }

  window.ToeicCard = {
    render,
    noteFrom,
    plainSurface,
    examplesShown,
    keepExamples,
    SWITCH,
    POS_ORDER,
    POS_LABELS
  };
})();
