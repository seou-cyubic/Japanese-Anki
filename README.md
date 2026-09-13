# Japanese-Anki

[日本語](#日本語) · [English](#english) · [한국어](#한국어)

---

## 日本語

日本語学習用の **Anki 単語帳を作るパイプライン**です。公的な漢字表や辞書、語彙リストを解析してカードデータを作り、ブラウザで修正し、そのまま Anki に反映します。**漢字** (3,012 字)、**文法** (表現文型 631 個・例文 2,520)、**TOEIC** (英単語 4,059 語を日本語で覚える) の 3 つのデッキを作ります。

> このリポジトリにはコードだけがあります。原典資料 (PDF・辞書) と、それから作ったデータは著作権のため含めていません。

### 技術スタック

| 分類 | 使用技術 |
|---|---|
| 言語 | Python 3.10、JavaScript、HTML、CSS |
| PDF / 表の解析 | **PyMuPDF** (フォント・サイズ・座標による組版解析)、xlrd (Excel)、正規表現、Unicode 正規化 |
| 生成 AI | **Google Vertex AI — Gemini** (サービスアカウント OAuth2、`google-auth`)、応答キャッシュ、`ThreadPoolExecutor` による並列呼び出し |
| 言語資源 | **JMdict** (EDRDG)、**BCCWJ** 長単位語頻度表 (国立国語研究所)、**Unihan** (Unicode)、NGSL / TSL 語彙リスト、常用漢字表・表外漢字字体表 (文化庁) |
| Anki 連携 | **AnkiConnect** (JSON-RPC over HTTP)、ノートタイプ・テンプレート・CSS の自動更新 |
| 編集サーバー | Python 標準 `http.server` (`ThreadingHTTPServer`、ループバック限定)、REST 風 JSON API |
| 保存 | JSON + 編集 overlay、**楽観的ロック** (SHA-256 ETag)、ファイルロック、アトミック書き込み (`fsync` → 置換) |
| フロントエンド | Vanilla JavaScript、CSS デザイントークン、Canvas (手書き練習パッド) |
| テスト | `unittest` (239 件)、Node.js によるカードレンダラーの契約テスト |

### 各部分の技術

#### 1. 原典 PDF の組版解析 — `decks/*/pipeline/stage1_*.py`

- **漢字デッキ**: 文化庁の『常用漢字表』PDF から、単語の x 座標で「漢字 | 音訓 | 例 | 備考」の 4 列を切り分けます。『表外漢字字体表』から表外字 876 字と異体字を取り出します。
- **文法デッキ**: 『日本語表現文型辞典』PDF は、本文の要素ごとに**フォントとサイズが決まっています** (17.0pt MidashiGo = 見出し、9.2pt Ryumin = 例文、9.2pt FutoGo = 接続形、6.4pt AdobeMyungjo = 韓国語解説 …)。そこで座標とフォント情報だけで見出し・意味・級・例文・接続・解説を正確に分解します。印刷されたルビは「本文より小さい同じフォントが上にある」ことを使い、文字単位の座標でどの字に付くかを対応付けます。
- **付表の解釈** (`fuhyo.py`): 「お巡りさん / おまわりさん」のような熟字訓・当て字について、仮名を固定点にして読みを漢字ごとに分割し、モーラ境界の全探索と連濁・促音便を考慮した照合で「どの漢字が例外読みを担うか」を判定します。表にない曖昧さが出ればビルドを失敗させます。

#### 2. 生成 AI と検証の組み合わせ — `shared/gemini.py`, 各 stage2〜5

- 韓国語の意味・翻訳・例文など、辞書だけでは作れない部分を Gemini に依頼します。すべての応答を「モデル → 用途 → キー」構造のキャッシュに残すため、再実行時の新規呼び出しはほぼゼロです。
- **機械で測れることはモデルに任せません**。例:
  - 漢字の用例の意味は「漢字 | 読み | 表記」をキーにします (`音(おと)` と `音(ね)` を別の項目として扱う)。1 回目の呼び出しで意味を作り、2 回目で「要素が本当に別の意味か・自然な韓国語か」だけを判定する 2 パス方式です。
  - TOEIC の例文では、ふりがなをモデルに付けさせません。文と「文全体の読み」だけを受け取り、`shared/furigana.py` の整列アルゴリズムで漢字ごとにルビを割り当てます。整列できない場合は `None` になるため、**誤ったふりがながデータに入る道がありません**。
  - モデルが返した日本語の実在と読みは JMdict で全件検証し、不合格のものは最大 5 回まで聞き直します。
- 用例の選定には BCCWJ の頻度、韓国語の漢字音には韓国の級数別漢字表と Unihan を使います。
- 監査スクリプト (`audit_*.py`) がモデルを呼ばずに全件を再検査します。

#### 3. 文法箇所のマーキング — `decks/bunpo/pipeline/marking.py`, `lexicon.py`

- 例文の中で、その文型が使われている区間を `*` で囲みます。オフセット配列ではなくインライン表記にしたのは、人が例文を 1 文字でも直すとオフセットがずれるためです。
- 見出しは仮名、例文は漢字なので (`あいだ` ↔ `夏の間`)、ルビを使って「読み形」に変換したうえで照合します。
- `たり～たりする` のように**離れて実現する文型**は複数の区間として表します。
- 候補をすべて集めてから選びます。「辞書の単語の真ん中を切らない」ことが基準の一つで、`冷たい` の `たい` を `飲みたい` の `たい` と取り違えません。

#### 4. デッキ契約とプラグイン構造 — `shared/deckspec.py`, `decks/<名前>/deck.py`

- 各デッキは `DeckSpec` 1 つで、データの検証・並べ替え・統計・Anki ノートの作り方を宣言します。サーバーと Anki 同期は `decks/` を列挙して宣言だけを読むので、**どこにもデッキ名がハードコードされていません**。デッキを追加するのはフォルダを 1 つ足すだけです。
- 1 つのデッキが複数のノートタイプを出せます (文法デッキ: 文型単位の読みカードと、例文単位の作文カード)。

#### 5. Anki 同期 — `shared/anki.py`

- 同期は**上書きではなく照合**です。各ノートにプロジェクト固有の安定 ID を `Key` フィールドとして埋め、それで検索して、なければ追加、あれば変わったフィールドだけ更新します。何度実行しても重複しません。
- 削除はしません。人が Anki で消したノートを復活させないためです。
- **学習履歴と学習設定は守ります**。`forgetCards`・`saveDeckConfig`・`updateCompleteDeck` など履歴や設定に触れる AnkiConnect のアクションは、コードから呼べないように禁止リストで塞いでいます。

#### 6. 編集器と単一レンダラー — `app/`, `shared/store.py`, `decks/*/static/card.js`

- ローカル専用の HTTP サーバーでデータをブラウザ編集でき、保存すると Anki にも反映されます。
- 人の修正は生成データを直接書き換えず、**別ファイルの overlay** として保存します。パイプラインを再実行しても修正が失われません。
- 保存時はレコードの SHA-256 を ETag とする**楽観的ロック**で競合を検出し、ファイルロックとアトミック書き込みで途中失敗による破損を防ぎます。
- Anki ノートはレコードそのものを `Data` フィールドに持ち、各デッキの `card.js`・`card.css` が**編集画面と Anki のカードを同じコードで描画**します。2 つの表示が食い違うことがありません。
- 漢字の書き取りカードには Canvas の手書きパッドがあり、表/裏の切り替えはクラスの付け替えだけなので、書いた内容が消えません。TOEIC カードは例文をまとめて非表示にするスイッチを持ちます。

#### 7. テスト — `tests/`

- 239 件の `unittest` と Node.js のレンダラーテストで、ふりがな文法、付表の判定、並び順、文法マーキング、Anki 同期の照合ロジック (Anki を起動せずにテストダブルで検証)、ストアの競合処理、サーバー API を固定しています。
- パイプラインの各ステージは **import されると実行を拒否します**。読み込んだだけで原典を再解析し有料のモデルを呼ぶ事故を防ぐためで、この規則もテストで全デッキに適用しています。

### 実際の効用

- 市販の単語帳アプリにはない、**韓国語話者向けの日本語学習デッキ**を作れます。常用漢字と表外漢字 3,012 字すべてに韓国語の訓音、読み方ごとの用例と意味、ふりがなが付きます。
- 文法カードでは、例文の中で文型が使われている箇所が強調表示されるため、例文を見るだけで「どこがその文法か」が分かります。
- TOEIC の英単語を日本語で覚えることで、英語と日本語を同時に学習できます。
- 生成 AI が作った内容を辞書で全件検証し、誤りの入り口を構造的に塞いでいるので、手作業の単語帳より正確で、しかも数千枚規模を作れます。
- データを直したら Anki にそのまま反映され、**これまでの学習履歴は失われません**。JSON を手で加工して Anki に移し直す手間がありません。

---

## English

A **pipeline that builds Anki decks for learning Japanese**. It parses official kanji tables, dictionaries and vocabulary lists into card data, lets you fix that data in a browser, and pushes it straight into Anki. It builds three decks: **Kanji** (3,012 characters), **Grammar** (631 expression patterns, 2,520 example sentences) and **TOEIC** (4,059 English words learned *through Japanese*).

> This repository contains code only. The source materials (PDFs, dictionaries) and the data derived from them are not included, for copyright reasons.

### Tech Stack

| Category | Technologies |
|---|---|
| Languages | Python 3.10, JavaScript, HTML, CSS |
| PDF / table parsing | **PyMuPDF** (layout analysis by font, size and coordinates), xlrd (Excel), regular expressions, Unicode normalisation |
| Generative AI | **Google Vertex AI — Gemini** (service-account OAuth2 via `google-auth`), response cache, parallel calls with `ThreadPoolExecutor` |
| Language resources | **JMdict** (EDRDG), **BCCWJ** long-unit word frequency list (NINJAL), **Unihan** (Unicode), NGSL / TSL word lists, Jōyō Kanji Table and Hyōgai Kanji Glyph Table (Agency for Cultural Affairs) |
| Anki integration | **AnkiConnect** (JSON-RPC over HTTP), automatic updates of note types, templates and CSS |
| Editor server | Python standard `http.server` (`ThreadingHTTPServer`, loopback only), REST-style JSON API |
| Persistence | JSON plus an edit overlay, **optimistic locking** (SHA-256 ETags), file locks, atomic writes (`fsync` then replace) |
| Frontend | Vanilla JavaScript, CSS design tokens, Canvas (handwriting practice pad) |
| Testing | `unittest` (239 tests), Node.js contract tests for the card renderers |

### Technology in Each Part

#### 1. Layout analysis of source PDFs — `decks/*/pipeline/stage1_*.py`

- **Kanji deck**: the Agency for Cultural Affairs' Jōyō Kanji Table PDF is split into its four columns — kanji | readings | examples | notes — by the x-coordinate of each word. The Hyōgai Kanji Glyph Table provides 876 additional characters and their variants.
- **Grammar deck**: in the *Dictionary of Japanese Expression Patterns* PDF, **every kind of element has its own font and size** (17.0pt MidashiGo = headword, 9.2pt Ryumin = example sentence, 9.2pt FutoGo = conjugation pattern, 6.4pt AdobeMyungjo = Korean commentary, …). Coordinates and font metadata alone are enough to separate headwords, glosses, levels, examples, conjugation patterns and commentary exactly. Printed furigana is recognised as "the same font, smaller, just above the text" and attached to the right character using per-character coordinates.
- **Interpreting the appendix** (`fuhyo.py`): for special readings such as お巡りさん / おまわりさん, kana act as fixed anchors that split the word's reading per kanji; an exhaustive search over mora boundaries, allowing rendaku and gemination, decides which kanji carry the exceptional reading. Any ambiguity not already adjudicated fails the build.

#### 2. Generative AI paired with verification — `shared/gemini.py`, stages 2–5

- Gemini fills in what dictionaries cannot: Korean meanings, translations, example sentences. Every response is cached under model → purpose → key, so re-runs make almost no new calls.
- **Anything a machine can measure is not left to the model.** For example:
  - Kanji example meanings are keyed by kanji | reading | spelling, so `音(おと)` and `音(ね)` are separate entries. Pass 1 writes meanings; pass 2 only judges whether the items are truly different meanings and natural Korean.
  - The model is never asked to place furigana in TOEIC examples. It returns the sentence and the reading of the whole sentence, and the alignment algorithm in `shared/furigana.py` assigns ruby to each kanji. If alignment fails the result is `None`, so **wrong furigana has no way into the data**.
  - Every Japanese word the model returns is checked against JMdict for existence and reading; failures are re-asked up to five times.
- BCCWJ frequencies guide example selection; Korea's graded kanji table and Unihan supply Korean character readings.
- Audit scripts (`audit_*.py`) re-check every entry without calling the model.

#### 3. Marking grammar inside sentences — `decks/bunpo/pipeline/marking.py`, `lexicon.py`

- The span of each example where the pattern is used is wrapped in `*`. Inline marks were chosen over offset arrays because a single-character human edit would shift every offset.
- Headwords are written in kana while examples use kanji (`あいだ` vs `夏の間`), so matching is done on a "reading form" built from the furigana.
- **Patterns realised in separate pieces**, such as `たり～たりする`, become multiple spans.
- All candidates are collected before choosing; one rule is "never cut through the middle of a dictionary word", which keeps the `たい` inside `冷たい` from being mistaken for the `たい` in `飲みたい`.

#### 4. Deck contract and plugin structure — `shared/deckspec.py`, `decks/<name>/deck.py`

- Each deck declares a single `DeckSpec`: validation, sort order, statistics and how to build Anki notes. The server and the Anki sync enumerate `decks/` and read only these declarations, so **no deck name is hard-coded anywhere**. Adding a deck means adding a folder.
- A deck may emit several note types (the grammar deck has pattern-level reading cards and sentence-level composition cards).

#### 5. Anki sync — `shared/anki.py`

- Sync is **reconciliation, not overwrite**. Each note carries a stable project ID in a `Key` field; notes are looked up by it, added if missing, and only changed fields are updated. Running it any number of times never creates duplicates.
- Nothing is deleted, so notes a person removed in Anki are not resurrected.
- **Review history and study settings are protected.** AnkiConnect actions that touch them — `forgetCards`, `saveDeckConfig`, `updateCompleteDeck` and others — are on a deny list the code cannot call.

#### 6. Editor and a single renderer — `app/`, `shared/store.py`, `decks/*/static/card.js`

- A loopback-only HTTP server lets you edit the data in a browser; saving also updates Anki.
- Human edits never rewrite generated data directly; they are stored as a **separate overlay file**, so re-running the pipeline does not lose them.
- Saves use **optimistic locking** with a SHA-256 ETag per record to detect conflicts, and file locks plus atomic writes prevent corruption from partial failures.
- Each Anki note carries its record in a `Data` field, and the deck's `card.js` / `card.css` **render both the editor preview and the Anki card from the same code**, so the two can never disagree.
- Kanji writing cards include a Canvas handwriting pad; flipping front and back only toggles a class, so what you wrote survives. TOEIC cards have a switch that hides all example sentences.

#### 7. Tests — `tests/`

- 239 `unittest` cases plus Node.js renderer tests pin down the furigana grammar, appendix interpretation, ordering, grammar marking, Anki sync reconciliation (verified with test doubles, no running Anki required), store conflict handling and the server API.
- Every pipeline stage **refuses to run when imported**, preventing an accidental import from re-parsing sources and calling a paid model; a test enforces this across all decks.

### Real-World Value

- It produces **Japanese study decks for Korean speakers** that no off-the-shelf flashcard app offers: all 3,012 Jōyō and Hyōgai kanji with Korean readings, examples and meanings per reading, and furigana.
- Grammar cards highlight exactly where the pattern appears in each example, so the grammar point is visible at a glance.
- Learning TOEIC vocabulary through Japanese lets a learner study English and Japanese at once.
- AI-generated content is verified against dictionaries entry by entry and the routes for errors are closed structurally, so the decks are more accurate than hand-made ones while reaching thousands of cards.
- Fixes flow straight into Anki **without losing any review history**, with no hand-editing of JSON and re-importing.

---

## 한국어

일본어 학습용 **Anki 덱을 만드는 파이프라인**입니다. 공식 한자표·사전·어휘 목록을 분석해 카드 데이터를 만들고, 브라우저에서 고친 뒤 그 자리에서 Anki에 반영합니다. **한자**(3,012자), **문법**(표현 문형 631개·예문 2,520개), **토익**(영어 낱말 4,059개를 일본어로 외우기) 세 가지 덱을 만듭니다.

> 이 저장소에는 코드만 있습니다. 원천 자료(PDF·사전)와 그로부터 만든 데이터는 저작권 때문에 포함하지 않았습니다.

### 기술 스택

| 분류 | 사용 기술 |
|---|---|
| 언어 | Python 3.10, JavaScript, HTML, CSS |
| PDF / 표 분석 | **PyMuPDF** (글꼴·크기·좌표 기반 조판 분석), xlrd (Excel), 정규식, 유니코드 정규화 |
| 생성형 AI | **Google Vertex AI — Gemini** (서비스 계정 OAuth2, `google-auth`), 응답 캐시, `ThreadPoolExecutor` 병렬 호출 |
| 언어 자원 | **JMdict** (EDRDG), **BCCWJ** 장단위 빈도표 (일본 국립국어연구소), **Unihan** (Unicode), NGSL / TSL 어휘 목록, 常用漢字表·表外漢字字体表 (일본 문화청) |
| Anki 연동 | **AnkiConnect** (HTTP 기반 JSON-RPC), 노트 유형·템플릿·CSS 자동 갱신 |
| 편집 서버 | Python 표준 `http.server` (`ThreadingHTTPServer`, 루프백 전용), REST 형태 JSON API |
| 저장 | JSON + 편집 overlay, **낙관적 잠금** (SHA-256 ETag), 파일 잠금, 원자적 쓰기 (`fsync` 후 교체) |
| 프론트엔드 | Vanilla JavaScript, CSS 디자인 토큰, Canvas (손글씨 연습 패드) |
| 테스트 | `unittest` (239개), Node.js 카드 렌더러 계약 테스트 |

### 부분별 기술

#### 1. 원천 PDF 조판 분석 — `decks/*/pipeline/stage1_*.py`

- **한자 덱**: 일본 문화청 『常用漢字表』 PDF를 낱말의 x 좌표로 "한자 | 음훈 | 예 | 備考" 4열로 가릅니다. 『表外漢字字体表』에서 표외자 876자와 이체자를 뽑습니다.
- **문법 덱**: 『日本語表現文型辞典』 PDF는 본문 요소마다 **글꼴과 크기가 정해져 있습니다**(17.0pt MidashiGo = 표제형, 9.2pt Ryumin = 예문, 9.2pt FutoGo = 접속형, 6.4pt AdobeMyungjo = 한국어 해설 …). 그래서 좌표와 글꼴 정보만으로 표제형·뜻·급수·예문·접속형·해설을 정확히 분리합니다. 인쇄된 후리가나는 "본문보다 작은 같은 글꼴이 위에 놓인다"는 점을 이용해, 글자 단위 좌표로 어느 글자에 붙는지 맞춥니다.
- **付表 해석** (`fuhyo.py`): 「お巡りさん / おまわりさん」 같은 숙자훈·당て字에서 가나를 고정점으로 삼아 단어 읽기를 한자별로 나누고, 모라 경계 전탐색과 연탁·촉음편을 고려한 대조로 "어느 한자가 예외 읽기를 지는가"를 판정합니다. 표에 없는 새 모호함이 나오면 빌드를 실패시킵니다.

#### 2. 생성형 AI와 검증의 결합 — `shared/gemini.py`, 각 stage2~5

- 한국어 뜻·번역·예문처럼 사전만으로는 만들 수 없는 부분을 Gemini에 맡깁니다. 모든 응답을 "모델 → 용도 → 키" 구조 캐시에 남기므로 다시 돌려도 새 호출이 거의 없습니다.
- **기계로 잴 수 있는 것은 모델에게 맡기지 않습니다.** 예:
  - 한자 용례의 뜻은 "한자 | 요미카타 | 표기"를 키로 삼습니다(`音(おと)`와 `音(ね)`를 다른 항목으로 취급). 1패스에서 뜻을 짓고, 2패스에서는 "원소가 정말 다른 뜻인가, 자연스러운 한국어인가"만 판정합니다.
  - 토익 예문의 후리가나는 모델에게 붙이게 하지 않습니다. 문장과 "문장 전체의 읽기"만 받고, `shared/furigana.py`의 정렬 알고리즘이 한자마다 루비를 배정합니다. 정렬되지 않으면 `None`이 되므로 **잘못된 후리가나가 데이터에 들어갈 길이 없습니다.**
  - 모델이 돌려준 일본어는 JMdict로 실재 여부와 읽기를 전수 검증하고, 불합격이면 최대 5회까지 다시 묻습니다.
- 용례 선정에는 BCCWJ 빈도를, 한국 한자음에는 한국 급수별 배정한자표와 Unihan을 씁니다.
- 감사 스크립트(`audit_*.py`)가 모델을 부르지 않고 전 항목을 다시 검사합니다.

#### 3. 예문 속 문법 구간 표시 — `decks/bunpo/pipeline/marking.py`, `lexicon.py`

- 예문에서 그 문형이 쓰인 구간을 `*`로 감쌉니다. 오프셋 배열 대신 인라인 표기를 고른 것은, 사람이 예문을 한 글자만 고쳐도 오프셋이 전부 어긋나기 때문입니다.
- 표제형은 가나인데 예문은 한자로 쓰므로(`あいだ` ↔ `夏の間`), 후리가나로 만든 "읽기 형태" 위에서 대조합니다.
- `たり～たりする`처럼 **떨어져서 실현되는 문형**은 여러 구간으로 표시합니다.
- 후보를 모두 모은 뒤 고릅니다. "사전 낱말 한가운데를 자르지 않는다"가 기준 중 하나라서 `冷たい`의 `たい`를 `飲みたい`의 `たい`로 착각하지 않습니다.

#### 4. 덱 계약과 플러그인 구조 — `shared/deckspec.py`, `decks/<이름>/deck.py`

- 각 덱은 `DeckSpec` 하나로 데이터 검증·정렬·통계·Anki 노트 생성 방법을 선언합니다. 서버와 Anki 동기화는 `decks/`를 열거해 이 선언만 읽으므로 **어디에도 덱 이름이 하드코딩되어 있지 않습니다.** 덱을 추가하는 일은 폴더 하나를 더하는 일입니다.
- 덱 하나가 노트 유형 여러 개를 낼 수 있습니다(문법 덱: 문형 단위 읽기 카드와 예문 단위 작문 카드).

#### 5. Anki 동기화 — `shared/anki.py`

- 동기화는 **덮어쓰기가 아니라 대조**입니다. 노트마다 프로젝트 고유의 안정 식별자를 `Key` 필드에 심고, 그 값으로 찾아 없으면 추가하고 있으면 바뀐 필드만 갱신합니다. 몇 번을 돌려도 중복이 생기지 않습니다.
- 삭제하지 않습니다. 사람이 Anki에서 직접 지운 노트를 되살리지 않기 위해서입니다.
- **학습 이력과 학습 설정을 지킵니다.** `forgetCards`·`saveDeckConfig`·`updateCompleteDeck`처럼 이력이나 설정을 건드리는 AnkiConnect 액션은 금지 목록으로 막아 코드가 아예 부를 수 없습니다.

#### 6. 편집기와 단일 렌더러 — `app/`, `shared/store.py`, `decks/*/static/card.js`

- 로컬 전용 HTTP 서버로 데이터를 브라우저에서 편집하고, 저장하면 Anki에도 반영됩니다.
- 사람의 수정은 생성 데이터를 직접 고치지 않고 **별도 overlay 파일**로 저장합니다. 파이프라인을 다시 돌려도 수정이 사라지지 않습니다.
- 저장할 때는 레코드의 SHA-256을 ETag로 쓰는 **낙관적 잠금**으로 충돌을 감지하고, 파일 잠금과 원자적 쓰기로 중간 실패에 의한 파손을 막습니다.
- Anki 노트는 레코드 자체를 `Data` 필드에 싣고, 덱마다의 `card.js`·`card.css`가 **편집 화면과 Anki 카드를 같은 코드로 그립니다.** 두 화면이 어긋날 수 없습니다.
- 한자 쓰기 카드에는 Canvas 손글씨 패드가 있고, 앞뒤 전환은 클래스 토글만으로 끝나 쓴 내용이 지워지지 않습니다. 토익 카드에는 예문을 통째로 끄는 스위치가 있습니다.

#### 7. 테스트 — `tests/`

- `unittest` 239개와 Node.js 렌더러 테스트로 후리가나 문법, 付表 판정, 정렬 규칙, 문법 구간 표시, Anki 동기화 대조 로직(Anki 없이 대역으로 검증), 저장소 충돌 처리, 서버 API를 고정합니다.
- 파이프라인 스테이지는 **import하면 실행을 거부합니다.** 읽히는 것만으로 원전을 다시 분석하고 유료 모델을 부르는 사고를 막기 위해서이며, 이 규칙도 테스트가 전 덱에 걸어 둡니다.

### 실제 효용

- 시중 단어장 앱에는 없는 **한국어 화자용 일본어 학습 덱**을 만듭니다. 상용·표외 한자 3,012자 전부에 한국어 훈음, 요미카타별 용례와 뜻, 후리가나가 붙습니다.
- 문법 카드는 예문에서 그 문형이 쓰인 자리를 강조해, 예문만 봐도 "어디가 그 문법인지" 바로 보입니다.
- 토익 영단어를 일본어로 외우면서 영어와 일본어를 함께 공부할 수 있습니다.
- 생성형 AI가 만든 내용을 사전으로 전수 검증하고 오류가 들어올 길을 구조적으로 막았기 때문에, 손으로 만든 단어장보다 정확하면서도 수천 장 규모를 만들 수 있습니다.
- 데이터를 고치면 Anki에 그대로 반영되고 **그동안의 학습 이력은 사라지지 않습니다.** JSON을 손으로 가공해 Anki로 다시 옮기는 수고가 없습니다.
