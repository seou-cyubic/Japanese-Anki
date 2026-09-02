'use strict';

/* The current-schema renderer uses the visual grammar from design_sample:
 * stable type groups, two readings per row, and one colored marker rail for
 * every reading. It never rewrites the native JSON order or raw keys. */

(() => {
  const GROUP_ORDER = ['on', 'kun', 'verb', 'exc', 'invalid'];
  const GROUP_LABELS = {
    on: '음독',
    kun: '훈독',
    verb: '동사 활용',
    exc: '특례',
    invalid: '미완성 읽기'
  };
  const HUES = {
    on: { l: 0.62, c: 0.115, h: 82 },
    kun: { l: 0.56, c: 0.085, h: 152 },
    verb: { l: 0.54, c: 0.095, h: 248 },
    exc: { l: 0.54, c: 0.125, h: 26 },
    invalid: { l: 0.52, c: 0.16, h: 26 }
  };
  const VISIBLE_SHADE_COUNT = 3;
  /* 모든 예외는 요미카타를 가리지 않고 이 마커 하나 아래 모인다. */
  const EXCEPTION_MARKER = 'X';
  const WRITING_PAD_SIZE = 220;

  const node = (tag, cls, text) => {
    const value = document.createElement(tag);
    if (cls) value.className = cls;
    if (text !== undefined) value.textContent = text;
    return value;
  };

  /* 쓰기 덱의 앞면은 '정답 한자' 를 가린다 — 카드의 한자 원문과 그 이체자다.
   * 글자를 지우는 대신 칸만 남기므로(visibility) 폭이 '　' 와 똑같이 유지되고,
   * 앞뒤 전환은 클래스 토글만으로 끝나 필기 캔버스가 살아남는다. */
  const answerSet = (note) =>
    new Set([note.character, ...Object.keys(note.variant || {})]);

  const answerText = (text, options = {}) => {
    const fragment = document.createDocumentFragment();
    const answers = options.answers;
    if (!answers || !answers.size) {
      fragment.append(document.createTextNode(text));
      return fragment;
    }
    let plain = '';
    for (const character of [...text]) {
      if (answers.has(character)) {
        if (plain) {
          fragment.append(document.createTextNode(plain));
          plain = '';
        }
        fragment.append(node('span', 'answer-char', character));
      } else {
        plain += character;
      }
    }
    if (plain) fragment.append(document.createTextNode(plain));
    return fragment;
  };

  const codepoint = (character) => character.codePointAt(0);
  const isRun = (character) => {
    const value = codepoint(character);
    return (value >= 0x2e80 && value <= 0x2eff)
      || (value >= 0x3400 && value <= 0x4dbf)
      || (value >= 0x4e00 && value <= 0x9fff)
      || (value >= 0xf900 && value <= 0xfaff)
      || (value >= 0x20000 && value <= 0x2ffff)
      || character === '々' || character === '〆';
  };
  const isKana = (character) => {
    const value = codepoint(character);
    return (value >= 0x3041 && value <= 0x309f)
      || (value >= 0x30a1 && value <= 0x30fa)
      || value === 0x30fc;
  };

  function parseAnnotation(word, annotated) {
    if (typeof word !== 'string' || typeof annotated !== 'string' || !annotated) return null;
    const chars = [...annotated];
    const segments = [];
    const reconstructed = [];
    const allReading = [];
    let index = 0;
    while (index < chars.length) {
      if (isRun(chars[index])) {
        let end = index;
        while (end < chars.length && isRun(chars[end])) end += 1;
        const surface = chars.slice(index, end).join('');
        const opening = chars[end];
        if (opening !== '(' && opening !== '（') return null;
        const closing = opening === '(' ? ')' : '）';
        let closeAt = end + 1;
        while (closeAt < chars.length && chars[closeAt] !== closing) closeAt += 1;
        if (closeAt >= chars.length) return null;
        const reading = chars.slice(end + 1, closeAt).join('');
        if (!reading || ![...reading].every(isKana)) return null;
        const source = opening === '(' ? 'generated' : 'printed';
        segments.push({ surface, reading, source });
        allReading.push(reading);
        reconstructed.push(source === 'generated'
          ? surface : `${surface}（${reading}）`);
        index = closeAt + 1;
        continue;
      }
      let end = index + 1;
      while (end < chars.length && !isRun(chars[end])) end += 1;
      const surface = chars.slice(index, end).join('');
      segments.push({ surface, reading: null, source: 'literal' });
      reconstructed.push(surface);
      for (const character of surface) if (isKana(character)) allReading.push(character);
      index = end;
    }
    if (reconstructed.join('') !== word) return null;
    return { segments, all: allReading.join('') };
  }

  const groupOfKey = (rawKey) => {
    if (typeof rawKey !== 'string' || !rawKey) return 'invalid';
    if (rawKey.includes('ー')) {
      const stem = rawKey.endsWith('ー') ? rawKey.slice(0, -1) : '';
      const hiraganaStem = stem && [...stem].every((character) => {
        const value = codepoint(character);
        return value >= 0x3041 && value <= 0x309f;
      });
      return hiraganaStem ? 'verb' : 'invalid';
    }
    if ([...rawKey].every((character) => {
      const value = codepoint(character);
      return value >= 0x30a1 && value <= 0x30fa;
    })) return 'on';
    if ([...rawKey].every((character) => {
      const value = codepoint(character);
      return value >= 0x3041 && value <= 0x309f;
    })) return 'kun';
    return 'invalid';
  };

  /* design_sample keeps Katakana readings as Katakana. */
  const displayReading = (rawKey) => rawKey;

  /* 용례의 뜻을 **뜻 하나씩**으로 가른다.  가르는 것은 줄바꿈 하나뿐이다 —
   * 쉼표와 가운뎃점은 한 뜻 안의 글자다(`decks/kanji/model.py` 의 `senses`). */
  const senses = (korean) => String(korean || '')
    .split('\n').map((line) => line.trim()).filter(Boolean);

  /* 후리가나는 표기 안에 실린다.  반각 (…) 만 생성분이므로 그것만 걷으면 원 표기다.
   * 전각 （…） 는 원전 인쇄분이라 표기의 일부로 남는다. */
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

  const parseAnnotated = (annotated) => parseAnnotation(plainSurface(annotated), annotated);

  const shadeStep = (index) => {
    const numeric = Number.isFinite(index) ? Math.max(0, Math.floor(index)) : 0;
    /* The sample defines three visible shades. Production has as many as eight
     * readings in one group, so repeat those shades instead of producing L>1. */
    return numeric % VISIBLE_SHADE_COUNT;
  };

  const shade = (group, index = 0) => {
    const base = HUES[group] || HUES.invalid;
    const step = shadeStep(index);
    return `oklch(${(base.l + 0.085 * step).toFixed(3)} ${(base.c * Math.pow(0.62, step)).toFixed(3)} ${base.h})`;
  };

  const toneClass = (index) => `tone-${shadeStep(index)}`;

  const toHiraganaExact = (value) => [...value].map((character) => {
    const point = codepoint(character);
    return point >= 0x30a1 && point <= 0x30f6
      ? String.fromCodePoint(point - 0x60)
      : character;
  }).join('');

  const branchIdentity = (surface, reading) => JSON.stringify([
    surface,
    toHiraganaExact(reading)
  ]);

  function analyzeBranches(example) {
    const parsed = parseAnnotated(example.w);
    if (!parsed) return { valid: false, branches: [] };

    const branches = [];
    let current = null;
    const reset = () => {
      current = {
        surface: '',
        localReading: '',
        printedCandidates: [],
        trailingPrinted: null
      };
    };
    const finish = () => {
      const localReading = toHiraganaExact(current.localReading);
      if (!current.surface || !localReading) return false;
      const candidates = current.printedCandidates.map(toHiraganaExact);
      const readingOptions = new Set([localReading, ...candidates]);
      let reading = localReading;
      if (current.trailingPrinted) {
        const candidate = toHiraganaExact(current.trailingPrinted.reading);
        const prefix = toHiraganaExact(current.trailingPrinted.prefix);
        if (!prefix || candidate.startsWith(prefix)) reading = candidate;
      }
      branches.push({
        surface: current.surface,
        localReading,
        reading,
        readingOptions,
        printed: candidates.length > 0
      });
      reset();
      return true;
    };
    reset();

    for (const segment of parsed.segments) {
      if (segment.reading !== null) {
        current.trailingPrinted = null;
        current.surface += segment.surface;
        const prefix = current.localReading;
        current.localReading += segment.reading;
        if (segment.source === 'printed') {
          current.printedCandidates.push(segment.reading);
          current.trailingPrinted = { reading: segment.reading, prefix };
        }
        continue;
      }

      const literal = [...segment.surface];
      for (let index = 0; index < literal.length;) {
        const character = literal[index];
        if (character === '（') {
          let closeAt = index + 1;
          while (closeAt < literal.length && literal[closeAt] !== '）') closeAt += 1;
          if (closeAt >= literal.length) return { valid: false, branches: [] };
          const reading = literal.slice(index + 1, closeAt).join('');
          if (!reading || ![...reading].every((item) => isKana(item) || item === '・')) {
            return { valid: false, branches: [] };
          }
          current.printedCandidates.push(reading);
          current.trailingPrinted = { reading, prefix: current.localReading };
          index = closeAt + 1;
          continue;
        }
        if (character === '・') {
          if (!finish()) return { valid: false, branches: [] };
          index += 1;
          continue;
        }
        current.trailingPrinted = null;
        current.surface += character;
        if (isKana(character)) current.localReading += character;
        index += 1;
      }
    }
    if (!finish()) return { valid: false, branches: [] };
    return { valid: true, branches };
  }

  function displayParts(example) {
    if (example._display) {
      return {
        valid: true,
        surface: example._display.surface,
        reading: example._display.reading,
        printed: false
      };
    }
    const analyzed = analyzeBranches(example);
    if (!analyzed.valid) {
      return {
        valid: false,
        surface: plainSurface(example.w) || '(빈 표기)',
        reading: '',
        printed: false
      };
    }
    return {
      valid: true,
      surface: analyzed.branches.map((branch) => branch.surface).join('・'),
      reading: analyzed.branches.map((branch) => branch.reading).join('・'),
      printed: analyzed.branches.some((branch) => branch.printed)
    };
  }

  function exceptionIdentitySet(exceptions) {
    const identities = new Set();
    for (const items of Object.values(exceptions || {})) {
      for (const example of items || []) {
        const analyzed = analyzeBranches(example);
        if (!analyzed.valid) continue;
        for (const branch of analyzed.branches) {
          identities.add(branchIdentity(branch.surface, branch.localReading));
        }
      }
    }
    return identities;
  }

  function visibleRegularEntries(examples, exceptions) {
    const identities = exceptionIdentitySet(exceptions);
    const visible = [];
    (examples || []).forEach((example, sourceIndex) => {
      const analyzed = analyzeBranches(example);
      if (!analyzed.valid) {
        visible.push({ example, sourceIndex });
        return;
      }
      const kept = analyzed.branches.filter((branch) => ![...branch.readingOptions]
        .some((reading) => identities.has(branchIdentity(branch.surface, reading))));
      if (kept.length === analyzed.branches.length) {
        visible.push({ example, sourceIndex });
        return;
      }
      if (!kept.length) return;
      visible.push({
        example: {
          ...example,
          _display: {
            surface: kept.map((branch) => branch.surface).join('・'),
            reading: kept.map((branch) => branch.reading).join('・')
          }
        },
        sourceIndex
      });
    });
    return visible;
  }

  function visibleRegularExamples(examples, exceptions) {
    return visibleRegularEntries(examples, exceptions).map(({ example }) => example);
  }

  /* pipeline/ordering.py 와 같은 규칙: 한자 길이 -> 뜻 길이 -> 후리가나 길이 ->
   * 뜻 가나다순.  X 마커는 여러 예외 키를 한 줄로 합치므로 여기서 다시 세운다. */
  function furiganaLength(example) {
    const parsed = parseAnnotated(example.w);
    if (parsed) return [...parsed.all].length;
    return [...plainSurface(example.w || '')].length;
  }

  function sortExamples(examples) {
    return [...examples].sort((left, right) => {
      /* 뜻이 여럿인 용례가 있으므로 견주는 것은 **첫 뜻**이다.  뜻이 둘이라는 이유로
       * 뒤로 밀리면 순서가 뜻의 개수를 따라가 버린다 — `pipeline/ordering.py` 와 같다. */
      const leftKo = senses(left.ko)[0] || '';
      const rightKo = senses(right.ko)[0] || '';
      return [...plainSurface(left.w || '')].length
          - [...plainSurface(right.w || '')].length
        || [...leftKo].length - [...rightKo].length
        || furiganaLength(left) - furiganaLength(right)
        || (leftKo < rightKo ? -1 : leftKo > rightKo ? 1 : 0);
    });
  }

  function layoutReadingGroups(note) {
    const buckets = Object.fromEntries(GROUP_ORDER.map((group) => [group, []]));
    for (const reading of note.readings || []) {
      const inferred = reading.group || groupOfKey(reading.rawKey);
      const group = GROUP_ORDER.includes(inferred) && inferred !== 'exc' ? inferred : 'invalid';
      const examples = visibleRegularEntries(reading.examples, note.except)
        .map(({ example, sourceIndex }) => ({ ...example, _sourceIndex: sourceIndex }));
      buckets[group].push({ ...reading, examples, group, exception: false });
    }
    /* 예외는 요미카타별로 흩어지지 않고 'X' 마커 하나 아래 모인다.  편집을 위해
     * 각 용례는 자기가 원래 속한 예외 키와 그 안에서의 위치를 지고 다닌다. */
    const exceptions = [];
    for (const [rawKey, examples] of Object.entries(note.except || {})) {
      (examples || []).forEach((example, sourceIndex) => {
        exceptions.push({ ...example, _exceptKey: rawKey, _sourceIndex: sourceIndex });
      });
    }
    if (exceptions.length) {
      buckets.exc.push({
        rawKey: EXCEPTION_MARKER,
        examples: sortExamples(exceptions),
        group: 'exc',
        exception: true
      });
    }

    const groups = [];
    for (const group of GROUP_ORDER) {
      const readings = buckets[group].map((reading, index) => ({
        ...reading,
        tone: shadeStep(index)
      }));
      if (!readings.length) continue;
      const rows = [];
      for (let index = 0; index < readings.length; index += 2) {
        const cols = readings.slice(index, index + 2);
        rows.push({ cols, filler: cols.length === 1 });
      }
      groups.push({ key: group, label: GROUP_LABELS[group], readings, rows });
    }
    return groups;
  }

  function koreanFlat(korean) {
    const seen = new Set();
    const values = [];
    for (const readings of Object.values(korean || {})) {
      for (const reading of readings) {
        if (!seen.has(reading)) {
          seen.add(reading);
          values.push(reading);
        }
      }
    }
    return values;
  }

  /* 한자 원문 오른쪽에 작은 글씨로 두 줄이 붙는다.
   *   ★★ ☆☆☆☆   ☆ = 한국어 음훈
   *   ★★ ○○○○   ○ = 이체자                       */
  function previewHeader(note, options = {}) {
    const head = node('header', 'kc-head');
    const character = node('div', 'kc-character');
    character.append(answerText(note.character, options));
    head.append(character);

    const side = node('div', 'kc-side');
    side.append(node('div', 'kc-korean reveal-korean',
      koreanFlat(note.korean).join(' · ') || '훈음 없음'));

    const variants = node('div', 'kc-variants reveal-korean');
    const entries = Object.entries(note.variant || {});
    if (entries.length) {
      for (const [variant, label] of entries) {
        const chip = node('span', 'kc-variant');
        chip.append(answerText(variant, options));
        chip.append(node('span', 'kc-variant-label', label));
        variants.append(chip);
      }
    } else {
      variants.append(node('span', 'kc-variant none', '이체자 없음'));
    }
    side.append(variants);
    head.append(side);
    return head;
  }

  /* 후리가나는 반드시 한자 칸 안에 들어간다.  기본 크기는 한자 한 칸에 후리가나
   * 두 자(비율 1/2)이고 가운데 정렬이다.  후리가나가 그보다 많으면 칸에 정확히
   * 들어맞도록 줄인다 — 한자 k 자, 후리가나 m 자일 때 배율은 min(1/2, k/m).
   * CSP 가 인라인 스타일을 막으므로 배율은 card.css 의 fr-k-m 클래스가 낸다.
   * 두 줄 모두 같은 letter-spacing 을 쓰므로 자간은 양변에서 약분되어 폭이
   * 정확히 일치한다. */
  const FURIGANA_MAX_RUN = 6;
  const FURIGANA_MAX_READING = 20;

  const furiganaClass = (kanjiCount, readingCount) => {
    if (!kanjiCount || !readingCount) return '';
    if (readingCount <= kanjiCount * 2) return '';          /* 기본값으로 충분 */
    const run = Math.min(kanjiCount, FURIGANA_MAX_RUN);
    const reading = Math.min(readingCount, FURIGANA_MAX_READING);
    return ` fr-${run}-${reading}`;
  };

  /* 주석을 [한자칸 | 가나] 로 쪼갠다.  한자칸만 후리가나를 인다. */
  function spellCells(example) {
    if (example._display) return null;
    const parsed = parseAnnotated(example.w);
    if (!parsed) return null;
    const cells = [];
    for (const segment of parsed.segments) {
      if (segment.reading !== null) {
        cells.push({ surface: segment.surface, reading: segment.reading });
        continue;
      }
      /* 리터럴 안의 （よみ） 는 앞선 한자칸의 인쇄 읽기다. */
      const pieces = segment.surface.split(/（([^）]*)）/);
      pieces.forEach((piece, index) => {
        if (!piece) return;
        if (index % 2 === 1) {
          const previous = cells[cells.length - 1];
          if (previous && previous.reading !== null) previous.reading = piece;
          return;
        }
        cells.push({ surface: piece, reading: null });
      });
    }
    return cells.length ? cells : null;
  }

  function previewSpell(example, options = {}) {
    const parts = displayParts(example);
    const cells = spellCells(example);
    const box = node('div', `example-spell${parts.valid ? '' : ' invalid-annotation'}`);
    box.setAttribute('aria-label', `${parts.surface} ${parts.reading || ''}`.trim());

    if (!cells) {
      /* 주석이 깨졌거나 예외로 가려진 표기다.  칸 배정 없이 그대로 보인다. */
      const plain = node('div', 'fseg fseg-plain');
      plain.append(node('div', 'fseg-furi reveal-furigana', parts.reading));
      const word = node('div', 'fseg-word');
      word.append(answerText(parts.surface, options));
      plain.append(word);
      box.append(plain);
      return box;
    }

    for (const cell of cells) {
      const kanjiCount = [...cell.surface].length;
      const readingCount = cell.reading ? [...cell.reading].length : 0;
      const segment = node('div',
        `fseg${cell.reading ? furiganaClass(kanjiCount, readingCount) : ' fseg-kana'}`);
      segment.append(node('div', 'fseg-furi reveal-furigana', cell.reading || ''));
      const word = node('div', 'fseg-word');
      word.append(answerText(cell.surface, options));
      segment.append(word);
      box.append(segment);
    }
    return box;
  }

  /* 뜻이 여럿인 용례는 **앞면에서도** 그 사실이 보여야 한다.
   *
   * 뜻을 갈라 놓고 뒷면에만 번호를 붙이면, 앞면에서는 뜻이 하나인 용례와 구별되지
   * 않아 '무엇을 몇 개 떠올려야 하는가' 를 알 수 없다.  그래서 개수만 용례 옆에
   * 작게 붙인다 — **`reveal-` 접두사를 붙이지 않는다.**  그 접두사가 붙은 것은
   * 앞면에서 `opacity: 0` 이 되는 정답 쪽이고(card.css), 이 숫자는 정답이 아니라
   * 문제의 일부다. */
  function senseCount(count) {
    const badge = node('span', 'sense-count', String(count));
    badge.setAttribute('aria-label', `뜻 ${count}개`);
    return badge;
  }

  /* 뒷면의 뜻.  하나면 그대로, 여럿이면 번호를 붙여 줄마다 나눈다. */
  function meaningBlock(lines) {
    const box = node('div', 'meaning reveal-meaning');
    if (lines.length <= 1) {
      box.textContent = lines[0] || '';
      return box;
    }
    lines.forEach((line, index) => {
      const row = node('div', 'meaning-sense');
      row.append(node('span', 'sense-no', `${index + 1}.`));
      row.append(node('span', 'sense-text', line));
      box.append(row);
    });
    return box;
  }

  function previewExample(example, options) {
    const word = node('div', 'word');
    const lines = senses(example.ko);
    const spell = previewSpell(example, options);
    if (lines.length > 1) spell.append(senseCount(lines.length));
    word.append(spell);
    if (options.revealMeanings) {
      word.append(meaningBlock(lines));
    }
    return word;
  }

  function readingColumn(reading, options) {
    const section = node(
      'section',
      `kc-reading group-${reading.group} ${toneClass(reading.tone)}`
    );
    const title = node('div', 'kc-reading-title');
    title.append(node('span', 'reading-dot', '●'));
    title.append(node('span', 'reading-label reveal-reading',
      displayReading(reading.rawKey)));
    title.append(node('span', 'sr-only', GROUP_LABELS[reading.group]));
    section.append(title);

    const body = node('div', 'reading-body');
    const lineWrap = node('div', 'reading-line-wrap');
    lineWrap.append(node('div', 'reading-line'));
    body.append(lineWrap);
    const words = node('div', 'words');
    for (const example of reading.examples) {
      words.append(previewExample(example, options));
    }
    body.append(words);
    section.append(body);
    return section;
  }

  function readingGrid(note, options = {}) {
    const grid = node('div', 'kc-readings');
    for (const group of layoutReadingGroups(note)) {
      const groupNode = node('section', `kc-reading-group reading-group-${group.key}`);
      groupNode.setAttribute('aria-label', group.label);
      for (const row of group.rows) {
        const rowNode = node('div', 'kc-reading-row');
        for (const reading of row.cols) {
          rowNode.append(readingColumn(reading, options));
        }
        if (row.filler) {
          const filler = node('div', 'kc-reading reading-filler');
          filler.setAttribute('aria-hidden', 'true');
          rowNode.append(filler);
        }
        groupNode.append(rowNode);
      }
      grid.append(groupNode);
    }
    return grid;
  }

  /* 읽기 덱은 요미가나·뜻·훈음을 가리고, 쓰기 덱은 정답 한자를 가린다.  두
   * 경우 모두 가리는 일은 CSS 가 하므로 앞뒤 전환에 DOM 을 다시 만들지 않는다. */
  const WRITING_MODES = new Set(['writing-front', 'writing-back']);

  /* 레코드 하나를 카드가 읽는 모양으로.  **편집기와 Anki 가 같은 이 함수를 쓴다.**
   *
   * 편집기는 사람이 고치는 중인 레코드를, Anki 는 노트의 Data 필드에서 푼 레코드를
   * 넣는다.  둘 다 `{key, record, derived}` 라는 같은 봉투이므로 같은 카드가 나온다.
   * 한자 카드가 `derived` 에서 읽는 것은 없다 — 요미카타의 갈래는 키만 보면 알 수
   * 있으므로(groupOfKey) 레코드 하나로 충분하다.
   *
   * 아직 키가 비어 있는 편집 중인 줄은 갈래를 알 수 없다.  그 한 줄에 한해
   * 편집기가 고르고 있는 갈래를 `draftReadingGroup` 으로 넘긴다. */
  function noteFrom(envelope, extra = {}) {
    const record = (envelope && envelope.record) || {};
    const readings = record.readings || {};
    return {
      character: (envelope && envelope.key) || '',
      korean: record.korean || {},
      variant: record.variant || {},
      except: record.except || {},
      note: record.note || [],
      readings: Object.keys(readings).map((rawKey) => ({
        rawKey,
        examples: readings[rawKey],
        group: rawKey === '' ? (extra.draftReadingGroup || null) : groupOfKey(rawKey)
      }))
    };
  }

  /* 常用漢字表 본표의 **備考 칸**.
   *
   * 표의 다른 어디에도 없는 읽기가 여기 들어 있다 — `観音` 을 `カンノン` 으로 읽는다는
   * 사실은 備考 에만 적혀 있다.  용례가 아니므로 요미카타 칸에 섞지 않고, 카드 아래에
   * 따로 한 줄씩 놓는다(`decks/kanji/pipeline/notes.py`).
   *
   * 정답 쪽이므로 `reveal-` 계열이다 — 앞면에서는 보이지 않는다. */
  const NOTE_LABELS = {
    special_reading: '특별한 읽기',
    also_read: '이렇게도 읽는다',
    also_reading: '이렇게도 읽는다',
    also_written: '이렇게도 적는다',
    same_kun: '같은 훈의 다른 한자',
    text: '비고'
  };

  function noteLine(entry) {
    const row = node('div', `kc-note-row note-${entry.kind}`);
    row.append(node('span', 'kc-note-of', entry.of || ''));
    row.append(node('span', 'kc-note-kind', NOTE_LABELS[entry.kind] || entry.kind));
    const body = node('span', 'kc-note-body');
    if (entry.kind === 'same_kun') {
      body.textContent = (entry.words || []).join(' · ');
    } else if (entry.kind === 'text') {
      body.textContent = entry.body || '';
    } else if (entry.kind === 'also_reading') {
      body.textContent = entry.reading || '';
    } else {
      const word = node('span', 'kc-note-word');
      word.textContent = entry.word || '';
      body.append(word);
      body.append(node('span', 'kc-note-value',
        entry.reading || entry.written || ''));
    }
    row.append(body);
    return row;
  }

  function noteBlock(entries) {
    const box = node('div', 'kc-notes reveal-meaning');
    for (const entry of entries) box.append(noteLine(entry));
    return box;
  }

  function render(note, options = {}) {
    const mode = options.mode || 'reading-front';
    const card = node('article', `kanji-card preview-card ${mode}`);
    /* 쓰기 덱에서만 정답 한자에 표식을 남긴다.  읽기 덱은 손대지 않는다. */
    const cardOptions = {
      revealMeanings: true,
      answers: WRITING_MODES.has(mode) ? answerSet(note) : null
    };
    const head = previewHeader(note, cardOptions);
    /* 연습판은 한자 원문 섹션의 가장 오른쪽에 놓인다. */
    if (WRITING_MODES.has(mode) && options.pad !== false) {
      head.append(writingPad(note, options));
    }
    card.append(head);
    card.append(readingGrid(note, cardOptions));
    if ((note.note || []).length) card.append(noteBlock(note.note));
    return card;
  }

  /* 획을 어디에 남기는가.
   *
   * 편집기는 자기 상태에 담아 `strokes` 로 넘긴다 — 한자를 오갔다 돌아와도 남는다.
   * Anki 는 아무것도 넘기지 않는다.  그런데 Anki 는 **면이 바뀔 때 카드를 통째로
   * 다시 그린다** — 앞면에서 쓴 획이 이 스크립트의 수명과 함께 사라진다는 뜻이다.
   * 그래서 아무도 넘기지 않으면 페이지 **바깥**에 남긴다.
   *
   * 남기는 곳은 '지금 이 한 자' 한 칸뿐이다.  `sessionStorage` 를 쓰므로 앱을 닫으면
   * 사라지고, 그마저 막힌 환경(사생활 모드 등)에서는 `window` 로 물러난다 — Anki
   * 데스크톱은 앞뒤를 같은 페이지에서 그리므로 그것만으로도 살아남는다.
   *
   * **앞면은 언제나 빈 판이다.**  획은 앞면에서 뒷면으로만 건너간다.  같은 카드를
   * 다시 만나도(다시 보기를 눌러도) 새로 쓰는 것이 연습이고, 아까 쓴 글씨가 남아
   * 있으면 그것을 보고 베끼게 된다.  그래서 앞면을 그릴 때 칸을 비운다. */
  const SLOT = 'sp-writing-pad';

  const slotRead = () => {
    try {
      const raw = window.sessionStorage && window.sessionStorage.getItem(SLOT);
      if (raw) return JSON.parse(raw);
    } catch (error) { /* 저장소가 막혀 있다.  아래의 window 칸으로 간다 */ }
    return window[SLOT] || null;
  };

  const slotWrite = (value) => {
    window[SLOT] = value;
    try {
      if (window.sessionStorage) {
        window.sessionStorage.setItem(SLOT, JSON.stringify(value));
      }
    } catch (error) { /* 못 남겨도 그리기 자체는 이어진다 */ }
  };

  const WRITING_BACK = 'writing-back';

  function keptStrokes(note, options) {
    if (options.strokes) return options.strokes;      // 부르는 쪽이 관리한다
    if (options.mode !== WRITING_BACK) {
      // 앞면으로 돌아왔다.  아까 쓴 것을 지우고 빈 판에서 시작한다.
      slotWrite({ key: note.character, strokes: [] });
      return [];
    }
    const slot = slotRead();
    return (slot && slot.key === note.character && Array.isArray(slot.strokes))
      ? slot.strokes : [];
  }

  function keepStrokes(note, options) {
    if (options.onStrokes) return options.onStrokes;
    // 부르는 쪽이 배열을 직접 들고 있으면(편집기) 제자리 수정으로 이미 남는다.
    if (options.strokes) return () => {};
    return (strokes) => slotWrite({ key: note.character, strokes });
  }

  /* 한자 원문 섹션 오른쪽 끝에서 마우스로 한자를 직접 쓴다.  획은 카드 바깥에
   * 남으므로 앞뒤를 뒤집어도, 카드를 다시 그려도 유지된다. */
  function writingPad(note, options) {
    const pad = node('div', 'writing-pad');
    const canvas = document.createElement('canvas');
    canvas.className = 'writing-canvas';
    canvas.width = WRITING_PAD_SIZE;
    canvas.height = WRITING_PAD_SIZE;
    canvas.setAttribute('aria-label', `${note.character} 쓰기 연습판`);
    pad.append(canvas);

    const strokes = keptStrokes(note, options);
    const keep = keepStrokes(note, options);
    const context = canvas.getContext('2d');
    const paint = () => {
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.lineWidth = 6;
      context.lineCap = 'round';
      context.lineJoin = 'round';
      context.strokeStyle = '#2b2a28';
      for (const stroke of strokes) {
        if (stroke.length < 2) continue;
        context.beginPath();
        context.moveTo(stroke[0][0], stroke[0][1]);
        for (const [x, y] of stroke.slice(1)) context.lineTo(x, y);
        context.stroke();
      }
    };

    let drawing = null;
    const at = (event) => {
      const box = canvas.getBoundingClientRect();
      return [
        (event.clientX - box.left) * canvas.width / box.width,
        (event.clientY - box.top) * canvas.height / box.height
      ];
    };
    canvas.onpointerdown = (event) => {
      event.preventDefault();
      event.stopPropagation();
      canvas.setPointerCapture(event.pointerId);
      drawing = [at(event)];
      strokes.push(drawing);
    };
    canvas.onpointermove = (event) => {
      if (!drawing) return;
      drawing.push(at(event));
      paint();
    };
    const release = () => {
      if (!drawing) return;
      if (drawing.length < 2) strokes.pop();
      drawing = null;
      paint();
      keep(strokes);
    };
    canvas.onpointerup = release;
    canvas.onpointercancel = release;
    canvas.onpointerleave = release;
    /* 카드 전체가 클릭으로 뒤집히므로 연습판 위의 클릭은 여기서 막는다. */
    canvas.onclick = (event) => event.stopPropagation();

    const clear = node('button', 'writing-clear', '지우기');
    clear.type = 'button';
    clear.onclick = (event) => {
      event.stopPropagation();
      strokes.length = 0;
      paint();
      keep(strokes);
    };
    pad.append(clear);
    paint();
    return pad;
  }

  window.KanjiCard = {
    render,
    noteFrom,
    keptStrokes,
    keepStrokes,
    parseAnnotation,
    parseAnnotated,
    plainSurface,
    groupOfKey,
    displayReading,
    displayParts,
    spellCells,
    furiganaClass,
    sortExamples,
    answerSet,
    shade,
    layoutReadingGroups,
    analyzeBranches,
    visibleRegularEntries,
    visibleRegularExamples,
    EXCEPTION_MARKER
  };
})();
