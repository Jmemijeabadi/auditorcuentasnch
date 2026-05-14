import re

from core.utils import normalizar, compact, a_float
from core.document_classifier import canonical_depto


ITEM_RE = re.compile(
    r"^(?P<codigo>[A-Z0-9-]+)\s+"
    r"(?P<descripcion>.*?)\s+"
    r"(?P<cantidad>\d+\.\d{3})\s+"
    r"(?P<precio>[\d,]+\.\d{2})\s+"
    r"(?P<descto>[\d,]+\.\d{2})\s+"
    r"(?P<subtotal>[\d,]+\.\d{2})\s+"
    r"(?P<impuesto>[\d,]+\.\d{2})\s+"
    r"(?P<total>[\d,]+\.\d{2})"
    r"(?:\s+(?P<fecha_folio>\S+))?"
    r"(?:\s+(?P<folio2>\S+))?"
    r"(?:\s+(?P<factura>\S+))?$",
    re.IGNORECASE,
)


def _parsear_ff(ff_raw, f2_raw):
    if not ff_raw:
        return "", ""

    if re.match(r"^\d{2}-\d{2}-\d{4}$", ff_raw):
        return ff_raw, f2_raw or ""

    if len(ff_raw) > 10 and re.match(r"\d{2}-\d{2}-\d{4}", ff_raw):
        return ff_raw[:10], ff_raw[10:]

    return "", ff_raw


def _bloque_departamentos(texto: str):
    patron = re.compile(r"(?im)^Departamento:\s*(.*)$")
    matches = list(patron.finditer(texto))
    bloques = []

    for i, match in enumerate(matches):
        inicio = match.end()
        fin = matches[i + 1].start() if i + 1 < len(matches) else len(texto)

        bloques.append(
            {
                "encabezado": match.group(1).strip(),
                "departamento": canonical_depto(match.group(1)),
                "contenido": texto[inicio:fin],
            }
        )

    return bloques


def extraer_todos_items(
    texto: str,
    nombre_archivo: str,
    tipo_doc: str,
    cuenta: str,
) -> list:
    items = []

    for bloque in _bloque_departamentos(texto):
        if bloque["departamento"] == "caja":
            continue

        for linea in bloque["contenido"].splitlines():
            linea_compacta = compact(linea)

            if not linea_compacta:
                continue

            match = ITEM_RE.match(linea_compacta)

            if not match:
                continue

            fecha, folio = _parsear_ff(
                match.group("fecha_folio"),
                match.group("folio2"),
            )

            items.append(
                {
                    "cuenta": cuenta,
                    "archivo": nombre_archivo,
                    "tipo_documento": tipo_doc,
                    "area": bloque["departamento"],
                    "codigo": match.group("codigo"),
                    "descripcion": match.group("descripcion"),
                    "cantidad": a_float(match.group("cantidad")),
                    "precio_unitario": a_float(match.group("precio")),
                    "subtotal": a_float(match.group("subtotal")),
                    "fecha": fecha,
                    "folio": folio,
                    "linea_original": linea_compacta,
                }
            )

    return items
