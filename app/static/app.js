'use strict';

/* Current-schema editor with the legacy shell and interaction rhythm. */

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const value = document.createElement(tag);
  if (cls) value.className = cls;
  if (text !== undefined) value.textContent = text;
  return value;
};

const TAG_LABELS = {
  s1: '소학교 1학년', s2: '소학교 2학년', s3: '소학교 3학년',
  s4: '소학교 4학년', s5: '소학교 5학년', s6: '소학교 6학년',
  j: '학년 외 상용한자', h: '표외한자'
};
const VARIANT_LABELS = [
  '康熙字典体', '簡易慣用字体', '許容字体', '印刷標準字体（表外漢字字体表）'
];
const GROUPS = [
  ['on', '음독'], ['kun', '훈독'], ['verb', '동사 활용'], ['exc', '특례 읽기']
];
const state = {
  /* 지금 보고 있는 덱.  서버가 decks/ 를 열거해 준 것 중 하나다. */
  deck: null,
  decks: [],
  ch: null,
  meta: null,
  model: null,
  base: '',
  recordEtag: '',
  mode: 'reading-front',
  bootstrap: null,
  saving: false,
  searchSerial: 0,
  draftDirty: false,
  draftReadingGroup: null,
  /* 한자별 필기 획.  카드를 다시 그려도, 앞뒤를 뒤집어도 남는다. */
  strokes: {}
};

let editRenderTimer = null;
let searchTimer = null;
let resolveAsk = null;
let modalReturnFocus = null;

const clone = (value) => JSON.parse(JSON.stringify(value));
const dirty = () => Boolean(state.model)
  && (state.draftDirty || JSON.stringify(state.model) !== state.base);

async function request(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    const wrapped = new Error('서버에 연결할 수 없다. 실행 상태를 확인한다.');
    wrapped.cause = error;
    throw wrapped;
  }
  let body;
  try {
    body = await response.json();
  } catch (error) {
    const wrapped = new Error(`서버가 JSON이 아닌 응답을 보냈다 (${response.status})`);
    wrapped.cause = error;
    throw wrapped;
  }
  if (!response.ok) {
    const error = new Error(body.error || `요청 실패 (${response.status})`);
    error.payload = body;
    error.status = response.status;
    throw error;
  }
  return body;
}

function showErrors(title, list = []) {
  const box = $('errors');
  box.innerHTML = '';
  box.append(el('b', null, title));
  if (list.length) {
    const lines = el('ul');
    for (const line of list) lines.append(el('li', null, line));
    box.append(lines);
  }
  box.hidden = false;
  box.scrollIntoView({ block: 'nearest' });
}

function clearErrors() {
  $('errors').hidden = true;
  $('errors').innerHTML = '';
}

function showStatus(text) {
  $('status').textContent = text;
  $('status').hidden = !text;
}

/* 덱 전용 렌더러와 스타일은 그 덱 폴더에서 온다.  CSP 가 'self' 이므로 같은
 * 출처의 정적 파일만 부를 수 있고, 덱마다 한 번씩만 싣는다. */
const loaded = new Set();

function loadDeckAssets(name) {
  if (loaded.has(name)) return Promise.resolve();
  loaded.add(name);
  const style = document.createElement('link');
  style.rel = 'stylesheet';
  style.href = `/deck/${name}/card.css`;
  document.head.append(style);
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = `/deck/${name}/card.js`;
    script.onload = resolve;
    script.onerror = () => reject(new Error(`${name} 렌더러를 부르지 못했다`));
    document.head.append(script);
  });
}

function renderDeckTabs() {
  const box = $('decks');
  box.innerHTML = '';
  for (const info of state.decks) {
    const button = el('button', 'deck' + (info.deck === state.deck ? ' on' : ''),
      info.title);
    button.type = 'button';
    button.setAttribute('aria-pressed', info.deck === state.deck ? 'true' : 'false');
    button.onclick = () => switchDeck(info.deck);
    box.append(button);
  }
}

async function switchDeck(name) {
  if (name === state.deck) return;
  if (dirty()) {
    const answer = await ask(`${state.ch}의 수정이 저장되지 않았다. 어떻게 할까?`);
    if (answer === 'cancel') return;
    if (answer === 'save' && !(await save())) return;
  }
  state.deck = name;
  state.ch = null;
  state.model = null;
  state.base = '';
  state.mode = (state.decks.find((deck) => deck.deck === name).modes[0] || {}).key
    || 'reading-front';
  $('q').value = '';
  $('hits').innerHTML = '';
  clearErrors();
  await loadDeckAssets(name);
  renderDeckTabs();
  await boot();
  render();
}

async function boot() {
  try {
    if (!state.decks.length) {
      const listing = await request('/api/decks');
      state.decks = listing.decks;
      if (!state.decks.length) throw new Error('열린 덱이 없다');
      state.deck = state.decks[0].deck;
      state.mode = (state.decks[0].modes[0] || {}).key || 'reading-front';
      await loadDeckAssets(state.deck);
      renderDeckTabs();
    }
    const info = state.decks.find((deck) => deck.deck === state.deck);
    state.bootstrap = info;
    const size = info.records ?? info.characters ?? 0;
    $('q').placeholder = `${info.title} ${size.toLocaleString()}개에서 찾기`;
    if (info.overlay_conflict) {
      showStatus('파이프라인 원본과 편집 기록의 기준 SHA가 다르다. 조회는 가능하지만 저장하려면 rebase가 필요하다.');
    }
    await refreshLog('');
    renderModes();
    renderAnki();          // 한자를 고르기 전에도 덱 상태는 보인다
  } catch (error) {
    showErrors(error.message, error.payload?.errors || []);
  }
}

async function search(text) {
  const box = $('hits');
  const query = text.trim();
  const serial = ++state.searchSerial;
  box.innerHTML = '';
  if (!query) {
    $('search-status').textContent = '';
    return;
  }
  try {
    const data = await request(`/api/${state.deck}/search?q=` + encodeURIComponent(query));
    if (serial !== state.searchSerial) return;
    if (!data.results.length) {
      box.append(el('div', 'muted', '없다'));
      $('search-status').textContent = '검색 결과 없음';
      return;
    }
    for (const row of data.results) {
      const hit = el('button', 'hit' + (row.key === state.ch ? ' on' : ''));
      hit.type = 'button';
      hit.setAttribute('role', 'option');
      hit.setAttribute('aria-selected', row.key === state.ch ? 'true' : 'false');
      hit.append(el('span', 'ch', row.title));
      hit.append(el('span', 'ko', row.subtitle || ''));
      hit.onclick = () => go(row.key);
      box.append(hit);
    }
    if (data.total > data.results.length) {
      box.append(el('div', 'muted more', `그 밖에 ${data.total - data.results.length}자`));
    }
    $('search-status').textContent = `검색 결과 ${data.total}자`;
  } catch (error) {
    if (serial !== state.searchSerial) return;
    box.append(el('div', 'muted', error.message));
    $('search-status').textContent = '검색 실패';
  }
}

async function go(character) {
  if (dirty()) {
    const answer = await ask(`${state.ch}의 수정이 저장되지 않았다. 어떻게 할까?`);
    if (answer === 'cancel') return;
    if (answer === 'save' && !(await save())) return;
  }
  await load(character);
}

async function load(character) {
  try {
    const data = await request(`/api/${state.deck}/record/` + encodeURIComponent(character));
    state.ch = data.key;
    state.meta = data;
    state.model = clone(data.record);
    state.base = JSON.stringify(state.model);
    state.recordEtag = data.record_etag;
    state.draftDirty = false;
    state.draftReadingGroup = null;
    $('reason').value = '';
    clearErrors();
    render();
    await refreshLog(character);
    await search($('q').value);
    return true;
  } catch (error) {
    showErrors(error.message, error.payload?.errors || []);
    return false;
  }
}

/* 카드에 넘길 봉투.  **덱 이름을 알지 않는다.**
 *
 * 레코드를 카드가 읽는 모양으로 옮기는 일은 덱의 렌더러(`noteFrom`)가 한다.
 * 그래야 Anki 도 같은 함수로 같은 카드를 그린다 — Anki 노트의 Data 필드에는
 * 여기와 **같은 모양의 봉투**가 실려 있고, 노트 타입의 스크립트가 이 셸이 하는
 * 것과 똑같이 `noteFrom` 을 부른다. */
function cardEnvelope() {
  return {
    key: state.ch,
    record: state.model,
    derived: (state.meta && state.meta.derived) || {}
  };
}

function noteFromModel() {
  return deckRenderer().noteFrom(cardEnvelope(), {
    draftReadingGroup: state.draftReadingGroup
  });
}

function render() {
  renderMeta();
  renderCard();
  renderSlots();
  renderModes();
  renderEditor();
  renderAnki();
  markDirty();
  $('savebar').hidden = !state.ch;
}

/* Anki 연동.  덱을 통째로 내보내는 것이 아니라, 지금 상태와 Anki 를 대조해
 * 무엇이 바뀌는지 먼저 보여 준 뒤 사람이 누르면 반영한다.
 * 덱 이름을 하드코딩하지 않는다 — 서버가 decks/ 를 열거해 준 것을 그대로 그린다. */
async function renderAnki(status) {
  const box = $('anki');
  const scope = $('anki-scope');
  box.innerHTML = '';
  if (!status) {
    box.append(el('div', 'muted', '상태 확인 중…'));
    try {
      status = await request('/api/anki/status');
    } catch (error) {
      box.innerHTML = '';
      box.append(el('div', 'muted', error.message));
      return;
    }
    box.innerHTML = '';
  }
  if (!status.available) {
    scope.textContent = '';
    box.append(el('div', 'muted', 'Anki 가 응답하지 않는다. Anki 를 실행하고 '
      + 'AnkiConnect(2055492159) 애드온을 확인한다.'));
    return;
  }
  const decks = status.decks || [];
  scope.textContent = `덱 ${decks.length}`;
  let pendingTotal = 0;
  for (const deck of decks) {
    const row = el('div', 'anki-deck');
    const head = el('div', 'anki-deck-head');
    head.append(el('span', 'anki-title', deck.title));
    // 한 덱이 노트 타입을 여럿 낼 수 있다(문법의 읽기·작문).  어느 것인지 밝힌다.
    head.append(el('span', 'muted', deck.note_type || deck.deck));
    row.append(head);
    if (deck.reason) {
      row.append(el('div', 'muted', deck.reason));
      box.append(row);
      continue;
    }
    const plan = deck.plan || {};
    /* 노트가 그대로여도 카드 모습이 옛것일 수 있다 — Anki 에서 실행 취소를 누르면
     * 노트 타입 갱신만 되돌아간다.  그때도 반영할 것이 있다고 보여야 한다. */
    const drift = deck.note_type_drift || [];
    const pending = (plan.add ?? 0) + (plan.update ?? 0) + (plan.move ?? 0)
      + drift.length;
    pendingTotal += pending;
    const nums = el('div', 'anki-plan');
    nums.append(el('span', 'anki-num add', `추가 ${plan.add ?? 0}`));
    nums.append(el('span', 'anki-num upd', `갱신 ${plan.update ?? 0}`));
    nums.append(el('span', 'anki-num same', `그대로 ${plan.unchanged ?? 0}`));
    if (plan.move) nums.append(el('span', 'anki-num upd', `이동 ${plan.move}`));
    if (plan.new_decks) {
      nums.append(el('span', 'anki-num stale', `새 덱 ${plan.new_decks}`));
    }
    if (plan.stale) nums.append(el('span', 'anki-num stale', `옛 노트 ${plan.stale}`));
    if (drift.length) {
      nums.append(el('span', 'anki-num stale', `카드 모습 ${drift.join(' · ')}`));
    }
    row.append(nums);
    /* Anki 에만 있고 계획에는 없는 노트다.  식별자 규칙이 바뀌면 남는다.
     * 지우는 것은 사람의 몫이므로 어디서 찾는지만 알려 준다. */
    /* 새로 만들어진 덱은 언제나 **기본 사전 설정**을 쓴다.  설정은 사람의 것이므로
     * 프로젝트가 붙여 주지 않는다 — 대신 붙여야 한다는 사실을 알린다. */
    if (plan.new_decks) {
      row.append(el('div', 'muted',
        `덱 ${plan.new_decks}개가 새로 생겼다. 새 덱은 기본 사전 설정을 쓰므로 `
        + `Anki 에서 학습 옵션을 붙여야 한다.`));
    }
    if (plan.stale) {
      row.append(el('div', 'muted',
        `계획에 없는 옛 노트 ${plan.stale} 개가 Anki 에 남아 있다. `
        + `카드가 비어 보이므로 '도구 > 빈 카드' 로 정리한다.`));
    }
    const button = el('button', 'anki-sync',
      pending ? `반영 (${pending})` : '반영할 것 없음');
    button.type = 'button';
    button.disabled = !pending;
    button.onclick = () => syncAnki(deck.name, button);
    row.append(button);
    box.append(row);
  }
  box.append(el('div', 'muted',
    pendingTotal ? '삭제는 하지 않는다. 추가와 갱신만 한다.'
                 : 'Anki 가 최신 상태다.'));
}

async function syncAnki(name, button) {
  button.disabled = true;
  button.textContent = '반영 중…';
  try {
    const done = await request(`/api/anki/sync?deck=${encodeURIComponent(name)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ schema_version: 1 })
    });
    const line = (done.decks || [])
      .map((d) => `${d.deck} 추가 ${d.result.add} · 갱신 ${d.result.update}`)
      .join(' / ');
    showStatus(`Anki 반영: ${line || '변경 없음'}`);
  } catch (error) {
    showErrors(error.message, error.payload?.errors || []);
  }
  renderAnki();
}

/* 편집은 탭이 아니라 사이드바에 산다.  어느 덱을 보고 있든 같은 자리에서
 * 고칠 수 있고, 카드는 언제나 '보이는 그대로' 를 유지한다. */
function renderEditor() {
  const box = $('editor');
  const scope = $('editor-scope');
  box.innerHTML = '';
  scope.textContent = state.ch || '';
  if (!state.model) {
    box.append(el('div', 'muted', '한자를 고르면 편집할 수 있다.'));
    return;
  }

  if (state.deck === 'bunpo') {
    renderBunpoEditor(box);
    return;
  }
  if (state.deck === 'toeic') {
    renderToeicEditor(box);
    return;
  }
  box.append(editorTagRow());
  box.append(editorSection('한국 훈음', koreanRows()));
  box.append(editorSection('이체자', variantRows()));
  box.append(editorSection('용례 후리가나 일괄 입력', [bulkFuriganaField()]));
  box.append(editorSection('요미카타와 용례', exampleRows()));
}

/* 토익 편집기.
 *
 * 고칠 것은 **뜻과 그 순서**다.  '이 낱말의 어느 뜻이 TOEIC 에 자주 나오는가' 가 이
 * 덱의 알맹이인데 그것을 정한 것은 모델이므로, 사람이 뒤집을 수 있어야 한다.
 * 빈도·어족·빈도대는 원전에서 온 사실이라 고치지 않는다 — 보여만 준다. */
function renderToeicEditor(box) {
  const record = state.model;

  const fact = el('div', 'editor-row');
  fact.append(el('span', 'editor-key', '원전'));
  fact.append(el('span', 'muted',
    `${(record.list || '').toUpperCase()} ${record.rank} · ${record.band}`));
  box.append(fact);

  const family = el('div', 'editor-row');
  family.append(el('span', 'editor-key', '어형'));
  family.append(el('span', 'muted', (record.family || []).join(' · ')));
  box.append(family);

  box.append(editorSection('뜻', (record.senses || []).map((sense, index) => {
    const group = el('div', 'editor-reading');

    const head = el('div', 'editor-reading-head');
    const pos = document.createElement('select');
    pos.className = 'editor-select';
    pos.setAttribute('aria-label', '품사');
    for (const [key, label] of Object.entries(ToeicCard.POS_LABELS)) {
      const option = document.createElement('option');
      option.value = key;
      option.textContent = label;
      if (sense.pos === key) option.selected = true;
      pos.append(option);
    }
    pos.onchange = () => {
      state.model.senses[index].pos = pos.value;
      render();
    };
    head.append(pos);
    if (sense.checked && sense.checked !== 'jmdict') {
      head.append(el('span', 'bn-chip', sense.checked === 'phrase' ? '구' : '읽기 미확인'));
    }
    head.append(smallButton('↑', () => moveSense(index, -1), 'text', '위로'));
    head.append(smallButton('↓', () => moveSense(index, 1), 'text', '아래로'));
    head.append(smallButton('×', () => {
      state.model.senses.splice(index, 1);
      render();
    }, 'del', '뜻 삭제'));
    group.append(head);

    const ja = editable(['senses', index, 'ja'], sense.ja, '일본어 (후리가나는 괄호로)');
    ja.classList.add('editor-ja');
    group.append(ja);
    group.append(editable(['senses', index, 'gloss'], sense.gloss, '일본어 뜻풀이'));
    const en = editable(['senses', index, 'en'], sense.en, '영어 뜻풀이');
    en.classList.add('editor-meaning');
    group.append(en);
    return group;
  }).concat([(() => {
    const row = el('div', 'editor-row');
    row.append(smallButton('＋ 뜻', () => {
      state.model.senses = state.model.senses || [];
      state.model.senses.push({ ja: '', pos: 'noun', gloss: '', en: '',
        checked: 'unsure' });
      render();
    }, 'text', '뜻 추가'));
    return row;
  })()])));
}

/* 뜻의 순서가 곧 '자주 나오는 순서' 다.  사람이 바꿀 수 있어야 한다. */
function moveSense(index, step) {
  const senses = state.model.senses || [];
  const target = index + step;
  if (target < 0 || target >= senses.length) return;
  [senses[index], senses[target]] = [senses[target], senses[index]];
  render();
}

/* 문법 편집기.
 *
 * 문형의 뜻·급수·접속형과, 예문마다 표기·해석·문법 구간을 고친다.  구간은 예문
 * 문자열 안의 별표 표시가 곧 데이터이므로 따로 입력칸을 두지 않는다 — 별표를 옮기면
 * 그것이 곧 구간 수정이다. */
function renderBunpoEditor(box) {
  const record = state.model;

  const head = el('div', 'editor-row');
  head.append(el('span', 'editor-key', '표제형'));
  head.append(editable(['head'], record.head, '표제형'));
  box.append(head);

  const level = el('div', 'editor-row');
  level.append(el('span', 'editor-key', '급수'));
  const select = document.createElement('select');
  select.setAttribute('aria-label', '급수');
  // 원전은 옛 JLPT 급수로 적는다.  4級=N5, 3級=N4, 2級=N2, 1級=N1 (N3 는 대응 없음).
  for (const [value, label] of [['4', 'N5'], ['3', 'N4'], ['2', 'N2'], ['1', 'N1']]) {
    const option = el('option', null, label);
    option.value = value;
    option.selected = value === record.level;
    select.append(option);
  }
  select.onchange = () => { state.model.level = select.value; render(); };
  level.append(select);
  box.append(level);

  const meaning = el('div', 'editor-row');
  meaning.append(el('span', 'editor-key', '뜻'));
  meaning.append(editable(['gloss_ko'], record.gloss_ko, '한국어 뜻'));
  box.append(meaning);

  const connectRows = (record.connect || []).map((shape, index) => {
    const row = el('div', 'editor-row');
    row.append(editable(['connect', index], shape, '접속형'));
    row.append(smallButton('×', () => {
      state.model.connect.splice(index, 1);
      render();
    }, 'del', '접속형 삭제'));
    return row;
  });
  const addConnect = el('div', 'editor-row');
  addConnect.append(smallButton('＋ 접속형', () => {
    state.model.connect = state.model.connect || [];
    state.model.connect.push('');
    render();
  }, 'text', '접속형 추가'));
  connectRows.push(addConnect);
  box.append(editorSection('접속형', connectRows));

  box.append(editorSection('예문 일괄 입력', [bunpoBulkField()]));

  box.append(editorSection('예문', (record.examples || []).map((example, index) => {
    const group = el('div', 'editor-reading');
    const label = el('div', 'editor-reading-head');
    label.append(el('span', 'muted', String(example.no || index + 1)));
    const span = BunpoCard.splitMarked(example.marked || example.ja || '')[1];
    label.append(el('span', 'bn-chip', span || '구간 미표시'));
    group.append(label);

    const ja = editable(['examples', index, 'marked'],
      example.marked || example.ja, '예문 (문법 구간을 별표로 감싼다)');
    ja.classList.add('editor-ja');
    ja.onblur = () => {
      // 표시를 걷은 것이 곧 원문이어야 한다.  둘을 함께 맞춘다.
      const marked = ja.textContent.replace(/[\r\n]/g, '').trim();
      const target = state.model.examples[index];
      target.marked = marked;
      target.ja = marked.split(BunpoCard.MARK).join('');
      if (marked.includes(BunpoCard.MARK) && !target.mark_method) {
        target.mark_method = 'human';
      }
      renderAfterEditing();
    };
    group.append(ja);

    const ko = editable(['examples', index, 'ko'], example.ko, '한국어 해석');
    ko.classList.add('editor-meaning');
    group.append(ko);
    return group;
  })));

  box.append(editorSection('한국어 해설',
    [editable(['note_ko'], record.note_ko, '해설')]));
}

/* 예문을 한 줄에 하나씩 놓고 통째로 고친다.  문법 구간의 별표도 여기서 옮긴다. */
function bunpoBulkField() {
  const wrap = el('div', 'bulk-furigana');
  const rows = state.model.examples || [];
  const area = document.createElement('textarea');
  area.className = 'bulk-input';
  area.rows = Math.min(14, Math.max(4, rows.length + 1));
  area.spellcheck = false;
  area.setAttribute('aria-label', '예문 일괄 입력');
  area.value = rows.map((example) => example.marked || example.ja || '').join('\n');
  wrap.append(el('div', 'muted',
    `한 줄에 예문 하나. 문법 구간은 별표로 감싼다. 줄 수(${rows.length})를 지켜야 한다.`));
  wrap.append(area);

  const report = el('div', 'bulk-report');
  wrap.append(smallButton('적용', () => {
    const lines = area.value.split('\n');
    if (lines.length !== rows.length) {
      report.className = 'bulk-report bad';
      report.textContent = `줄 수가 다르다 — ${lines.length} ≠ ${rows.length}`;
      return;
    }
    const failures = [];
    lines.forEach((line, position) => {
      const marked = line.trim();
      if (!marked) {
        failures.push(`${position + 1}행: 비었다`);
        return;
      }
      const marks = marked.split(BunpoCard.MARK).length - 1;
      if (marks !== 0 && marks !== 2) {
        failures.push(`${position + 1}행: 별표가 짝을 이루지 않는다`);
      }
    });
    if (failures.length) {
      report.className = 'bulk-report bad';
      report.textContent = failures.slice(0, 4).join(' / ');
      return;
    }
    lines.forEach((line, position) => {
      const marked = line.trim();
      const target = state.model.examples[position];
      target.marked = marked;
      target.ja = marked.split(BunpoCard.MARK).join('');
      if (marked.includes(BunpoCard.MARK) && !target.mark_method) {
        target.mark_method = 'human';
      }
    });
    report.className = 'bulk-report good';
    report.textContent = `${lines.length}건 반영했다.`;
    markDirty();
    renderCard();
  }, 'text', '예문 일괄 적용'));
  wrap.append(report);
  return wrap;
}


function editorSection(title, children) {
  const section = el('div', 'editor-section');
  section.append(el('div', 'editor-section-title', title));
  const body = el('div', 'editor-section-body');
  for (const child of children) body.append(child);
  if (!children.length) body.append(el('div', 'muted', '없음'));
  section.append(body);
  return section;
}

function editorTagRow() {
  const row = el('div', 'editor-row');
  row.append(el('span', 'editor-key', '분류'));
  const select = document.createElement('select');
  select.setAttribute('aria-label', '한자 분류');
  for (const [value, label] of Object.entries(TAG_LABELS)) {
    const option = el('option', null, `${value} · ${label}`);
    option.value = value;
    option.selected = value === state.model.tag;
    select.append(option);
  }
  select.onchange = () => {
    state.model.tag = select.value;
    render();
  };
  row.append(select);
  return row;
}

function koreanRows() {
  const rows = [];
  for (const [form, values] of Object.entries(state.model.korean)) {
    const row = el('div', 'editor-row');
    row.append(el('span', 'editor-key', form === '본' ? '본자' : form));
    const list = el('div', 'editor-values');
    values.forEach((value, index) => {
      const chip = el('div', 'editor-chip');
      chip.append(editable(['korean', form, index], value, `${form} 훈음`));
      chip.append(smallButton('×', () => {
        state.model.korean[form].splice(index, 1);
        if (form === '본') syncKoreanSource();
        render();
      }, 'del', `${form} 훈음 삭제`));
      list.append(chip);
    });
    list.append(smallButton('＋', () => {
      state.model.korean[form].push('');
      if (form === '본') syncKoreanSource();
      render();
    }, '', `${form} 훈음 추가`));
    row.append(list);
    rows.push(row);
  }
  return rows;
}

function variantRows() {
  const rows = Object.entries(state.model.variant)
    .map(([variant, label]) => variantRow(variant, label));
  const add = el('div', 'editor-row');
  add.append(smallButton('＋ 이체자', addVariant, 'text', '이체자 추가'));
  rows.push(add);
  return rows;
}

/* 카드에 보이는 것과 같은 순서로 모든 용례를 훑는다.  일괄 입력의 줄 순서가
 * 이 순서다. */
function everyExample() {
  const found = [];
  for (const bucket of ['readings', 'except']) {
    for (const [rawKey, examples] of Object.entries(state.model[bucket])) {
      examples.forEach((example, index) => {
        found.push({ bucket, rawKey, index, example });
      });
    }
  }
  return found;
}

function bulkFuriganaField() {
  const wrap = el('div', 'bulk-furigana');
  const rows = everyExample();
  const area = document.createElement('textarea');
  area.className = 'bulk-input';
  area.rows = Math.min(14, Math.max(4, rows.length));
  area.spellcheck = false;
  area.setAttribute('aria-label', '용례 후리가나 일괄 입력');
  area.value = rows.map(({ example }) => example.w || '').join('\n');
  wrap.append(el('div', 'muted',
    `한 줄에 용례 하나. 순서와 줄 수(${rows.length})를 지켜야 한다.`));
  wrap.append(area);

  const report = el('div', 'bulk-report');
  const apply = smallButton('적용', () => {
    const lines = area.value.split('\n');
    if (lines.length !== rows.length) {
      report.className = 'bulk-report bad';
      report.textContent = `줄 수가 다르다 — ${lines.length} ≠ ${rows.length}`;
      return;
    }
    const failures = [];
    lines.forEach((line, position) => {
      const annotated = line.trim();
      const { example } = rows[position];
      if (!annotated) {
        failures.push(`${position + 1}행: 비었다`);
        return;
      }
      const surface = KanjiCard.plainSurface(example.w);
      if (!KanjiCard.parseAnnotated(annotated)) {
        failures.push(`${position + 1}행: 후리가나 주석 문법이 아니다 — ${annotated}`);
      } else if (KanjiCard.plainSurface(annotated) !== surface) {
        failures.push(`${position + 1}행: 표기가 ${surface} 에서 `
          + `${KanjiCard.plainSurface(annotated)} 로 바뀐다 — ${annotated}`);
      }
    });
    if (failures.length) {
      report.className = 'bulk-report bad';
      report.textContent = failures.slice(0, 4).join(' / ')
        + (failures.length > 4 ? ` 외 ${failures.length - 4}건` : '');
      return;
    }
    lines.forEach((line, position) => {
      const { bucket, rawKey, index } = rows[position];
      state.model[bucket][rawKey][index].w = line.trim();
    });
    report.className = 'bulk-report good';
    report.textContent = `${lines.length}건 반영했다.`;
    markDirty();
    renderCard();
  }, 'text', '후리가나 일괄 적용');
  wrap.append(apply);
  wrap.append(report);
  return wrap;
}

function exampleRows() {
  const rows = [];
  for (const bucket of ['readings', 'except']) {
    for (const [rawKey, examples] of Object.entries(state.model[bucket])) {
      const group = el('div', 'editor-reading');
      const head = el('div', 'editor-reading-head');
      head.append(bucket === 'except'
        ? editableExceptionKey(rawKey)
        : editableReadingKey(rawKey));
      head.append(el('span', 'muted', bucket === 'except' ? '특례' : ''));
      group.append(head);
      const sourceIndices = examples.map((_, index) => index);
      examples.forEach((example, index) => {
        const row = el('div', 'editor-example');
        row.append(editableAnnotation(bucket, rawKey, index, example));
        const meaning = editable([bucket, rawKey, index, 'ko'], example.ko, '한국어 뜻');
        meaning.classList.add('editor-meaning');
        row.append(meaning);
        row.append(wordFoot(bucket, rawKey, index, example, sourceIndices, index));
        group.append(row);
      });
      group.append(smallButton('＋ 용례', () => {
        state.model[bucket][rawKey].push({ w: '', ko: '', ja: '' });
        render();
      }, 'text addword', `${rawKey} 용례 추가`));
      rows.push(group);
    }
  }
  const add = el('div', 'editor-row');
  add.append(smallButton('＋ 특례', addException, 'text', '특례 읽기 추가'));
  rows.push(add);
  return rows;
}

function renderModes() {
  const box = $('modes');
  box.innerHTML = '';
  // 편집은 더 이상 탭이 아니다.  모든 탭에서 사이드바로 편집한다.
  // 어떤 면이 있는지는 덱이 선언한다.
  const info = state.decks.find((deck) => deck.deck === state.deck);
  const items = (info ? info.modes : []).map((mode) => [mode.key, mode.label]);
  for (const [key, label] of items) {
    const button = el('button', 'mode' + (state.mode === key ? ' on' : ''), label);
    button.type = 'button';
    button.setAttribute('aria-pressed', state.mode === key ? 'true' : 'false');
    button.onclick = () => {
      state.mode = key;
      render();
    };
    box.append(button);
  }
}

function renderMeta() {
  const box = $('meta');
  box.innerHTML = '';
  if (!state.meta) return;
  const add = (text, cls = '') => box.append(el('span', `badge${cls ? ` ${cls}` : ''}`, text));
  if (state.deck === 'toeic') {
    const derived = state.meta.derived || {};
    if (derived.band_label) add(derived.band_label, 'codepoint');
    add(`${(derived.list || '').toUpperCase()} ${derived.rank}`);
    add(`뜻 ${(derived.senses || []).length}`);
    if (derived.unverified) add(`사전 미확인 ${derived.unverified}`, 'warning');
    if (state.meta.edited) add('사람이 고침', 'current');
    return;
  }
  if (state.deck === 'bunpo') {
    const derived = state.meta.derived || {};
    if (derived.level) add(derived.level, 'codepoint');
    add(`예문 ${(derived.examples || []).length}`);
    if (derived.unmarked) add(`문법 구간 미표시 ${derived.unmarked}`, 'warning');
    if (state.meta.edited) add('사람이 고침', 'current');
    return;
  }
  add(state.meta.codepoint, 'codepoint');

  const tag = el('span', 'badge current');
  tag.textContent = `${state.model.tag} · ${TAG_LABELS[state.model.tag]}`;
  box.append(tag);

  // 이체자는 카드 헤더가 한자 옆에 직접 보여주므로 뱃지로 중복하지 않는다.
  if (Object.keys(state.model.except).length) add(`특례 ${Object.keys(state.model.except).length}`);
  if (state.model.korean_src === 'gemini') add('훈음 Gemini 보완');
  if (state.meta.edited) add('사람이 고침', 'current');
  if (state.meta.derived.annotation_warnings) {
    add(`읽기 감사 ${state.meta.derived.annotation_warnings}`, 'warning');
  }
}

function deckRenderer() {
  const info = state.decks.find((deck) => deck.deck === state.deck);
  const name = info && info.renderer;
  return (name && window[name]) || window.KanjiCard;
}

function renderCard() {
  const box = $('card');
  box.innerHTML = '';
  if (!state.ch) {
    box.append(el('div', 'empty', '왼쪽에서 찾아 누른다.'));
    return;
  }
  const rendered = deckRenderer().render(noteFromModel(), {
    mode: state.mode,
    strokes: strokesFor(state.ch)
  });
  rendered.tabIndex = 0;
  rendered.setAttribute('role', 'button');
  rendered.setAttribute('aria-label', '카드 앞뒷면 전환');
  rendered.title = '클릭하거나 Space를 눌러 앞뒷면을 전환한다';
  rendered.onclick = flipPreview;
  rendered.onkeydown = (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      flipPreview();
    }
  };
  box.append(rendered);
  box.append(el('div', 'card-flip-hint', '카드를 클릭 · SPACE 로 뒤집기'));
}

function flipPreview() {
  const previous = state.mode;
  const opposite = {
    'reading-front': 'reading-back',
    'reading-back': 'reading-front',
    'writing-front': 'writing-back',
    'writing-back': 'writing-front',
    'produce-front': 'produce-back',
    'produce-back': 'produce-front',
    'spell-front': 'spell-back',
    'spell-back': 'spell-front'
  }[state.mode];
  if (!opposite) return;
  const info = state.decks.find((deck) => deck.deck === state.deck);
  if (info && !info.modes.some((mode) => mode.key === opposite)) return;
  state.mode = opposite;
  const card = $('card').querySelector('.preview-card');
  if (!card) {
    render();
    return;
  }
  // 가리기는 전적으로 CSS 가 한다.  DOM 을 다시 만들지 않으므로 필기가 남는다.
  card.classList.remove(previous);
  card.classList.add(opposite);
  renderModes();
}

function handleEditableKeydown(event, target) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    target.blur();
  }
}

/* 필기는 한자별로 남는다.  앞뒤 전환은 물론 카드를 다시 그려도 유지된다. */
function strokesFor(character) {
  if (!state.strokes[character]) state.strokes[character] = [];
  return state.strokes[character];
}

function readPath(path) {
  let target = state.model;
  for (const key of path) target = target[key];
  return target;
}

function writePath(path, value) {
  let target = state.model;
  for (let index = 0; index < path.length - 1; index += 1) target = target[path[index]];
  target[path[path.length - 1]] = value;
}

function syncKoreanSource() {
  if (!state.base || !state.model) return;
  const loaded = JSON.parse(state.base);
  if (loaded.korean_src === 'gemini'
      && JSON.stringify(loaded.korean.본) === JSON.stringify(state.model.korean.본)) {
    state.model.korean_src = 'gemini';
  } else {
    delete state.model.korean_src;
  }
}

function editable(path, value, placeholder) {
  const field = el('div', 'field-value', value || '');
  field.contentEditable = 'plaintext-only';
  field.spellcheck = false;
  field.dataset.empty = placeholder || '';
  field.setAttribute('aria-label', placeholder || path.join('.'));
  const sync = () => {
    writePath(path, field.textContent.replace(/[\r\n]/g, ''));
    if (path[0] === 'korean' && path[1] === '본') syncKoreanSource();
    markDirty();
  };
  field.oninput = sync;
  field.oncompositionend = sync;
  field.onblur = () => {
    const next = field.textContent.trim();
    field.textContent = next;
    writePath(path, next);
    if (path[0] === 'korean' && path[1] === '본') syncKoreanSource();
    renderAfterEditing();
  };
  field.onkeydown = (event) => handleEditableKeydown(event, field);
  return field;
}

function editableReadingKey(rawKey) {
  const field = el('span', 'reading-name', rawKey);
  field.contentEditable = 'plaintext-only';
  field.spellcheck = false;
  field.dataset.empty = '읽기';
  field.setAttribute('aria-label', `${rawKey} 읽기 키`);
  field.oninput = () => {
    state.draftDirty = true;
    markDirty();
  };
  field.onkeydown = (event) => handleEditableKeydown(event, field);
  field.onblur = () => {
    const next = field.textContent.trim();
    if (next !== rawKey && !renameReading(rawKey, next)) field.textContent = rawKey;
    state.draftDirty = false;
    renderAfterEditing();
  };
  return field;
}

function editableExceptionKey(fragment) {
  const field = el('span', 'reading-name', fragment);
  field.contentEditable = 'plaintext-only';
  field.spellcheck = false;
  field.dataset.empty = '특례 읽기';
  field.setAttribute('aria-label', `${fragment || '새'} 특례 읽기 키`);
  field.oninput = () => {
    state.draftDirty = true;
    markDirty();
  };
  field.onkeydown = (event) => handleEditableKeydown(event, field);
  field.onblur = () => {
    const next = field.textContent.trim();
    if (next !== fragment && !renameKeyIn('except', fragment, next)) field.textContent = fragment;
    state.draftDirty = false;
    renderAfterEditing();
  };
  return field;
}

function makeEditablePiece(text, cls, label, sync) {
  const field = el('span', cls, text);
  field.contentEditable = 'plaintext-only';
  field.spellcheck = false;
  field.dataset.empty = label;
  field.setAttribute('aria-label', label);
  field.oninput = sync;
  field.oncompositionend = sync;
  field.onblur = () => {
    field.textContent = field.textContent.trim();
    sync();
    renderAfterEditing();
  };
  field.onkeydown = (event) => handleEditableKeydown(event, field);
  return field;
}

function editableAnnotation(bucket, rawKey, index, example) {
  const parsed = KanjiCard.parseAnnotated(example.w);
  if (!parsed) return rawAnnotationRepair(bucket, rawKey, index, example);
  const box = el('div', 'spell editable-spell');
  box.title = '표기와 한자 위의 후리가나를 직접 누르면 고친다';
  const pieces = [];
  const sync = () => {
    // 후리가나는 표기 안에 실린다.  조각을 다시 이어 붙여 w 하나만 만든다.
    const target = state.model[bucket][rawKey][index];
    const annotated = [];
    for (const piece of pieces) {
      const surface = piece.surface.textContent.replace(/[\r\n]/g, '');
      if (piece.reading === null) {
        annotated.push(surface);
        continue;
      }
      const reading = piece.reading.textContent.replace(/[\r\n]/g, '');
      annotated.push(piece.source === 'printed'
        ? `${surface}（${reading}）`
        : `${surface}(${reading})`);
    }
    target.w = annotated.join('');
    markDirty();
  };

  for (const segment of parsed.segments) {
    const surface = makeEditablePiece(segment.surface, 'piece-surface', '표기', sync);
    if (segment.reading === null) {
      box.append(surface);
      pieces.push({ surface, reading: null, source: 'literal' });
      continue;
    }
    const ruby = el('ruby', segment.source === 'printed' ? 'printed-ruby' : 'generated-ruby');
    const rt = document.createElement('rt');
    const reading = makeEditablePiece(segment.reading, 'piece-reading', '후리가나', sync);
    rt.append(reading);
    ruby.append(surface, rt);
    box.append(ruby);
    pieces.push({ surface, reading, source: segment.source });
  }
  return box;
}

/* 주석 문법이 깨져 조각으로 나눌 수 없을 때의 마지막 수단.  표기 한 칸을 날것으로
 * 고치게 하고, 다시 문법에 맞으면 조각 편집기로 돌아간다. */
function rawAnnotationRepair(bucket, rawKey, index, example) {
  const box = el('div', 'raw-repair');
  const row = document.createElement('label');
  row.append(el('span', null, '표기'));
  const input = document.createElement('input');
  input.value = example.w || '';
  input.placeholder = '한자(よみ) 꼴로 적는다';
  input.setAttribute('aria-label', '후리가나가 실린 표기');
  input.oninput = () => {
    state.model[bucket][rawKey][index].w = input.value;
    markDirty();
  };
  input.onblur = renderAfterEditing;
  row.append(input);
  box.append(row);
  return box;
}

function wordFoot(bucket, rawKey, sourceIndex, example, visibleIndices, visiblePosition) {
  const foot = el('div', 'word-foot');
  const rawLabel = example._display
    ? '결합 용례 · 특례 중복 제외'
    : `w ${example.w || '∅'}`;
  foot.append(el('span', 'raw', rawLabel));
  foot.append(el('span', 'spacer'));
  const move = (step) => {
    if (Array.isArray(visibleIndices) && Number.isInteger(visiblePosition)) {
      moveVisibleArray(state.model[bucket][rawKey], visibleIndices, visiblePosition, step);
    } else {
      moveArray(state.model[bucket][rawKey], sourceIndex, step);
    }
  };
  foot.append(smallButton('↑', () => move(-1), '', '용례 위로'));
  foot.append(smallButton('↓', () => move(1), '', '용례 아래로'));
  foot.append(smallButton('✕', () => {
    state.model[bucket][rawKey].splice(sourceIndex, 1);
    render();
  }, 'del', '용례 삭제'));
  return foot;
}

function variantRow(variant, label) {
  const row = el('div', 'native-row variant-row');
  const key = document.createElement('input');
  key.className = 'native-key';
  key.value = variant;
  key.placeholder = '이체자';
  key.setAttribute('aria-label', '이체자 글자');
  key.oninput = () => {
    state.draftDirty = true;
    markDirty();
  };
  key.onchange = () => {
    const next = key.value.trim();
    if (!renameVariant(variant, next)) key.value = variant;
    state.draftDirty = false;
    renderAfterEditing();
  };
  row.append(key);
  const select = document.createElement('select');
  select.className = 'native-value';
  select.setAttribute('aria-label', `${variant || '새'} 이체자 종류`);
  for (const value of VARIANT_LABELS) {
    const option = el('option', null, value);
    option.value = value;
    option.selected = value === label;
    select.append(option);
  }
  select.onchange = () => {
    state.model.variant[variant] = select.value;
    markDirty();
  };
  select.onblur = renderAfterEditing;
  row.append(select);
  if (!(variant in state.model.korean)) {
    row.append(smallButton('훈음', () => {
      state.model.korean[variant] = [];
      render();
    }, 'text', '이체자 훈음 그룹 추가'));
  }
  row.append(smallButton('✕', () => {
    const koreanValues = state.model.korean[variant] || [];
    if (koreanValues.length && !window.confirm(
      `${variant} 이체자와 그 훈음 ${koreanValues.length}개를 함께 삭제할까?`
    )) return;
    delete state.model.variant[variant];
    if (variant in state.model.korean) delete state.model.korean[variant];
    render();
  }, 'del', '이체자 삭제'));
  return row;
}

function renameObjectKey(object, oldKey, newKey) {
  if (oldKey === newKey) return object;
  const output = {};
  for (const [key, value] of Object.entries(object)) {
    output[key === oldKey ? newKey : key] = value;
  }
  return output;
}

function canRename(object, oldKey, newKey, label) {
  if (oldKey === newKey) return true;
  if (newKey in object) {
    showErrors(`${label} \`${newKey}\`가 이미 있다.`);
    return false;
  }
  return true;
}

function renameReading(oldKey, newKey) {
  if (!canRename(state.model.readings, oldKey, newKey, '읽기')) return false;
  state.model.readings = renameObjectKey(state.model.readings, oldKey, newKey);
  if (oldKey === '') state.draftReadingGroup = null;
  markDirty();
  return true;
}

function renameVariant(oldKey, newKey) {
  if (!canRename(state.model.variant, oldKey, newKey, '이체자')) return false;
  state.model.variant = renameObjectKey(state.model.variant, oldKey, newKey);
  if (oldKey in state.model.korean) {
    if (newKey in state.model.korean) {
      showErrors(`한국 훈음 형태 \`${newKey}\`가 이미 있어 이체자 키를 바꿀 수 없다.`);
      state.model.variant = renameObjectKey(state.model.variant, newKey, oldKey);
      return false;
    }
    state.model.korean = renameObjectKey(state.model.korean, oldKey, newKey);
  }
  markDirty();
  return true;
}

function renameKeyIn(field, oldKey, newKey) {
  if (!canRename(state.model[field], oldKey, newKey, field)) return false;
  state.model[field] = renameObjectKey(state.model[field], oldKey, newKey);
  markDirty();
  return true;
}

function addVariant() {
  if ('' in state.model.variant) {
    showErrors('먼저 비어 있는 이체자 행을 채운다.');
    return;
  }
  state.model.variant[''] = VARIANT_LABELS[0];
  render();
}

function addException() {
  if ('' in state.model.except) {
    showErrors('먼저 비어 있는 특례 읽기 행을 채운다.');
    return;
  }
  state.model.except[''] = [{ w: '', ko: '', ja: '' }];
  render();
}

function smallButton(label, action, cls = '', ariaLabel = label) {
  const button = el('button', `mini${cls ? ` ${cls}` : ''}`, label);
  button.type = 'button';
  button.setAttribute('aria-label', ariaLabel);
  button.onclick = action;
  return button;
}

function renderSlots() {
  if (state.deck !== 'kanji') {          // 슬롯은 요미카타 구조가 있는 덱만 쓴다
    $('slots').innerHTML = '';
    $('slot-count').textContent = '';
    return;
  }
  const box = $('slots');
  box.innerHTML = '';
  if (!state.model) {
    $('slot-count').textContent = '';
    return;
  }
  const readingKeys = Object.keys(state.model.readings);
  const regularCount = Object.values(state.model.readings).reduce(
    (sum, values) => sum + KanjiCard.visibleRegularEntries(values, state.model.except).length,
    0
  );
  const exceptionCount = Object.values(state.model.except).reduce((sum, values) => sum + values.length, 0);
  $('slot-count').textContent = `읽기 ${readingKeys.length} · 용례 ${regularCount} · 특례 ${exceptionCount}`;

  for (const [groupKey, label] of GROUPS) {
    const group = el('div', `slot-group group-${groupKey}`);
    const title = el('div', 'gname');
    title.append(el('span', null, label));
    if (groupKey === 'exc') {
      title.append(smallButton('＋ 읽기', addException, 'text', '특례 읽기 추가'));
    } else {
      title.append(smallButton('＋ 읽기', () => addReading(groupKey), 'text', `${label} 추가`));
    }
    group.append(title);

    if (groupKey === 'exc') {
      for (const [fragment, examples] of Object.entries(state.model.except)) {
        const slot = el('div', 'slot group-exc');
        const head = el('div', 'slot-head');
        const dot = el('span', 'slot-dot group-exc', '●');
        head.append(dot, el('span', 'nm', fragment || '(이름 없음)'), el('span', 'kind', '특례'));
        head.append(smallButton('✕', () => {
          delete state.model.except[fragment];
          render();
        }, 'del', '특례 읽기 삭제'));
        slot.append(head);
        examples.forEach((example, index) => {
          const line = el('div', 'slot-ex');
          line.append(el('span', 'w', KanjiCard.plainSurface(example.w) || '(빈 용례)'));
          line.append(smallButton('↑', () => moveArray(examples, index, -1), '', '용례 위로'));
          line.append(smallButton('↓', () => moveArray(examples, index, 1), '', '용례 아래로'));
          line.append(smallButton('✕', () => {
            examples.splice(index, 1);
            render();
          }, 'del', '특례 용례 삭제'));
          slot.append(line);
        });
        group.append(slot);
      }
      group.append(el('div', 'slot-note', '특례는 일반 용례 슬롯과 합치지 않는다.'));
      box.append(group);
      continue;
    }

    for (const rawKey of readingKeys.filter((key) => readingGroup(key) === groupKey)) {
      const examples = state.model.readings[rawKey];
      const visibleEntries = KanjiCard.visibleRegularEntries(examples, state.model.except);
      const visibleIndices = visibleEntries.map(({ sourceIndex }) => sourceIndex);
      const slot = el('div', `slot group-${groupKey}`);
      const head = el('div', 'slot-head');
      const dot = el('span', `slot-dot group-${groupKey}`, '●');
      head.append(dot, el('span', 'nm', rawKey || '(이름 없음)'));
      head.append(el('span', 'kind', groupKey === 'on' ? '음독' : groupKey === 'verb' ? '동사 활용' : '훈독'));
      head.append(smallButton('↑', () => moveReading(rawKey, -1), '', '읽기 위로'));
      head.append(smallButton('↓', () => moveReading(rawKey, 1), '', '읽기 아래로'));
      head.append(smallButton('＋', () => {
        examples.push({ w: '', ko: '', ja: '' });
        render();
      }, '', '용례 추가'));
      head.append(smallButton('✕', () => {
        delete state.model.readings[rawKey];
        if (rawKey === '') state.draftReadingGroup = null;
        render();
      }, 'del', '읽기 삭제'));
      slot.append(head);
      visibleEntries.forEach(({ example, sourceIndex }, visiblePosition) => {
        const line = el('div', 'slot-ex');
        const display = KanjiCard.displayParts(example);
        line.append(el('span', 'w', display.surface || '(빈 용례)'));
        line.append(smallButton('↑', () => {
          moveVisibleArray(examples, visibleIndices, visiblePosition, -1);
        }, '', '용례 위로'));
        line.append(smallButton('↓', () => {
          moveVisibleArray(examples, visibleIndices, visiblePosition, 1);
        }, '', '용례 아래로'));
        line.append(smallButton('✕', () => {
          examples.splice(sourceIndex, 1);
          render();
        }, 'del', '용례 삭제'));
        slot.append(line);
      });
      group.append(slot);
    }
    box.append(group);
  }
}

function readingGroup(rawKey) {
  return rawKey === '' ? state.draftReadingGroup : KanjiCard.groupOfKey(rawKey);
}

function addReading(group) {
  if ('' in state.model.readings) {
    showErrors('먼저 이름이 비어 있는 새 읽기를 채운다.');
    return;
  }
  state.draftReadingGroup = group;
  state.model.readings[''] = [{ w: '', ko: '', ja: '' }];
  render();
}

function moveArray(items, index, step) {
  const target = index + step;
  if (target < 0 || target >= items.length) return;
  [items[index], items[target]] = [items[target], items[index]];
  render();
}

function moveVisibleArray(items, visibleIndices, position, step) {
  const targetPosition = position + step;
  if (targetPosition < 0 || targetPosition >= visibleIndices.length) return;
  const sourceIndex = visibleIndices[position];
  const targetIndex = visibleIndices[targetPosition];
  [items[sourceIndex], items[targetIndex]] = [items[targetIndex], items[sourceIndex]];
  render();
}

function moveReading(rawKey, step) {
  const keys = Object.keys(state.model.readings);
  const group = readingGroup(rawKey);
  const visible = keys.filter((key) => readingGroup(key) === group);
  const position = visible.indexOf(rawKey);
  const targetPosition = position + step;
  if (targetPosition < 0 || targetPosition >= visible.length) return;
  const other = visible[targetPosition];
  const first = keys.indexOf(rawKey);
  const second = keys.indexOf(other);
  [keys[first], keys[second]] = [keys[second], keys[first]];
  const reordered = {};
  for (const key of keys) reordered[key] = state.model.readings[key];
  state.model.readings = reordered;
  render();
}

function renderAfterEditing() {
  clearTimeout(editRenderTimer);
  editRenderTimer = setTimeout(() => {
    const active = document.activeElement;
    if (active && (active.isContentEditable || active.matches('input, select, textarea'))) return;
    render();
  }, 0);
}

function markDirty() {
  const on = dirty();
  const indicator = $('dirty');
  indicator.textContent = on ? '고친 것이 있다' : '고친 것 없음';
  indicator.className = 'dirty' + (on ? ' on' : '');
  $('save').disabled = !on || state.saving || Boolean(state.meta?.overlay_conflict);
  $('save').textContent = state.saving ? '저장 중…' : '저장';
}

async function save() {
  if (!dirty()) return true;
  const reason = $('reason').value.trim();
  if (!reason) {
    showErrors('사유를 적어야 저장한다.');
    $('reason').focus();
    return false;
  }
  if (state.saving) return false;
  state.saving = true;
  markDirty();
  try {
    const answer = await request(`/api/${state.deck}/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        schema_version: 1,
        key: state.ch,
        record_etag: state.recordEtag,
        reason,
        record: state.model
      })
    });
    clearErrors();
    state.recordEtag = answer.record_etag;
    state.base = JSON.stringify(state.model);
    state.draftDirty = false;
    if (state.meta) state.meta.edited = true;
    $('reason').value = '';
    const reloaded = await load(state.ch);
    if (!reloaded) {
      showStatus('저장은 완료됐지만 최신 화면을 다시 불러오지 못했다. 연결을 확인한 뒤 새로고침한다.');
    }
    return true;
  } catch (error) {
    showErrors(error.message, error.payload?.errors || []);
    return false;
  } finally {
    state.saving = false;
    markDirty();
  }
}

async function refreshLog(character) {
  try {
    const data = await request(`/api/${state.deck}/log?key=` + encodeURIComponent(character));
    const box = $('log');
    box.innerHTML = '';
    $('log-scope').textContent = character || '전체';
    if (!data.lines.length) {
      box.append(el('div', 'muted', '아직 없다'));
      return;
    }
    for (const line of data.lines) {
      const entry = el('div', 'log-entry');
      const changes = line.changes || [];
      const first = changes[0];
      entry.append(el('span', 'p', `${line.character} · ${changes.length}곳`));
      if (first) {
        entry.append(document.createElement('br'));
        entry.append(el('span', null, `${first.path}: ${show(first.before)} → `));
        entry.append(el('b', null, show(first.after)));
        if (changes.length > 1) entry.append(el('span', 'p', ` 외 ${changes.length - 1}곳`));
      }
      entry.append(document.createElement('br'));
      entry.append(el('span', 'p', `${line.at.replace('T', ' ').replace('Z', ' UTC')} · ${line.reason}`));
      box.append(entry);
    }
  } catch (error) {
    $('log').innerHTML = '';
    $('log').append(el('div', 'muted', error.message));
  }
}

const show = (value) => value === null || value === undefined
  ? '(없음)'
  : typeof value === 'object' ? JSON.stringify(value) : String(value);

function ask(text) {
  $('modal-text').textContent = text;
  $('modal').hidden = false;
  modalReturnFocus = document.activeElement;
  $('m-save').focus();
  return new Promise((resolve) => { resolveAsk = resolve; });
}

function answerModal(value) {
  return () => {
    $('modal').hidden = true;
    const resolve = resolveAsk;
    resolveAsk = null;
    if (modalReturnFocus) modalReturnFocus.focus();
    resolve(value);
  };
}

$('q').oninput = (event) => {
  clearTimeout(searchTimer);
  const value = event.target.value;
  searchTimer = setTimeout(() => search(value), 120);
};
$('save').onclick = () => save();
$('revert').onclick = () => {
  if (state.ch) load(state.ch);
};
$('m-save').onclick = answerModal('save');
$('m-drop').onclick = answerModal('drop');
$('m-cancel').onclick = answerModal('cancel');

$('modal').onkeydown = (event) => {
  if (event.key === 'Escape') answerModal('cancel')();
};

window.addEventListener('beforeunload', (event) => {
  if (dirty()) {
    event.preventDefault();
    event.returnValue = '';
  }
});

window.addEventListener('keydown', (event) => {
  if (event.code !== 'Space' && event.key !== ' ') return;
  const target = event.target;
  if (target instanceof Element && target.closest(
    'input, select, textarea, button, [contenteditable="true"], [contenteditable="plaintext-only"]'
  )) return;
  if (!['reading-front', 'reading-back', 'writing-front', 'writing-back'].includes(state.mode)) return;
  event.preventDefault();
  flipPreview();
});

// 덱 목록을 받아야 모드도 정해지므로 boot 가 먼저다.
boot();
