"""MateDog — a private, local MateCat-style CAT tool.

Runs entirely on the user's machine: FastAPI server + SQLite storage +
browser-based segment editor. Supports EN<->RU and EN<->NL translation,
translation memory (TMX), XLIFF round-trip, learning from paired corpora,
and proofreading/QA.
"""

__version__ = "0.1.0"

SUPPORTED_LANGS = {"en", "ru", "nl"}
SUPPORTED_PAIRS = {
    ("en", "ru"), ("ru", "en"),
    ("en", "nl"), ("nl", "en"),
}


def norm_lang(code: str) -> str:
    """Normalize a BCP-47-ish language code to its base subtag: 'en-US' -> 'en'."""
    return (code or "").strip().lower().replace("_", "-").split("-")[0]
