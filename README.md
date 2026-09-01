# SP_Compact

일본어 학습용 **Anki 덱을 만드는 파이프라인**이다. 사전과 표준 자료(PDF·표)를 파싱해
학습 카드 데이터를 만들고, 브라우저에서 고치고, 그 자리에서 Anki 덱에 반영한다.
JSON 을 손으로 가공해 Anki 로 옮기는 왕복이 없다.

덱은 셋이다.

| 덱 | 내용 | Anki |
|---|---|---|
| **한자** | 상용 2,136 + 표외 876 = **3,012 자** — 음훈·요미카타·용례·이체자 | 노트 3,012 → 카드 6,024 |
| **문법** | 표현 문형 **631 개**, 예문 **2,520** — 뜻·접속형·해설·한국어 해석 | 노트 3,151 → 카드 3,151 |
| **토익** | 영어 낱말 **4,059 개** — 영어를 한국어가 아니라 **일본어로** 외운다.  카드 안의 스위치로 예문을 통째로 끌 수 있다 | 노트 4,059 → 카드 8,118 |

세 덱 모두 **레코드 하나가 노트 하나**이고, **카드는 프론트엔드 렌더러가 그린다** —
Anki 노트는 레코드 자체를 `Data` 필드에 싣고 다니며, 그 덱의 `card.js`·`card.css` 가
편집 화면과 Anki 카드를 **함께** 그린다. 두 곳이 어긋날 수 없다.

---

## 이 저장소에는 코드만 있다

**정보 원천도, 산출물도 올리지 않는다.** 원천은 남의 저작물이고, 산출물은 그 원천의
내용을 그대로 담고 있기 때문이다. 저장소에 있는 것은 그 둘을 잇는 코드뿐이다.

```
있는 것        파이프라인 · 편집기 · 렌더러 · Anki 동기화 · 시험
없는 것        decks/*/base/  (원전)     decks/*/data/  (산출물)
               corpora/       (코퍼스)   secrets/       (자격 증명)
```

받아서 직접 돌리면 산출물이 생긴다. 아래 §원천 조달 과 §돌리는 법 을 따른다.

---

## 원천 조달

파이프라인을 돌리려면 원천을 직접 받아 아래 자리에 둔다. **이 저장소는 어느 것도
재배포하지 않는다.**

### 한자 덱 — `decks/kanji/base/`

| 파일 | 무엇 | 어디서 |
|---|---|---|
| `J_20101130.pdf` | 常用漢字表 (2010 내각고시 제2호) | [문화청 常用漢字表](https://www.bunka.go.jp/kokugo_nihongo/sisaku/joho/joho/kijun/naikaku/kanji/) |
| `J_19811001.pdf` | 常用漢字表 (1981년판) — 구 자체 대조용 | 위와 같은 문화청 국어시책 페이지 |
| `H_20000901.pdf` | 表外漢字字体表 (2000 국어심의회 답신) | [문화청 表外漢字字体表](https://www.bunka.go.jp/kokugo_nihongo/sisaku/joho/joho/kakuki/22/tosin03/) |
| `H_20000901_data.pdf` | 위 답신의 자체 일람 부분 | 위와 같음 |
| `S.txt` | 学年別漢字配当表 (학년별 배당한자) — 학년마다 한 줄 | [문부과학성 학습지도요령](https://www.mext.go.jp/a_menu/shotou/new-cs/youryou/syo/koku/001.htm) 별표에서 옮겨 적는다 |
| `H.txt` | 표외한자 목록 — 쉼표로 나열한 평문 | `H_20000901.pdf` 의 인쇄표준자체에서 옮겨 적는다 |
| `K.xls` | 급수별 배정한자표 (한국 훈음) | [한국어문회](http://www.hanja.re.kr/) 자료실 |

### 문법 덱 — `decks/bunpo/base/`

| 파일 | 무엇 |
|---|---|
| `B.pdf` | **『日本語表現文型辞典』(ALC PRESS)** — 시판 사전이다. 각자 정당하게 구해야 한다. |

### 토익 덱 — `decks/toeic/base/`

NGSL 과 TSL 은 **CC BY-SA** 로 공개되어 있다 (Browne, Culligan & Phillips).

```
https://www.newgeneralservicelist.com/s/NGSL_12_stats.csv
https://www.newgeneralservicelist.com/s/NGSL_12_lemmatized_for_teaching.csv
https://www.newgeneralservicelist.com/s/TSL_12_stats.csv
https://www.newgeneralservicelist.com/s/TSL_12_lemmatized_for_teaching.csv
```

### 공용 코퍼스 — `corpora/`

| 자료 | 어디서 | 자리 |
|---|---|---|
| JMdict (CC BY-SA, EDRDG) | `https://www.edrdg.org/pub/Nihongo/JMdict.gz` | `corpora/JMdict` |
| BCCWJ 장단위 빈도표 (NINJAL) | `https://doi.org/10.15084/00003213` | `corpora/bccwj_luw/BCCWJ_frequencylist_luw_ver1_1.tsv` |
| Unihan Readings (Unicode) | `https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip` | `corpora/unihan/` |

### 자격 증명 — `secrets/`

뜻·번역·예문 일부를 Gemini(Vertex AI)에서 받는다. Google Cloud 서비스 계정 JSON 을
`secrets/` 에 둔다. **키는 절대 커밋하지 않는다** — `.gitignore` 가 막지만, 실수로
올렸다면 파일을 지우는 것이 아니라 **키를 폐기**해야 한다.

---

## 산출물

파이프라인이 만드는 것은 `decks/<덱>/data/` 아래의 JSON 이다. 저장소에는 없다.

| 덱 | 최종 산출물 | 크기 | 무엇이 들었나 |
|---|---|---|---|
| 한자 | `data_japanese.json` | ~1.9 MB | 한자 3,012 · 요미카타 4,862 · 용례 11,910 · 이체자 391 |
| 문법 | `bunpo_korean.json` | ~1.9 MB | 문형 631 · 예문 2,520 · 번역 2,520 · 문법 구간 표시 2,492 |
| 토익 | `toeic_japanese.json` | ~3.8 MB | 낱말 4,059 · 뜻 6,423 · 예문 6,327 쌍 |

`data/cache.json` 은 모델 응답 캐시다. 있으면 두 번째 실행부터 신규 호출이 거의
발생하지 않으므로 **지우지 않는 편이 좋다**(다만 저장소에는 올리지 않는다).

### 산출물을 다룰 때의 규칙

1. **산출물을 손으로 고치지 않는다.** 다음 실행이 지운다. 고쳐야 할 것은 언제나 그
   값을 만들어 낸 규칙이고, 한 건을 고칠 때도 같은 원인을 가진 모든 건이 함께
   고쳐져야 한다.
2. **파이프라인은 JSON 에서 끝나지 않는다.** 규칙을 고쳤으면 뒤따르는 스테이지를 전부
   다시 돌리고 `python -m app sync` 로 Anki 까지 밀어 넣는다. JSON 만 새로워지고
   Anki 가 옛것이면 그 수정은 미완이다.
3. **Anki 의 학습 정보는 건드리지 않는다.** 카드의 학습 이력과 예약은 사람이 쌓은
   것이고 데이터에서 다시 만들 수 없다. 동기화는 추가·갱신·이동만 하고 삭제하지
   않으며, 학습 이력·사전 설정을 만지는 AnkiConnect 액션은 코드가 아예 부를 수 없다.
4. **산출물은 원천의 파생물이다.** 문법 덱의 산출물 한 파일에 시판 사전의 예문과
   해설이 33 만 자 들어 있다 — PDF 를 빼고 이것만 공개하는 것은 형태만 바꾼 같은
   배포다. 예문의 한국어 번역도 원문의 2차적저작물이다. 공개하지 않는다.

---

## 돌리는 법

```
의존: pymupdf, xlrd, google-auth        (파이썬 3.10+)

python decks/kanji/pipeline/run_all.py            # 한자  stage1..5
python decks/toeic/pipeline/run_all.py            # 토익  stage1..4
python decks/bunpo/pipeline/stage1_extract.py     # 문법  stage1
python decks/bunpo/pipeline/stage2_korean.py      #       stage2

python -m app sync                                # 산출물을 Anki 에 반영
python -m app serve                               # 편집기 http://127.0.0.1:8770

python -m app check --deck kanji                  # 데이터·편집 overlay 전수 검증
python -m app materialize --deck kanji --output <경로>   # base+overlay 완성본
```

스테이지 스크립트는 **import 하면 실행을 거절한다** — 읽히는 것만으로 원전을 다시
읽고 모델을 부르는(유료다) 일이 벌어지지 않도록 막아 둔 것이다. 반드시 위처럼 실행한다.

Anki 연동에는 **AnkiConnect 애드온(코드 `2055492159`)** 이 필요하다. 애드온이 8765 를
쓰므로 편집기는 8770 을 쓴다.

시험:

```
python -m unittest discover -s tests -t .     # 197 tests
node tests/test_card.mjs                      # 렌더러 계약 + Anki 카드 면
```

Anki 관련 시험은 Anki 가 꺼져 있어도 전부 돌아간다 — 대역으로 대조 논리만 검증한다.
다만 **산출물이 있어야 도는 시험이 있다.** 갓 받은 저장소에는 `decks/*/data/` 가 없으므로
파이프라인을 한 번 돌린 뒤에 전부 통과한다.

---

## 구조

```
shared/       주제 무관 공용 — 경로·덱 계약·Gemini·Anki·후리가나 문법·저장
decks/<덱>/   base/ 원천(읽기 전용) · data/ 산출물 · pipeline/ 스테이지
              static/ 그 덱의 렌더러(card.js·card.css) · deck.py 덱 선언
app/          덱에 종속되지 않는 편집기 셸 (서버 + 프론트엔드)
tests/        전 계약 검증
```

**덱을 하나 더 붙이는 일은 폴더 하나를 더하는 일이다.** `decks/<이름>/deck.py` 가
`DeckSpec` 하나를 내놓으면 서버·저장소·Anki 동기화가 자동으로 찾아낸다. 어느 쪽도 덱
이름을 하드코딩하지 않는다.

---

## 더 읽을 것 — 코드가 곧 문서다

이 저장소는 '무엇을 하는가' 보다 **'왜 그렇게 했는가'** 를 코드 안에 적는다. 판정
규칙, 표기법, 함정과 그 근거는 전부 해당 모듈의 첫머리 문서화 주석에 있고, 규칙마다
그것을 잠그는 시험이 `tests/` 에 있다. 별도의 설계 문서를 찾을 필요가 없다.

| 무엇이 궁금한가 | 어디를 읽는가 |
|---|---|
| 후리가나를 표기 안에 싣는 주석 문법 (`空港(くうこう)`) | `shared/furigana.py` |
| 원전 PDF 를 글꼴과 좌표로 갈라내는 법 | `decks/*/pipeline/stage1_*.py` |
| 예문에서 문법이 쓰인 구간을 찾는 두 단계 | `decks/bunpo/pipeline/marking.py` |
| 덱 하나가 서버·저장소·Anki 에 내놓는 계약 | `shared/deckspec.py`, `decks/*/deck.py` |
| 동기화가 덮어쓰기가 아니라 대조인 이유, 학습 정보를 지키는 법 | `shared/anki.py` |
| 카드 앞뒤가 클래스 하나로 갈리는 구조 | `decks/*/static/card.js`·`card.css` |
| 편집 overlay 와 낙관적 잠금 | `shared/store.py` |

시험 목록이 곧 이 프로젝트가 지키기로 한 것들의 목록이다 — `tests/` 의 각 파일
첫머리에 무엇을 잠그는지 적혀 있다.

## 라이선스

코드는 이 저장소의 것이다. 원천 자료는 각자의 권리자에게 있으며 이 저장소는 어느 것도
재배포하지 않는다 — 위 §원천 조달 의 링크에서 각 자료의 이용 조건을 확인한다.
