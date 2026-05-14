import re

from core.utils import normalizar, compact, a_float


def _parsear_tiempo_qx(texto_norm: str):
    """
    Parsea tiempo quirúrgico en múltiples formatos:
    - '2hrs' → 2.0
    - '6hrs y 26 min' → 6.43
    - '2:26' → 2.43
    - '2 horas' / '2 horeas' → 2.0
    - '30 minutos' → 0.5

    Retorna horas como float o None.
    """
    bloque = ""

    match = re.search(
        r"tiempo quirurgico:\s*(.+?)(?:incidentes|hallazgos|$)",
        texto_norm,
    )

    if match:
        bloque = match.group(1).strip()

    if not bloque:
        return None

    # Formato H:MM
    match = re.match(r"(\d+):(\d{2})\b", bloque)
    if match:
        horas = int(match.group(1))
        minutos = int(match.group(2))
        return round(horas + minutos / 60, 2)

    # Formato "X hrs y YY min"
    match = re.search(
        r"(\d+)\s*(?:hrs?|horas?|horeas?)\s*(?:y|con)?\s*(\d+)\s*min",
        bloque,
    )
    if match:
        horas = int(match.group(1))
        minutos = int(match.group(2))
        return round(horas + minutos / 60, 2)

    # Formato solo horas
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:hrs?|horas?|horeas?)",
        bloque,
    )
    if match:
        return a_float(match.group(1))

    # Formato solo minutos
    match = re.search(r"(\d+)\s*min", bloque)
    if match:
        return round(int(match.group(1)) / 60, 2)

    # Último intento: primer número
    match = re.search(r"(\d+(?:\.\d+)?)", bloque)
    if match:
        return a_float(match.group(1))

    return None


def extraer_nota_postqx(texto: str) -> dict:
    texto_norm = normalizar(compact(texto))

    resultado = {
        "tiempo_quirurgico": None,
        "hemotransfusion": None,
        "histopatologico": None,
    }

    resultado["tiempo_quirurgico"] = _parsear_tiempo_qx(texto_norm)

    match = re.search(r"hemotransfusion:\s*(no|si|sí)", texto_norm)
    if match:
        resultado["hemotransfusion"] = match.group(1) not in ("no",)

    match = re.search(r"solicitud histopatologico:\s*(no|si|sí)", texto_norm)
    if match:
        resultado["histopatologico"] = match.group(1) not in ("no",)

    return resultado
