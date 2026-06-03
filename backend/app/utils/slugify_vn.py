import unicodedata
import re


def slugify_vn(text: str) -> str:
    """Strip Vietnamese diacritics and lowercase for filter matching.

    Example: slugify_vn("Hải Châu") == "hai chau"
    Allows users to type district names without diacritics.
    """
    nfc = unicodedata.normalize("NFC", text)
    # Manually replace đ and Đ since they don't decompose into d + diacritic in NFD
    nfc = nfc.replace("đ", "d").replace("Đ", "D")
    # Decompose to NFD so diacritics become separate chars, then strip non-ASCII
    nfd = unicodedata.normalize("NFD", nfc)
    ascii_text = nfd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text).strip().lower()
