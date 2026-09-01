# -*- coding: utf-8 -*-
"""付表 예외 판정 알고리즘의 계약."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "decks" / "kanji" / "pipeline"))

import fuhyo  # noqa: E402


# 판정에 필요한 만큼의 정규 읽기.  본표 음훈 칸에서 오는 값이다.
REGULAR = fuhyo.build_regular_readings({
    "手": {"シュ": [], "て": [], "た": []},
    "下": {"カ": [], "ゲ": [], "した": [], "しも": [], "もと": [],
           "さー": [], "くだー": [], "おー": []},
    "上": {"ジョウ": [], "ショウ": [], "うえ": [], "うわ": [], "かみ": [],
           "あー": [], "のぼー": []},
    "伝": {"デン": [], "つたー": []},
    "今": {"コン": [], "キン": [], "いま": []},
    "年": {"ネン": [], "とし": []},
    "日": {"ニチ": [], "ジツ": [], "ひ": [], "か": []},
    "川": {"セン": [], "かわ": []},
    "原": {"ゲン": [], "はら": []},
    "河": {"カ": [], "かわ": []},
    "巡": {"ジュン": [], "めぐー": []},
    "早": {"ソウ": [], "サッ": [], "はやー": []},
    "乙": {"オツ": []},
    "女": {"ジョ": [], "ニョ": [], "ニョウ": [], "おんな": [], "め": []},
    "立": {"リツ": [], "リュウ": [], "たー": [], "たてー": []},
    "退": {"タイ": [], "しりぞー": []},
    "笑": {"ショウ": [], "わらー": [], "えー": []},
    "顔": {"ガン": [], "かお": []},
})


class SegmentationTest(unittest.TestCase):
    def judge(self, surface, reading):
        found, ambiguous = fuhyo.irregular_kanji(surface, reading, REGULAR)
        self.assertIsNotNone(found, f"{surface}/{reading} 판정 실패: {ambiguous}")
        return found

    def test_regular_reading_keeps_the_kanji_out(self) -> None:
        """手 는 た·て 를 가지므로 下手·手伝う 를 지지 않는다."""
        self.assertEqual(self.judge("下手", "へた"), ["下"])
        self.assertEqual(self.judge("手伝う", "てつだう"), ["伝"])
        self.assertEqual(self.judge("上手", "じょうず"), ["手"])

    def test_okurigana_is_an_anchor_not_a_reading(self) -> None:
        """가나 리터럴은 읽기 위의 고정점이다. 立=た 는 정규, 退=の 가 예외."""
        self.assertEqual(self.judge("立ち退く", "たちのく"), ["退"])

    def test_prefix_and_suffix_kana_anchor(self) -> None:
        self.assertEqual(self.judge("お巡りさん", "おまわりさん"), ["巡"])

    def test_partially_regular_compound(self) -> None:
        """年=とし 는 정규이므로 今年 은 今 만 진다."""
        self.assertEqual(self.judge("今年", "ことし"), ["今"])
        self.assertEqual(self.judge("河原", "かわら"), ["原"])
        self.assertEqual(self.judge("川原", "かわら"), ["原"])

    def test_pure_jukujikun_assigns_every_kanji(self) -> None:
        """어느 조각도 정규가 아니면 구성 한자 전부가 진다."""
        self.assertEqual(self.judge("今日", "きょう"), ["今", "日"])
        self.assertEqual(self.judge("今朝", "けさ"), ["今", "朝"])

    def test_fully_regular_word_also_assigns_every_kanji(self) -> None:
        """付表 수록 자체가 예외다. 지목할 한자가 없으면 전부가 진다."""
        self.assertEqual(self.judge("笑顔", "えがお"), ["笑", "顔"])

    def test_fragment_ambiguity_does_not_change_the_verdict(self) -> None:
        """さ|おと|め 와 さお|と|め 는 예외 집합이 같다 — 키가 전체 읽기라서."""
        self.assertEqual(self.judge("早乙女", "さおとめ"), ["早", "乙"])

    def test_mora_boundary_blocks_small_kana_starts(self) -> None:
        for pieces in fuhyo._splits("きょう", 2):
            self.assertNotIn(pieces[1][0], "ゃゅょっー")


class VariantTest(unittest.TestCase):
    def test_rendaku_and_sokuon_count_as_regular(self) -> None:
        self.assertIn("がわ", fuhyo.phonetic_variants("かわ"))
        self.assertIn("ばら", fuhyo.phonetic_variants("はら"))
        self.assertIn("ぱら", fuhyo.phonetic_variants("はら"))
        self.assertIn("がっ", fuhyo.phonetic_variants("かつ"))


class NoteStrippingTest(unittest.TestCase):
    """備考 칸에는 付表 포인터와 진짜 용례가 섞여 있다.  포인터만 걷어내야 한다."""

    def test_reference_tokens_are_removed(self) -> None:
        self.assertEqual(fuhyo.strip_reference_tokens("上手（じょうず）下手（へた）"), "")
        self.assertEqual(fuhyo.strip_reference_tokens("愛媛（えひめ）県"), "")
        self.assertEqual(fuhyo.strip_reference_tokens("今日（きょう）今朝（けさ）今年（ことし）"), "")
        # 오쿠리가나가 괄호 앞뒤에 붙는 꼴
        self.assertEqual(fuhyo.strip_reference_tokens("手伝（てつだ）う"), "")
        self.assertEqual(fuhyo.strip_reference_tokens("兄（にい）さん"), "")
        # 「・」 로 묶인 복합 표기
        self.assertEqual(fuhyo.strip_reference_tokens("河原・川原（かわら）"), "")

    def test_genuine_notes_survive(self) -> None:
        for note in ("⇔当てる，充てる", "「遺言」は，「イゴン」とも。",
                     "「宮内庁」などと使う。", "「京浜」，「京阪」などと使う。"):
            self.assertEqual(fuhyo.strip_reference_tokens(note), note)

    def test_paren_less_prefecture_notes_are_examples_not_pointers(self) -> None:
        """구성 한자가 모두 정규 읽기면 예외가 아니라 그 한자의 용례다.

        岡=おか, 埼=さい, 栃=とち, 茨=いばら 는 전부 정규 읽기이므로 괄호 읽기가
        붙지 않는다.  이것을 포인터로 오인해 지우면 용례를 잃는다.
        """
        for note in ("岡山県，静岡県，福岡県", "埼玉県", "栃木県", "茨城県", "岐阜県"):
            self.assertEqual(fuhyo.strip_reference_tokens(note), note)

    def test_stripping_never_crosses_a_distinction_marker(self) -> None:
        """⇔ 뒤는 동음이의 주석이다.  포인터를 지우다 여기까지 넘어가면 안 된다.

        넘어가면 固/かたい 의 용례로 「硬い」 가 새어 들어온다.
        """
        self.assertEqual(
            fuhyo.strip_reference_tokens("固唾（かたず）⇔堅い，硬い"), "⇔堅い，硬い")
        self.assertEqual(
            fuhyo.strip_reference_tokens("日和（ひより）⇔和らぐ"), "⇔和らぐ")


class AdjudicationTest(unittest.TestCase):
    def test_the_two_ambiguous_words_are_pinned(self) -> None:
        self.assertEqual(fuhyo.ADJUDICATED[("うわき", "浮気")], ["浮"])
        self.assertEqual(fuhyo.ADJUDICATED[("やよい", "弥生")], ["生"])

    def test_a_new_ambiguity_fails_the_build(self) -> None:
        """모호가 표에 없으면 조용히 넘어가지 않고 빌드를 세운다."""
        regular = fuhyo.build_regular_readings({"浮": {"フ": [], "うー": []},
                                                "気": {"キ": [], "ケ": []}})
        with self.assertRaises(AssertionError):
            fuhyo.compute_except([("うわき", ["浮氣"])],
                                 dict(regular, 氣=regular["気"]))


if __name__ == "__main__":
    unittest.main()
