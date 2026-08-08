import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.ai_news_review import AI_ACCEPT, AI_REJECT, recommend_news  # noqa: E402
from app.language_gate import CHINESE, ENGLISH, OTHER, detect_language_class  # noqa: E402


class LanguageDetectionTests(unittest.TestCase):
    def test_chinese_headlines_are_reviewable(self):
        self.assertEqual(
            detect_language_class("AlipayHK 防騙功能升級 答問題免費賺高達 300 A. Point 獎賞 - Jetso Today"),
            CHINESE,
        )
        self.assertEqual(detect_language_class("蚂蚁国际扩展 Alipay+ 银行网络"), CHINESE)

    def test_english_headlines_are_reviewable(self):
        for title in (
            "Wise gains PayNet access to support DuitNow QR payments in Malaysia",
            "HKMA Launches Quantum Readiness Whitepaper, Index for Banks",
        ):
            self.assertEqual(detect_language_class(title), ENGLISH, title)

    def test_a_terse_english_headline_with_no_function_words_is_still_english(self):
        # Absence of English markers must never be read as evidence of another language.
        for title in (
            "Mastercard Completes BVNK Acquisition",
            "Visa to buy BioCatch",
            "Airwallex launches local payment methods",
        ):
            self.assertEqual(detect_language_class(title), ENGLISH, title)

    def test_an_english_headline_is_not_rejected_because_someone_is_named_yang(self):
        title = "At the helm: Gary Yang takes on the role of Asia-Pacific President at Adyen"
        self.assertEqual(detect_language_class(title), ENGLISH)

    def test_indonesian_and_malay_headlines_are_rejected(self):
        for title in (
            "Cara Pakai QRIS Agar Tetap Hemat: Tips Cerdas Mengontrol Anggaran Digital",
            "Wise Kini Sokong Pembayaran DuitNow QR Menerusi Aplikasi di Malaysia - Hrga.my",
            "Daftar Negara yang Bisa Pakai QRIS, Transaksi Digital Makin Mudah di Luar Negeri",
            "Ini Daftar Negara yang Bisa Manfaatkan Pembayaran QRIS",
        ):
            self.assertEqual(detect_language_class(title), OTHER, title)

    def test_other_scripts_are_rejected_and_japanese_is_not_mistaken_for_chinese(self):
        self.assertEqual(detect_language_class("ペイパルが日本で新サービスを開始"), OTHER)
        self.assertEqual(detect_language_class("페이팔 한국 진출"), OTHER)
        self.assertEqual(detect_language_class("Сбербанк запускает платежи"), OTHER)
        self.assertEqual(detect_language_class("บริการชำระเงินใหม่"), OTHER)

    def test_a_single_ambiguous_marker_is_not_enough_to_reject(self):
        self.assertEqual(detect_language_class("Stripe expands into Germany with der Bank"), ENGLISH)

    def test_a_foreign_proper_noun_alone_does_not_reject_an_english_headline(self):
        # Bank Negara Malaysia is a regulator GBSS actually watches.
        for title in (
            "Bank Negara Malaysia approves new e-wallet licences",
            "Alipay+ partners with Bank Negara Malaysia on QR interoperability",
        ):
            self.assertEqual(detect_language_class(title), ENGLISH, title)

    def test_a_terse_indonesian_headline_is_rejected_on_accumulated_markers(self):
        self.assertEqual(detect_language_class("QRIS Antar Negara 2026: Scan, Bayar, Selesai"), OTHER)
        self.assertEqual(detect_language_class("6 Negara yang Bisa Pakai QRIS Antarnegara, Ada Thailand hingga Jepang"), OTHER)

    def test_an_empty_title_is_left_to_the_other_gates(self):
        self.assertEqual(detect_language_class(""), ENGLISH)
        self.assertEqual(detect_language_class(None), ENGLISH)


class LanguageGateInReviewTests(unittest.TestCase):
    NEWS = {"Source URL": {"link": "https://example.com/a"}, "Publish Date": "2026-08-04", "Event Case ID": "event-1"}
    STRONG_EVENT = {"Event Type": "Product_Launch", "Business Lines": "Alipay_Plus", "Relevance Score": "0.90"}

    def test_a_strong_event_in_another_language_is_rejected_by_default(self):
        result = recommend_news(
            {**self.NEWS, "Title": "Ini Daftar Negara yang Bisa Manfaatkan Pembayaran QRIS"},
            self.STRONG_EVENT,
        )
        self.assertEqual(result.status, AI_REJECT)
        self.assertIn("语言", result.reason)

    def test_the_same_event_in_english_is_still_accepted(self):
        result = recommend_news({**self.NEWS, "Title": "QRIS cross-border payments expand"}, self.STRONG_EVENT)
        self.assertEqual(result.status, AI_ACCEPT)

    def test_a_chinese_headline_is_still_accepted(self):
        result = recommend_news({**self.NEWS, "Title": "支付宝跨境二维码互通扩展至新市场"}, self.STRONG_EVENT)
        self.assertEqual(result.status, AI_ACCEPT)

    def test_neither_the_rulebook_nor_the_sweep_can_override_the_language_default(self):
        result = recommend_news(
            {**self.NEWS, "Title": "Cara Pakai QRIS Agar Tetap Hemat: Tips Cerdas Mengontrol Anggaran"},
            self.STRONG_EVENT,
            sweep_score=0.99,
        )
        self.assertEqual(result.status, AI_REJECT)


class FingerprintChurnTests(unittest.TestCase):
    """Adding the gate must not re-fingerprint the English majority."""

    def test_an_english_record_keeps_the_fingerprint_it_had_before_the_gate(self):
        from app.ai_news_review import review_fingerprint

        fields = {"Title": "Mastercard Completes BVNK Acquisition", "Publish Date": "2026-08-04"}
        payload_without_language = {
            "event_id": "", "source_url": "", "publish_date": "2026-08-04",
            "duplicate_of": "", "duplicate_reason": "", "event_type": "",
            "business_lines": "", "relevance": "", "strategic": "",
            "learned_rule": "", "rulebook": "",
        }
        import hashlib
        import json

        encoded = json.dumps(payload_without_language, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.assertEqual(review_fingerprint(fields, None), hashlib.sha256(encoded).hexdigest()[:20])

    def test_a_non_english_record_does_get_a_new_fingerprint(self):
        from app.ai_news_review import review_fingerprint

        english = {"Title": "QRIS expands abroad", "Publish Date": "2026-08-04"}
        indonesian = {"Title": "Ini Daftar Negara yang Bisa Manfaatkan Pembayaran QRIS", "Publish Date": "2026-08-04"}
        self.assertNotEqual(review_fingerprint(english, None), review_fingerprint(indonesian, None))


if __name__ == "__main__":
    unittest.main()
