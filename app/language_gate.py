"""Classify a headline as Chinese, English, or another language.

Only English and Chinese sources are reviewed; anything else is rejected by
default. Rejection must be evidence-driven rather than absence-driven: a terse
English headline such as "Mastercard Completes BVNK Acquisition" contains no
function words at all, so "no English markers" cannot be the test. A headline is
only rejected when another language is positively indicated.

The gate labels a recommendation. It never blocks a human decision.
"""

from __future__ import annotations

import re
from typing import Any


CHINESE = "chinese"
ENGLISH = "english"
OTHER = "other"

# Han ideographs without Japanese kana or Korean hangul.
_HAN = re.compile(r"[一-鿿㐀-䶿]")
_KANA = re.compile(r"[぀-ゟ゠-ヿ]")
_HANGUL = re.compile(r"[가-힯ᄀ-ᇿ]")
# Scripts that are never English or Chinese.
_OTHER_SCRIPT = re.compile(r"[Ѐ-ӿ֐-׿؀-ۿऀ-ॿ฀-๿Ͱ-Ͽ]")

_ENGLISH_MARKERS = {
    "the", "of", "to", "in", "for", "and", "on", "with", "as", "at", "by", "from",
    "is", "are", "will", "its", "it", "that", "this", "after", "over", "into",
    "how", "why", "what", "new", "says", "amid", "ahead", "than", "but", "not",
}

# Function words that signal a specific non-English language. Deliberately
# excludes words that double as English or as common proper nouns -- "per",
# "ada" and "die" all appear in real English payment headlines, and "yang" is a
# surname, which is why a single hit is never enough to reject.
_OTHER_MARKERS = {
    # Indonesian / Malay
    "yang", "dan", "untuk", "dengan", "ini", "itu", "dari", "adalah", "akan",
    "kini", "agar", "cara", "pakai", "menerusi", "bisa", "tidak", "sudah",
    "juga", "kepada", "oleh", "pada", "dalam", "negara", "pengguna", "transaksi",
    "penipuan", "daftar", "jangan", "setiap", "tetap", "hemat", "sokong",
    "pembayaran", "aplikasi", "luar", "negeri", "antarnegara", "di", "ke",
    "bayar", "selesai", "antar", "mudah", "hingga", "uang", "harga", "lintas",
    "turis", "pasar", "saldo", "rekening", "manfaatkan", "terbesar", "makin",
    "jelajah", "berlaku", "tembus", "kenali", "modus",
    # Spanish / Portuguese
    "que", "del", "los", "las", "por", "una", "más", "são", "não", "das",
    "pelo", "pela", "está", "años", "según",
    # French
    "pour", "des", "les", "avec", "dans", "aux", "cette", "sont",
    # German
    "und", "der", "das", "für", "mit", "von", "ist", "eine", "auf", "bei",
    # Italian
    "della", "nel", "sono", "dei", "gli",
    # Vietnamese / Turkish
    "của", "và", "cho", "được", "için", "ile", "bir", "ve",
}

_WORD = re.compile(r"[a-zA-ZÀ-ÿăđĩũơưạ-ỹğışçöü]+", re.UNICODE)


def detect_language_class(title: Any) -> str:
    text = str(title or "").strip()
    if not text:
        # Nothing to judge on; other gates already reject records this thin.
        return ENGLISH
    if _KANA.search(text) or _HANGUL.search(text) or _OTHER_SCRIPT.search(text):
        return OTHER
    if _HAN.search(text):
        return CHINESE

    words = [word.lower() for word in _WORD.findall(text)]
    english_hits = sum(1 for word in words if word in _ENGLISH_MARKERS)
    other_hits = sum(1 for word in words if word in _OTHER_MARKERS)
    if other_hits >= 2 and other_hits > english_hits:
        return OTHER
    return ENGLISH


def is_reviewable_language(title: Any) -> bool:
    return detect_language_class(title) != OTHER
