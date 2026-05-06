import unicodedata


def normalize_nfc(text: str) -> str:
    """Normalize Unicode string to NFC form.

    Windows IME and clipboard text can be NFD (decomposed diacritics).
    bge-m3 tokenizer is sensitive to NFC vs NFD, so normalize everywhere.
    """
    return unicodedata.normalize("NFC", text)
