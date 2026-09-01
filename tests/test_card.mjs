import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import vm from 'node:vm';

/* **산출물이 없으면 건너뛴다.**
 *
 * 이 시험은 렌더러를 **원전 산출물과 실제 노트 타입에 대고** 잰다 — 용례 11,910 건을
 * 훑고, 진짜 레코드를 그리고, 파이썬이 만든 Anki 카드 면을 실행한다.  산출물이 없으면
 * 잴 것 자체가 없으므로 터지는 대신 그 사실을 말하고 물러난다.  갓 받은 저장소에는
 * 언제나 없다 — 원전의 파생물이라 올리지 않기 때문이다(`tests/__init__.py` 와 같은
 * 규칙이고, 그쪽은 파이썬 시험을 skip 으로 넘긴다). */
const required = [
  'decks/kanji/data/data_japanese.json',
  'decks/bunpo/data/bunpo_korean.json'
];
const missing = required.filter((path) => !fs.existsSync(path));
if (missing.length) {
  process.stdout.write(
    `건너뜀: ${missing.join(', ')} 이 아직 없다 — 파이프라인을 먼저 돌린다
`);
  process.exit(0);
}

globalThis.window = {};
globalThis.document = {};
vm.runInThisContext(fs.readFileSync('decks/kanji/static/card.js', 'utf8'), {
  filename: 'decks/kanji/static/card.js'
});

const data = JSON.parse(fs.readFileSync('decks/kanji/data/data_japanese.json', 'utf8'));
let examples = 0;
for (const record of Object.values(data)) {
  for (const items of [...Object.values(record.readings), ...Object.values(record.except)]) {
    for (const example of items) {
      examples += 1;
      if (window.KanjiCard.parseAnnotated(example.w) === null) {
        throw new Error(`card parser rejected ${JSON.stringify(example)}`);
      }
    }
  }
}
if (examples !== 11910) throw new Error(`unexpected example count: ${examples}`);
if (window.KanjiCard.groupOfKey('キ') !== 'on') throw new Error('Katakana must be on');
if (window.KanjiCard.groupOfKey('いのり') !== 'kun') throw new Error('Hiragana must be kun');
if (window.KanjiCard.groupOfKey('いのー') !== 'verb') throw new Error('ー must be verb');
if (window.KanjiCard.groupOfKey('') !== 'invalid') throw new Error('blank key must be invalid');
if (window.KanjiCard.groupOfKey('かなー') !== 'verb') throw new Error('Hiragana stem + ー must be verb');
for (const invalid of ['カー', 'ー', 'いーの', 'かなカ']) {
  if (window.KanjiCard.groupOfKey(invalid) !== 'invalid') {
    throw new Error(`${invalid} must be invalid`);
  }
}
if (window.KanjiCard.displayReading('セイ') !== 'セイ') {
  throw new Error('design card must preserve raw Katakana');
}

const synthetic = {
  readings: [
    { rawKey: 'うむー', examples: [] },
    { rawKey: 'セイ', examples: [] },
    { rawKey: 'なま', examples: [] },
    { rawKey: 'ショウ', examples: [] },
    { rawKey: 'き', examples: [] },
    { rawKey: 'はえー', examples: [] },
    { rawKey: 'ケイ', examples: [] }
  ],
  except: {
    やよい: [{ w: '弥生(やよい)', ko: '음력 3월' }],
    しばふ: [{ w: '芝生(しばふ)', ko: '잔디밭' }]
  }
};
const layout = window.KanjiCard.layoutReadingGroups(synthetic);
if (layout.map((group) => group.key).join(',') !== 'on,kun,verb,exc') {
  throw new Error(`wrong design group order: ${layout.map((group) => group.key)}`);
}
// 예외는 요미카타별로 나뉘지 않고 'X' 마커 하나 아래 모두 모인다.
const excGroup = layout.find((group) => group.key === 'exc');
if (excGroup.readings.length !== 1
    || excGroup.readings[0].rawKey !== window.KanjiCard.EXCEPTION_MARKER) {
  throw new Error('every exception must sit under the single X marker');
}
if (excGroup.readings[0].examples.map((example) => example.w).join('|')
    !== '芝生(しばふ)|弥生(やよい)') {
  throw new Error('X marker must carry every exception in ordering-rule order');
}
if (excGroup.readings[0].examples.map((example) => example._exceptKey).join('|')
    !== 'しばふ|やよい') {
  throw new Error('X marker examples must remember their own exception key');
}
const expectedKeys = {
  on: ['セイ', 'ショウ', 'ケイ'],
  kun: ['なま', 'き'],
  verb: ['うむー', 'はえー'],
  exc: ['X']
};
for (const group of layout) {
  if (group.readings.map((reading) => reading.rawKey).join('|') !== expectedKeys[group.key].join('|')) {
    throw new Error(`${group.key} lost stable source order`);
  }
  if (group.rows.some((row) => row.cols.length > 2)) throw new Error(`${group.key} row exceeds two columns`);
  const odd = group.readings.length % 2 === 1;
  if (group.rows.at(-1).filler !== odd) throw new Error(`${group.key} filler contract failed`);
}

const liveRecord = data['生'];
const liveRecordBeforeProjection = JSON.stringify(liveRecord);
const liveLayout = window.KanjiCard.layoutReadingGroups({
  readings: Object.entries(liveRecord.readings).map(([rawKey, values]) => ({
    rawKey,
    examples: values
  })),
  except: liveRecord.except
});
if (liveLayout.map((group) => group.key).join(',') !== 'on,kun,verb,exc') {
  throw new Error('生 must render on → kun → verb → exc');
}
if (liveLayout.map((group) => group.rows.length).join(',') !== '1,1,2,1') {
  throw new Error('生 must render 1/1/2/1 two-column rows after inflection grouping');
}
const liveSei = liveLayout.flatMap((group) => group.readings)
  .find((reading) => reading.rawKey === 'セイ');
// 芝生·弥生 는 備考 상호참조였으므로 이제 readings 에 실리지도 않는다.
// 남는 셋은 정렬 규칙(한자 길이 -> 뜻 길이 -> 후리가나 길이 -> 가나다)대로 온다.
if (liveSei.examples.map((example) => window.KanjiCard.plainSurface(example.w)).join('|')
    !== '発生|生活|先生') {
  throw new Error('生/セイ must list only its own examples in canonical order');
}
if (liveSei.examples.map((example) => example._sourceIndex).join(',') !== '0,1,2') {
  throw new Error('projected 生/セイ examples must retain canonical source indices');
}
const liveExceptions = liveLayout.find((group) => group.key === 'exc').readings;
// 실데이터의 뜻 길이는 '음력 3월'(5) < '잔디밭, 잔디'(8) 이므로 弥生 가 앞선다.
if (liveExceptions.length !== 1 || liveExceptions[0].rawKey !== 'X') {
  throw new Error('生 exceptions must collapse into one X marker');
}
if (liveExceptions.flatMap((reading) => reading.examples)
  .map((example) => window.KanjiCard.displayParts(example).surface).join('|') !== '弥生|芝生') {
  throw new Error('生 exception group must retain 弥生 and 芝生 exactly once');
}
if (JSON.stringify(liveRecord) !== liveRecordBeforeProjection) {
  throw new Error('display projection must never mutate canonical 生 data');
}

const rainVisible = window.KanjiCard.visibleRegularEntries(
  data['雨'].readings['ウ'], data['雨'].except
);
if (!rainVisible.some(({ example }) => {
  const parts = window.KanjiCard.displayParts(example);
  return parts.surface === '梅雨' && parts.reading === 'ばいう';
})) {
  throw new Error('ordinary 梅雨(ばいう) must survive exception projection');
}
if (rainVisible.some(({ example }) => window.KanjiCard.displayParts(example).reading === 'つゆ')) {
  throw new Error('exception 梅雨(つゆ) must not remain in regular readings');
}

const tenLayout = window.KanjiCard.layoutReadingGroups({
  readings: Object.entries(data['十'].readings).map(([rawKey, values]) => ({
    rawKey,
    examples: values
  })),
  except: data['十'].except
});
// 十/ジュウ 의 備考 는 「二十・二十歳（はたち）」 라는 付表 포인터뿐이었다.
// 그것을 걷어냈으므로 例 칸의 용례만 남고, はたち 는 except 로만 존재한다.
const tenJuu = tenLayout.flatMap((group) => group.readings)
  .find((reading) => reading.rawKey === 'ジュウ').examples;
if (tenJuu.map((example) => window.KanjiCard.plainSurface(example.w)).join('|')
    !== '十字架|十文字') {
  throw new Error('十/ジュウ must carry only its printed 例 column examples');
}
const tenExcept = tenLayout.find((group) => group.key === 'exc').readings[0];
const tenHatachi = tenExcept.examples
  .filter((example) => example._exceptKey === 'はたち')
  .map((example) => window.KanjiCard.plainSurface(example.w));
if (tenHatachi.join('|') !== '二十|二十歳') {
  throw new Error('十 must record 二十·二十歳 under the whole-word reading はたち');
}

// 付表 어휘는 except 에 실리고, 표기는 원문 그대로다(주석 괄호가 붙지 않는다).
// 그 전체 읽기는 except 의 키와 정확히 일치해야 한다.
for (const [character, word, expected] of [
  ['兄', '兄さん', 'にいさん'],
  ['最', '最寄り', 'もより'],
  ['青', '真っ青', 'まっさお']
]) {
  const example = (data[character].except[expected] || [])
    .find((item) => window.KanjiCard.plainSurface(item.w) === word);
  if (!example) {
    throw new Error(`${word} must live under ${character}.except[${expected}]`);
  }
  if (window.KanjiCard.displayParts(example).reading !== expected) {
    throw new Error(`${word} whole-word reading must resolve to ${expected}`);
  }
}

// 例 칸에 인쇄된 연탁 용례는 그대로 남아 printed 경로를 계속 태운다.
const rendaku = data['羽'].readings['は']
  .find((item) => window.KanjiCard.plainSurface(item.w) === '一羽（わ）');
if (!rendaku || !window.KanjiCard.displayParts(rendaku).printed) {
  throw new Error('printed rendaku examples from the 例 column must survive');
}

const invalidExample = { w: '壊れた(', ko: 'broken' };
if (window.KanjiCard.visibleRegularEntries([invalidExample], liveRecord.except).length !== 1) {
  throw new Error('invalid annotations must fail open instead of disappearing');
}

const identity = (surface, reading) => JSON.stringify([
  surface,
  [...reading].map((character) => {
    const point = character.codePointAt(0);
    return point >= 0x30a1 && point <= 0x30f6
      ? String.fromCodePoint(point - 0x60)
      : character;
  }).join('')
]);
let matchedRegularBranches = 0;
let shadowedRegularRows = 0;
let partialRegularRows = 0;
let visibleRegularRows = 0;
for (const record of Object.values(data)) {
  const exceptionIdentities = new Set();
  for (const items of Object.values(record.except)) {
    for (const example of items) {
      const analyzed = window.KanjiCard.analyzeBranches(example);
      if (!analyzed.valid) throw new Error('normalized exception annotation must analyze');
      for (const branch of analyzed.branches) {
        exceptionIdentities.add(identity(branch.surface, branch.localReading));
      }
    }
  }
  for (const items of Object.values(record.readings)) {
    visibleRegularRows += window.KanjiCard.visibleRegularEntries(items, record.except).length;
    for (const example of items) {
      const analyzed = window.KanjiCard.analyzeBranches(example);
      if (!analyzed.valid) throw new Error('normalized regular annotation must analyze');
      const matched = analyzed.branches.filter((branch) => [...branch.readingOptions]
        .some((reading) => exceptionIdentities.has(identity(branch.surface, reading)))).length;
      if (matched) {
        matchedRegularBranches += matched;
        shadowedRegularRows += 1;
        if (matched < analyzed.branches.length) partialRegularRows += 1;
      }
    }
  }
}
// 付表 상호참조를 備考 단계에서 걷어낸 뒤로 실데이터의 그림자 용례는 0 이 됐다.
// visibleRegularEntries 는 이제 방어선으로만 남는다 — 사람이 편집으로 같은
// 표기·읽기를 정규 용례와 예외에 동시에 만들면 그때 걸러 준다.
if (matchedRegularBranches !== 0 || shadowedRegularRows !== 0
    || partialRegularRows !== 0 || visibleRegularRows !== 11708) {
  throw new Error('production exception projection census changed unexpectedly');
}

const groupRank = new Map([['on', 0], ['kun', 1], ['verb', 2], ['exc', 3], ['invalid', 4]]);
for (const [character, record] of Object.entries(data)) {
  const note = {
    readings: Object.entries(record.readings).map(([rawKey, values]) => ({
      rawKey,
      examples: values
    })),
    except: record.except
  };
  const groups = window.KanjiCard.layoutReadingGroups(note);
  const ranks = groups.map((group) => groupRank.get(group.key));
  if (ranks.some((rank, index) => index > 0 && rank <= ranks[index - 1])) {
    throw new Error(`${character} design groups are not strictly ordered`);
  }
  // 예외는 키가 몇 개든 X 마커 한 칸으로 접힌다.  용례는 하나도 잃지 않는다.
  const expected = Object.keys(record.readings).length
    + (Object.keys(record.except).length ? 1 : 0);
  const actual = groups.reduce((sum, group) => sum + group.readings.length, 0);
  if (actual !== expected) throw new Error(`${character} lost a reading during layout`);
  const exceptCount = Object.values(record.except)
    .reduce((sum, values) => sum + values.length, 0);
  const laidOut = groups.filter((group) => group.key === 'exc')
    .reduce((sum, group) => sum
      + group.readings.reduce((inner, reading) => inner + reading.examples.length, 0), 0);
  if (laidOut !== exceptCount) throw new Error(`${character} lost an exception example`);
  for (const group of groups) {
    for (const row of group.rows) {
      if (row.cols.length < 1 || row.cols.length > 2) {
        throw new Error(`${character}/${group.key} has an invalid row width`);
      }
    }
    if (group.readings.some((reading) => reading.tone < 0 || reading.tone > 2)) {
      throw new Error(`${character}/${group.key} escaped the visible sample tones`);
    }
  }
}

const exactShades = [
  'oklch(0.620 0.115 82)',
  'oklch(0.705 0.071 82)',
  'oklch(0.790 0.044 82)'
];
exactShades.forEach((expected, index) => {
  if (window.KanjiCard.shade('on', index) !== expected) {
    throw new Error(`wrong on shade ${index}: ${window.KanjiCard.shade('on', index)}`);
  }
});
if (window.KanjiCard.shade('on', 3) !== exactShades[0]) {
  throw new Error('long production groups must repeat the visible sample shades');
}

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName;
    this.className = '';
    this.textContent = '';
    this.children = [];
    this.attributes = {};
    this.classList = {
      add: (...names) => {
        const current = new Set(this.className.split(/\s+/).filter(Boolean));
        names.forEach((name) => current.add(name));
        this.className = [...current].join(' ');
      }
    };
  }
  append(...children) { this.children.push(...children); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  /* 필기 캔버스가 부르는 것들.  그리기 자체는 여기서 검증하지 않는다. */
  getContext() {
    return new Proxy({}, { get: () => () => {} });
  }
  getBoundingClientRect() { return { left: 0, top: 0, width: 220, height: 220 }; }
  setPointerCapture() {}
}

class FakeFragment extends FakeElement {
  constructor() { super('#fragment'); }
}

globalThis.document.createElement = (tagName) => new FakeElement(tagName);
globalThis.document.createDocumentFragment = () => new FakeFragment();
globalThis.document.createTextNode = (text) => {
  const node = new FakeElement('#text');
  node.textContent = text;
  return node;
};
const hasClass = (element, name) => element.className.split(/\s+/).includes(name);
const descendants = (element, name) => {
  const found = [];
  for (const child of element.children) {
    if (!(child instanceof FakeElement)) continue;
    if (hasClass(child, name)) found.push(child);
    found.push(...descendants(child, name));
  }
  return found;
};

/* 편집기와 Anki 는 **같은 봉투**를 같은 noteFrom 에 넣는다.  편집기는 서버가
 * 계산해 준 derived 를 통째로 넘기고 Anki 는 덱이 추린 것만 넘기는데, 한자
 * 렌더러는 derived 를 읽지 않으므로 둘의 결과가 같아야 한다. */
const liveEnvelope = { key: '生', record: liveRecord, derived: {} };
const fromEditor = window.KanjiCard.noteFrom({
  ...liveEnvelope,
  derived: { tag_label: '소학교 1학년', reading_count: 9, annotation_warnings: 0 }
});
const noteOf生 = window.KanjiCard.noteFrom(liveEnvelope);
if (JSON.stringify(fromEditor) !== JSON.stringify(noteOf生)) {
  throw new Error('noteFrom must ignore anything the renderer does not read');
}
if (noteOf生.character !== '生' || noteOf生.readings.length
    !== Object.keys(liveRecord.readings).length) {
  throw new Error('noteFrom must carry the key and every reading of the record');
}
if (noteOf生.readings.find((row) => row.rawKey === 'セイ').group !== 'on') {
  throw new Error('noteFrom must label each reading with its own group');
}

const rendered = window.KanjiCard.render(noteOf生, { mode: 'reading-back' });
const renderedGroups = descendants(rendered, 'kc-reading-group');
if (renderedGroups.map((group) => group.className.match(/reading-group-(\w+)/)?.[1]).join(',')
    !== 'on,kun,verb,exc') {
  throw new Error('rendered DOM group order differs from the sample');
}
for (const row of descendants(rendered, 'kc-reading-row')) {
  if (row.children.length !== 2) throw new Error('every rendered reading row must keep two half-width columns');
}
for (const reading of descendants(rendered, 'kc-reading').filter((item) => !hasClass(item, 'reading-filler'))) {
  if (descendants(reading, 'reading-dot').length !== 1) throw new Error('reading marker missing');
  if (descendants(reading, 'reading-line').length !== 1) throw new Error('reading line missing');
  if (!/tone-[0-2]/.test(reading.className)) throw new Error('reading marker/line tone missing');
}
if (descendants(rendered, 'reading-label')[0].textContent !== 'セイ') {
  throw new Error('first rendered label must remain Katakana セイ');
}

const previewNote = noteOf生;
const readingFront = window.KanjiCard.render(previewNote, { mode: 'reading-front' });
const writingFront = window.KanjiCard.render(previewNote, { mode: 'writing-front' });
for (const name of ['kc-reading', 'word', 'reading-line', 'reveal-meaning']) {
  if (descendants(readingFront, name).length !== descendants(rendered, name).length) {
    throw new Error(`reading front/back must keep identical ${name} geometry`);
  }
  if (descendants(writingFront, name).length !== descendants(rendered, name).length) {
    throw new Error(`writing front/back must keep identical ${name} geometry`);
  }
}
// 쓰기 앞면은 정답 한자를 지우지 않고 가리기만 한다.  DOM 이 앞뒤로 동일해야
// 클래스 토글만으로 뒤집을 수 있고, 그래야 필기 캔버스가 살아남는다.
const writingBack = window.KanjiCard.render(previewNote, { mode: 'writing-back' });
const answerCount = (card) => descendants(card, 'answer-char').length;
if (answerCount(writingFront) === 0) {
  throw new Error('writing deck must mark every answer kanji');
}
if (answerCount(writingFront) !== answerCount(writingBack)) {
  throw new Error('writing front and back must share identical markup');
}
if (answerCount(readingFront) !== 0 || answerCount(rendered) !== 0) {
  throw new Error('reading deck must never mark answer kanji');
}
// 한자 원문 + 용례 속 모든 生 이 대상이다.
const seiOccurrences = Object.values(previewNote.readings)
  .reduce((sum, reading) => sum + reading.examples
    .reduce((inner, example) => inner
      + [...window.KanjiCard.plainSurface(example.w)].filter((c) => c === '生').length, 0), 0)
  + Object.values(previewNote.except)
    .reduce((sum, items) => sum + items
      .reduce((inner, example) => inner
      + [...window.KanjiCard.plainSurface(example.w)].filter((c) => c === '生').length, 0), 0)
  + 1;
if (answerCount(writingFront) !== seiOccurrences) {
  throw new Error(`writing deck must mark all ${seiOccurrences} answer kanji, got ${answerCount(writingFront)}`);
}
if (descendants(writingFront, 'writing-canvas').length !== 1) {
  throw new Error('writing deck must offer exactly one practice canvas');
}
if (descendants(readingFront, 'writing-canvas').length !== 0) {
  throw new Error('reading deck must not offer a practice canvas');
}
// 연습판은 부르는 쪽이 끌 수 있다.  꺼도 나머지는 그대로여야 한다.
const ankiWritingFront = window.KanjiCard.render(previewNote,
  { mode: 'writing-front', pad: false });
if (descendants(ankiWritingFront, 'writing-canvas').length !== 0) {
  throw new Error('pad:false must drop the practice canvas');
}
if (answerCount(ankiWritingFront) !== answerCount(writingFront)) {
  throw new Error('pad:false must not change what the writing front hides');
}

// 획은 카드 바깥에 남는다.  Anki 는 면이 바뀔 때 카드를 통째로 다시 그리므로,
// 앞면에서 쓴 것이 뒷면에 남으려면 스크립트 수명 바깥에 있어야 한다.
const kept = (character, options = {}) =>
  window.KanjiCard.keptStrokes({ character }, options);
const keep = (character, options = {}) =>
  window.KanjiCard.keepStrokes({ character }, options);

const BACK = { mode: 'writing-back' };
const FRONT = { mode: 'writing-front' };

if (kept('生', FRONT).length !== 0) {
  throw new Error('a fresh character must start with a blank pad');
}
keep('生')([[[1, 2], [3, 4]]]);
// 획은 앞면에서 뒷면으로만 건너간다.
if (kept('生', BACK).length !== 1) {
  throw new Error('a stroke drawn on the front must reach the back');
}
// 앞면으로 돌아오면 빈 판이다 — 아까 쓴 글씨가 남아 있으면 그것을 베끼게 된다.
if (kept('生', FRONT).length !== 0) {
  throw new Error('coming back to the front must clear the pad');
}
if (kept('生', BACK).length !== 0) {
  throw new Error('the front must clear the slot, not just its own view');
}
// 다른 한자로 넘어가면 그 한자의 판도 비어 있다.
keep('生')([[[1, 2], [3, 4]]]);
if (kept('今', BACK).length !== 0) {
  throw new Error('another character must not inherit the previous strokes');
}
// 부르는 쪽이 획을 관리하면(편집기) 그것이 우선한다.
const mine = [];
if (kept('生', { strokes: mine, mode: 'writing-front' }) !== mine) {
  throw new Error('an explicit strokes array must win over the kept slot');
}
const onStrokes = () => {};
if (keep('生', { onStrokes }) !== onStrokes) {
  throw new Error('an explicit onStrokes callback must win over the kept slot');
}
// 배열을 직접 들고 있는 쪽에는 아무것도 되쓰지 않는다 — 제자리 수정으로 이미 남는다.
keep('生', { strokes: mine })([[[9, 9], [8, 8]]]);
if (kept('生').length !== 0) {
  throw new Error('a caller-owned array must not spill into the kept slot');
}

// 뒷면도 연습판을 그대로 내놓는다 — 정답을 보면서 한 번 더 써 볼 수 있다.
keep('生')([[[5, 5], [6, 6]]]);
const restored = window.KanjiCard.render(previewNote, { mode: 'writing-back' });
if (descendants(restored, 'writing-canvas').length !== 1) {
  throw new Error('the writing back must still offer the practice canvas');
}
keep('生')([]);

// 이체자는 한자 옆 두 번째 줄에 붙는다.
const variantNote = { ...previewNote, variant: { 甦: '康熙字典体' } };
const withVariant = window.KanjiCard.render(variantNote, { mode: 'reading-back' });
if (descendants(withVariant, 'kc-variants').length !== 1
    || descendants(withVariant, 'kc-variant').length !== 1) {
  throw new Error('the header must carry the variant row beside the character');
}

// 후리가나는 한자 칸에 배정된다.  기본은 한 칸에 두 자이고, 넘치면 줄인다.
const cellsOf = (annotated) => window.KanjiCard.spellCells({ w: annotated });
const scaleOf = (kanji, reading) => window.KanjiCard.furiganaClass(kanji, reading);
if (cellsOf('空港(くうこう)').length !== 1) {
  throw new Error('空港 must occupy one kanji cell');
}
if (scaleOf(2, 4) !== '') throw new Error('空港 must use the default 1/2 scale exactly');
if (scaleOf(3, 4) !== '') throw new Error('生意気 must stay at the default scale with room left');
if (scaleOf(2, 5) !== ' fr-2-5') throw new Error('消滅 must shrink to 2/5');
if (scaleOf(1, 5) !== ' fr-1-5') throw new Error('承る must shrink to 1/5');
const ukeCells = cellsOf('承(うけたまわ)る');
if (ukeCells.length !== 2 || ukeCells[0].reading !== 'うけたまわ' || ukeCells[1].reading !== null) {
  throw new Error('okurigana must form its own cell without furigana');
}

/* --------------------------------------------------------------------------
 * 문법 렌더러 — 문형 하나가 카드 한 장이다.
 * -------------------------------------------------------------------------- */

vm.runInThisContext(fs.readFileSync('decks/bunpo/static/card.js', 'utf8'), {
  filename: 'decks/bunpo/static/card.js'
});

const bunpo = JSON.parse(
  fs.readFileSync('decks/bunpo/data/bunpo_korean.json', 'utf8'));
const [bunpoKey, bunpoRecord] = Object.entries(bunpo)[0];

/* 편집기는 서버의 derived 를 통째로, Anki 는 덱이 추린 것만 넘긴다.  문법
 * 렌더러가 derived 에서 읽는 것은 급수 하나뿐이므로 결과가 같아야 한다. */
const bunpoEnvelope = { key: bunpoKey, record: bunpoRecord, derived: { level: 'N1' } };
const bunpoNote = window.BunpoCard.noteFrom(bunpoEnvelope);
const bunpoFromEditor = window.BunpoCard.noteFrom({
  ...bunpoEnvelope,
  derived: { level: 'N1', examples: [], unmarked: 0, head: bunpoRecord.head }
});
if (JSON.stringify(bunpoNote) !== JSON.stringify(bunpoFromEditor)) {
  throw new Error('bunpo noteFrom must ignore anything the renderer does not read');
}
if (bunpoNote.head !== bunpoRecord.head || bunpoNote.level !== 'N1') {
  throw new Error('bunpo noteFrom must carry the headword and the level label');
}
if (bunpoNote.examples.length !== bunpoRecord.examples.length) {
  throw new Error('one card must carry every example of its grammar point');
}

const bunpoCard = window.BunpoCard.render(bunpoNote, { mode: 'reading-front' });
if (descendants(bunpoCard, 'bn-ex').length !== bunpoRecord.examples.length) {
  throw new Error('the card must draw one row per example');
}
if (descendants(bunpoCard, 'bn-grammar')[0].textContent !== bunpoRecord.head) {
  throw new Error('the card must show its grammar point');
}

/* 문법 구간은 `*` 한 쌍이 곧 데이터다.  split 한 번으로 갈라 강조한다. */
const marked = '愛(あい)*あっての*結(けっ)婚(こん)';
const [, span] = window.BunpoCard.splitMarked(marked);
if (span !== 'あっての') throw new Error('splitMarked must return the marked span');
const spanCard = window.BunpoCard.render(
  { head: 'あっての', examples: [{ marked, ja: marked.split('*').join(''), ko: '뜻' }] },
  { mode: 'reading-front' });
if (descendants(spanCard, 'bn-span').length !== 1) {
  throw new Error('the marked span must be highlighted exactly once');
}

/* 후리가나는 **한자 위에** 붙는다.  걸릴 한자가 없으면 루비를 만들지 않는다.
 *
 * 파이프라인은 별표가 덩이 가운데로 들어가지 못하게 막지만(`marking.groups`),
 * 사람이 편집기에서 예문을 고칠 때는 `後*(あと)` 같은 조각이 렌더러에 닿을 수
 * 있다.  그때 빈 <ruby> 를 만들면 읽기가 걸릴 글자 없이 허공에 뜨고 그 자리가
 * 벌어져, 문장 한가운데에 설명할 수 없는 틈이 생긴다.  글자 그대로 싣는 쪽이 옳다. */
const walk = (element, found = []) => {
  found.push(element);
  for (const child of element.children) {
    if (child instanceof FakeElement) walk(child, found);
  }
  return found;
};
const flatText = (element) => walk(element)
  .filter((node) => node.tagName === '#text').map((node) => node.textContent).join('');
const splitRuby = '祭(まつ)りの*後*(あと)、';
const splitCard = window.BunpoCard.render(
  { head: 'あとで',
    examples: [{ marked: splitRuby, ja: splitRuby.split('*').join(''), ko: '뜻' }] },
  { mode: 'reading-front' });
for (const ruby of walk(splitCard).filter((node) => node.tagName === 'ruby')) {
  const base = ruby.children
    .filter((child) => child.tagName === '#text')
    .map((child) => child.textContent).join('');
  if (!base) throw new Error('a ruby without a base must never be rendered');
}
if (!flatText(splitCard).includes('(あと)')) {
  throw new Error('a reading with nothing to attach to must stay as plain text');
}

/* 온전한 표기는 그대로 루비가 된다 — 위의 방어가 정상 경로를 막지 않는다. */
const wholeRuby = '祭(まつ)りの*後(あと)*、';
const wholeCard = window.BunpoCard.render(
  { head: 'あとで',
    examples: [{ marked: wholeRuby, ja: wholeRuby.split('*').join(''), ko: '뜻' }] },
  { mode: 'reading-front' });
const readings = walk(wholeCard).filter((node) => node.tagName === 'rt')
  .map((node) => node.textContent);
if (readings.join('|') !== 'まつ|あと') {
  throw new Error(`every kanji must keep its ruby: ${readings.join('|')}`);
}

/* 구간 미표시 경고는 편집기의 진단이다.  Anki 카드에는 띄우지 않는다. */
const unmarkedNote = { head: 'x', examples: [{ ja: 'あ', ko: '아' }] };
if (descendants(window.BunpoCard.render(unmarkedNote, {}), 'bn-unmarked').length !== 1) {
  throw new Error('the editor must warn about an unmarked example');
}
if (descendants(window.BunpoCard.render(unmarkedNote, { diagnostics: false }),
  'bn-unmarked').length !== 0) {
  throw new Error('diagnostics:false must drop the editor-only warning');
}

/* 카드 면은 클래스 하나로 갈린다 — 그래서 Anki 템플릿도 모드 문자열만 다르다. */
for (const mode of ['reading-front', 'reading-back', 'produce-front', 'produce-back']) {
  const card = window.BunpoCard.render(bunpoNote, { mode });
  if (!card.className.split(/\s+/).includes(mode)) {
    throw new Error(`the card element must carry its mode class: ${mode}`);
  }
  if (descendants(card, 'bn-ex').length !== descendants(bunpoCard, 'bn-ex').length) {
    throw new Error('every mode must keep identical markup — CSS does the hiding');
  }
}

process.stdout.write(`card parser/layout: ${examples} examples, X marker + furigana cells OK\n`);
/* --------------------------------------------------------------------------
 * Anki 카드 면 — 파이썬이 만든 템플릿이 **실제로 이 렌더러를 돌려** 카드를 그린다.
 *
 * 노트 타입 템플릿은 `shared/ankicard.py` 가 덱의 card.js 를 그대로 실어 만든다.
 * 그것이 Anki 안에서 정말 도는지는 돌려 봐야 안다 — 여기서 그 두 스크립트 블록을
 * 꺼내 가짜 DOM 위에서 실행하고, 편집기와 같은 카드가 나오는지 본다.
 * -------------------------------------------------------------------------- */

const faces = JSON.parse(execFileSync('python', ['tests/anki_faces.py'],
  { encoding: 'utf8', cwd: process.cwd() }));

class MountElement extends FakeElement {
  appendChild(child) { this.children.push(child); return child; }
}

for (const [deck, deckFaces] of Object.entries(faces)) {
  for (const [name, html] of Object.entries(deckFaces.templates)) {
    const scripts = [...html.matchAll(/<script>([\s\S]*?)<[/]script>/g)].map((m) => m[1]);
    if (scripts.length !== 2) {
      throw new Error(`${deck}/${name}: an Anki face must carry the renderer and the mount`);
    }
    const mount = new MountElement('div');
    const carrier = new FakeElement('div');
    carrier.textContent = deckFaces.data;
    const sandbox = {
      window: {},
      document: {
        getElementById: (id) => (id === 'sp-mount' ? mount
          : id === 'sp-data' ? carrier : null),
        createElement: (tag) => new FakeElement(tag),
        createDocumentFragment: () => new FakeFragment(),
        createTextNode: (text) => {
          const textNode = new FakeElement('#text');
          textNode.textContent = text;
          return textNode;
        }
      },
      atob: (value) => Buffer.from(value, 'base64').toString('binary'),
      Uint8Array,
      TextDecoder,
      JSON
    };
    const context = vm.createContext(sandbox);
    for (const code of scripts) {
      vm.runInContext(code, context, { filename: `${deck}/${name}` });
    }
    if (mount.children.length !== 1) {
      throw new Error(`${deck}/${name}: the Anki face drew nothing`);
    }
    const card = mount.children[0];
    const mode = html.match(/"mode":[ ]*"([^"]+)"/)[1];
    if (!hasClass(card, mode)) {
      throw new Error(`${deck}/${name}: the card must carry its mode class ${mode}`);
    }
    if (descendants(card, deckFaces.block).length === 0) {
      throw new Error(`${deck}/${name}: the Anki card body is empty`);
    }
    // 쓰기 카드는 **Anki 에서도** 손으로 써 볼 수 있어야 한다.  써 보지 않으면
    // 쓰기 연습이 아니다.  획은 카드를 넘기면 지워지지만 그것으로 족하다.
    const pads = descendants(card, 'writing-canvas').length;
    if (mode.startsWith('writing') !== (pads === 1)) {
      throw new Error(`${deck}/${name}: writing faces need exactly one practice canvas`
        + ` (mode ${mode}, found ${pads})`);
    }
  }
}

/* 앞면에 쓴 획이 뒷면에 남는가.
 *
 * Anki 는 면이 바뀔 때 카드를 통째로 다시 그린다 — **스크립트가 처음부터 다시 돈다.**
 * 그래서 앞면의 획이 뒷면에 남으려면 스크립트 수명 바깥에 있어야 한다.  여기서는
 * 페이지(window·sessionStorage)만 이어 두고 두 면을 따로 돌려 그것을 확인한다. */

class PadElement extends MountElement {
  /* 캔버스는 한 번 받은 그리기 맥락을 계속 쓴다.  새로 만들어 주면 무엇이 그려졌는지
   * 셀 수 없다. */
  getContext() {
    if (!this.painted) {
      const calls = [];
      this.painted = new Proxy({ calls }, {
        get: (_target, name) => (name === 'calls' ? calls
          : (...args) => { calls.push([name, ...args]); })
      });
    }
    return this.painted;
  }
  getBoundingClientRect() { return { left: 0, top: 0, width: 220, height: 220 }; }
  setPointerCapture() {}
}

const page = { window: {} };
const slots = new Map();
page.window.sessionStorage = {
  getItem: (key) => (slots.has(key) ? slots.get(key) : null),
  setItem: (key, value) => slots.set(key, String(value))
};

function drawFace(html, data) {
  const mount = new PadElement('div');
  const carrier = new PadElement('div');
  carrier.textContent = data;
  const sandbox = {
    window: page.window,
    document: {
      getElementById: (id) => (id === 'sp-mount' ? mount
        : id === 'sp-data' ? carrier : null),
      createElement: (tag) => new PadElement(tag),
      createDocumentFragment: () => new FakeFragment(),
      createTextNode: (text) => {
        const node = new PadElement('#text');
        node.textContent = text;
        return node;
      }
    },
    atob: (value) => Buffer.from(value, 'base64').toString('binary'),
    Uint8Array,
    TextDecoder,
    JSON
  };
  const context = vm.createContext(sandbox);
  for (const code of [...html.matchAll(/<script>([\s\S]*?)<[/]script>/g)].map((m) => m[1])) {
    vm.runInContext(code, context, { filename: 'face' });
  }
  return mount.children[0];
}

const segments = (card) => descendants(card, 'writing-canvas')[0]
  .getContext().calls.filter(([name]) => name === 'lineTo').length;

const kanjiFaces = faces['SP 한자'];
const ankiFront = drawFace(kanjiFaces.templates['쓰기 앞면'], kanjiFaces.data);
const pad = descendants(ankiFront, 'writing-canvas')[0];
if (!pad) throw new Error('the Anki writing front must offer a practice canvas');

// 한 획을 긋는다 — 누르고, 끌고, 뗀다.
pad.onpointerdown({ preventDefault() {}, stopPropagation() {}, pointerId: 1, clientX: 10, clientY: 10 });
pad.onpointermove({ clientX: 60, clientY: 70 });
pad.onpointermove({ clientX: 90, clientY: 120 });
pad.onpointerup({});
if (segments(ankiFront) === 0) throw new Error('the stroke must be painted as it is drawn');

// 뒷면: 스크립트가 처음부터 다시 돈다.  그래도 그 획이 다시 그려져야 한다.
const ankiBack = drawFace(kanjiFaces.templates['쓰기 뒷면'], kanjiFaces.data);
if (segments(ankiBack) === 0) {
  throw new Error('a stroke drawn on the front must survive the flip to the back');
}
// 다시 앞면으로 돌아오면(다시 보기) 빈 판이어야 한다 — 남아 있으면 베끼게 된다.
const againFront = drawFace(kanjiFaces.templates['쓰기 앞면'], kanjiFaces.data);
if (segments(againFront) !== 0) {
  throw new Error('coming back to the front must clear the pad');
}
// 그 뒤의 뒷면도 비어 있어야 한다 — 앞면이 칸을 비웠기 때문이다.
if (segments(drawFace(kanjiFaces.templates['쓰기 뒷면'], kanjiFaces.data)) !== 0) {
  throw new Error('the back must show this pass only, not an earlier attempt');
}
// 다른 한자로 넘어가도 빈 판이어야 연습이 된다.
const nextCard = drawFace(kanjiFaces.templates['쓰기 앞면'], kanjiFaces.next);
if (segments(nextCard) !== 0) {
  throw new Error('another character must start from a blank pad');
}

process.stdout.write(`anki faces: ${Object.values(faces)
  .reduce((sum, deck) => sum + Object.keys(deck.templates).length, 0)} card faces render from Data alone
`);

process.stdout.write('anki writing pad: a stroke reaches the back, the front always starts blank\n');
/* --------------------------------------------------------------------------
 * 토익 렌더러 — 낱말 하나와 그 뜻들이 카드 한 장이다.
 * -------------------------------------------------------------------------- */

vm.runInThisContext(fs.readFileSync('decks/toeic/static/card.js', 'utf8'), {
  filename: 'decks/toeic/static/card.js'
});

const toeicRecord = {
  list: 'ngsl',
  rank: 741,
  band: '1-1000',
  family: ['board', 'boards', 'boarded', 'boarding'],
  senses: [
    { ja: '取締役会(とりしまりやくかい)', pos: 'noun', gloss: '役員会', en: 'governing body', checked: 'jmdict',
      example: { en: 'The board approved the new travel policy last week.',
        ja: '取締役会(とりしまりやくかい)は先週(せんしゅう)、新(あたら)しい出張(しゅっちょう)規定(きてい)を承認(しょうにん)しました。' } },
    { ja: '搭乗(とうじょう)する', pos: 'verb', gloss: '乗り物に乗る', en: 'to get on', checked: 'jmdict',
      example: { en: 'Passengers may board the aircraft from the rear door.',
        ja: '乗客(じょうきゃく)は後方(こうほう)のドアから搭乗(とうじょう)できます。' } },
    { ja: 'ボード', pos: 'noun', gloss: '板', en: 'a flat piece', checked: 'phrase' }
  ]
};
const toeicNote = window.ToeicCard.noteFrom(
  { key: 'board', record: toeicRecord, derived: {} });

/* derived 에서 아무것도 읽지 않는다 — 낱말과 뜻은 레코드 하나로 충분하다. */
const toeicFromEditor = window.ToeicCard.noteFrom({
  key: 'board', record: toeicRecord,
  derived: { band_label: 'NGSL 1-1000', unverified: 1, senses: [] }
});
if (JSON.stringify(toeicNote) !== JSON.stringify(toeicFromEditor)) {
  throw new Error('toeic noteFrom must ignore anything the renderer does not read');
}
if (toeicNote.word !== 'board' || toeicNote.senses.length !== 3) {
  throw new Error('toeic noteFrom must carry the key and every sense');
}

const toeicCard = window.ToeicCard.render(toeicNote, { mode: 'reading-front' });
if (descendants(toeicCard, 'tc-sense').length !== 3) {
  throw new Error('the card must draw one row per sense');
}
if (descendants(toeicCard, 'tc-en-word')[0].textContent !== 'board') {
  throw new Error('the card must show the English word');
}
// 어족은 표제어를 빼고 보여 준다 — 표제어는 이미 위에 크게 있다.
if (descendants(toeicCard, 'tc-family')[0].textContent.includes('board,')) {
  throw new Error('the family row must not repeat the headword');
}
// 품사마다 마커 색이 다르다.  클래스로 갈린다.
const posClasses = descendants(toeicCard, 'tc-sense').map((row) => row.className);
if (!posClasses[0].includes('pos-noun') || !posClasses[1].includes('pos-verb')) {
  throw new Error('each sense must carry its part-of-speech class');
}
// 후리가나는 표기 안에 실려 루비가 된다.
if (descendants(toeicCard, 'tc-ja')[0].children.filter((c) => c.tagName === 'ruby').length !== 1) {
  throw new Error('an annotated Japanese form must be drawn as ruby');
}

/* 예문은 낱말 바로 아래 본문 자리에, 짧은 뜻풀이는 오른쪽 단에 놓인다. */
const firstSense = descendants(toeicCard, 'tc-sense')[0];
const mainColumn = descendants(firstSense, 'tc-main')[0];
const asideColumn = descendants(firstSense, 'tc-aside')[0];
if (!mainColumn || !asideColumn) throw new Error('a sense must have a main and an aside column');
if (descendants(mainColumn, 'tc-ja').length !== 1
    || descendants(mainColumn, 'tc-ex-en').length !== 1
    || descendants(mainColumn, 'tc-ex-ja').length !== 1) {
  throw new Error('the Japanese word and both example lines belong to the main column');
}
if (descendants(asideColumn, 'tc-gloss').length !== 1
    || descendants(asideColumn, 'tc-en').length !== 1) {
  throw new Error('both short glosses belong to the aside column');
}
if (descendants(asideColumn, 'tc-ex-en').length !== 0) {
  throw new Error('the aside column must not hold the example');
}
// 예문이 없는 뜻은 예문 줄 자체를 두지 않는다 — 반쪽을 두지 않는다.
const third = descendants(toeicCard, 'tc-sense')[2];
if (descendants(third, 'tc-example').length !== 0) {
  throw new Error('a sense with no example must not draw an empty example block');
}
// 일본어 예문의 후리가나도 루비가 된다.
if (descendants(mainColumn, 'tc-ex-ja')[0].children
  .filter((c) => c.tagName === 'ruby').length < 3) {
  throw new Error('the Japanese example must carry ruby for every annotated run');
}

/* 검증 등급 뱃지는 편집기의 진단이다.  Anki 카드에는 띄우지 않는다. */
if (descendants(window.ToeicCard.render(toeicNote, {}), 'tc-check').length !== 1) {
  throw new Error('the editor must flag a sense the dictionary could not check');
}
if (descendants(window.ToeicCard.render(toeicNote, { diagnostics: false }),
  'tc-check').length !== 0) {
  throw new Error('diagnostics:false must drop the editor-only badge');
}

/* 카드 면은 클래스 하나로 갈린다 — 그래서 Anki 템플릿도 모드 문자열만 다르다. */
for (const mode of ['reading-front', 'reading-back', 'spell-front', 'spell-back']) {
  const card = window.ToeicCard.render(toeicNote, { mode });
  if (!card.className.split(/\s+/).includes(mode)) {
    throw new Error(`the card element must carry its mode class: ${mode}`);
  }
  if (descendants(card, 'tc-sense').length !== 3) {
    throw new Error('every mode must keep identical markup — CSS does the hiding');
  }
}

/* --------------------------------------------------------------------------
 * 예문 스위치 — **카드 하나에서 누르면 모든 카드에 걸린다.**
 *
 * Anki 는 카드를 넘길 때마다 렌더러를 처음부터 다시 돌리므로, 고른 값은 스크립트
 * 바깥(저장소)에 남아야 다음 카드가 이어받는다.  여기서 그 왕복을 실제로 해 본다 —
 * 한 카드에서 끄고, **렌더러를 다시 돌려** 다음 카드를 그리고, 꺼진 채로 나오는지.
 * -------------------------------------------------------------------------- */

const fakeStore = () => {
  const slots = new Map();
  return {
    getItem: (key) => (slots.has(key) ? slots.get(key) : null),
    setItem: (key, value) => slots.set(key, String(value))
  };
};
globalThis.window.localStorage = fakeStore();
delete globalThis.window.__toeicExamples;

const switchOf = (card) => descendants(card, 'tc-switch')[0];
const classesOf = (card) => card.className.split(/\s+/);

/* 기본값은 덱이 정한다 — 저장된 것이 없을 때만 쓰인다. */
const byDefault = window.ToeicCard.render(toeicNote, { mode: 'reading-back' });
if (!classesOf(byDefault).includes('examples-on')) {
  throw new Error('with nothing stored the card must follow the deck default');
}
if (!switchOf(byDefault)) throw new Error('every card must carry the switch');
if (window.ToeicCard.render(toeicNote, { examples: false })
  .className.split(/\s+/).includes('examples-on')) {
  throw new Error('examples:false must be the default when nothing is stored');
}

/* 한 카드에서 끈다. */
switchOf(byDefault).onclick({ stopPropagation() {} });
if (!classesOf(byDefault).includes('examples-off')) {
  throw new Error('pressing the switch must turn this card off at once');
}
if (switchOf(byDefault).textContent !== '예문 OFF') {
  throw new Error('the switch must say what it is now');
}

/* **다음 카드** — 렌더러를 다시 돌려도 꺼진 채로 나와야 한다.  두 방향 모두. */
for (const mode of ['reading-front', 'reading-back', 'spell-front', 'spell-back']) {
  const next = window.ToeicCard.render(toeicNote, { mode });
  if (!classesOf(next).includes('examples-off')) {
    throw new Error(`the switch must carry over to the next card: ${mode}`);
  }
  if (descendants(next, 'tc-example').length !== 2) {
    throw new Error('the DOM must stay identical — CSS does the hiding');
  }
}

/* 다시 켜면 되돌아온다. */
const off = window.ToeicCard.render(toeicNote, { mode: 'spell-back' });
switchOf(off).onclick({ stopPropagation() {} });
if (!classesOf(window.ToeicCard.render(toeicNote, {})).includes('examples-on')) {
  throw new Error('turning the switch back on must carry over too');
}

/* 저장소가 막혀 있어도 카드는 그려지고, 그 화면 안에서는 스위치가 듣는다. */
const blocked = {
  getItem() { throw new Error('blocked'); },
  setItem() { throw new Error('blocked'); }
};
globalThis.window.localStorage = blocked;
globalThis.window.sessionStorage = blocked;
delete globalThis.window.__toeicExamples;
const noStore = window.ToeicCard.render(toeicNote, { mode: 'reading-back' });
if (!classesOf(noStore).includes('examples-on')) {
  throw new Error('a blocked store must fall back to the deck default, not crash');
}
switchOf(noStore).onclick({ stopPropagation() {} });
if (!classesOf(window.ToeicCard.render(toeicNote, {})).includes('examples-off')) {
  throw new Error('with no store the switch must still hold for this page');
}
delete globalThis.window.localStorage;
delete globalThis.window.sessionStorage;
delete globalThis.window.__toeicExamples;

/* 뜻이 없는 낱말도 카드가 되기는 해야 한다.  빈 화면 대신 그렇다고 말한다. */
const barren = window.ToeicCard.render(
  window.ToeicCard.noteFrom({ key: 'x', record: { senses: [] } }), {});
if (descendants(barren, 'tc-empty').length !== 1) {
  throw new Error('a word with no sense must say so rather than draw nothing');
}

process.stdout.write('toeic switch: one press carries to the next card, both directions\n');
process.stdout.write(`toeic card: ${toeicNote.senses.length} senses on one card, `
  + `example in the main column, glosses in the aside, modes OK\n`);

process.stdout.write(`bunpo card: ${bunpoNote.examples.length} examples on one card, span + modes OK\n`);
