"""Module C — no imports from the other modules (deliberately independent)."""


def _slug_words(text):
    words = []
    for raw in str(text).split():
        cleaned = raw.strip().lower()
        if cleaned:
            words.append(cleaned)
    return words


def _normalize_words(text):
    words = []
    for raw in str(text).split():
        cleaned = raw.strip().lower()
        if cleaned:
            words.append(cleaned)
    return words


def slug(text):
    return "-".join(_slug_words(text))


def slug_alt(text):
    return "-".join(_normalize_words(text))
