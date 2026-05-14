import re
import unicodedata
from html import escape


def normalizar(texto: str) -> str:
    texto = str(texto or "").lower()
    texto = "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
    texto = re.sub(r"[ \t]+", " ", texto)
    return texto


def compact(texto: str) -> str:
    return re.sub(r"\s+", " ", str(texto or "")).strip()


def h(valor) -> str:
    return escape(str(valor or ""), quote=True)


def a_float(valor) -> float:
    try:
        return float(str(valor).replace(",", "").strip())
    except Exception:
        return 0.0
