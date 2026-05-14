import re
from datetime import datetime

from core.utils import normalizar, compact


def extraer_cuenta(texto: str) -> str:
    m = re.search(r"\bNC\d{5,}\b", texto, re.IGNORECASE)
    if m:
        return m.group(0).upper()

    m = re.search(r"Cuenta[:\s]+(NC\d+)", texto, re.IGNORECASE)
    if m:
        return m.group(1).upper()

    return "SIN_CUENTA"


def extraer_paciente(texto: str) -> str:
    nombre_crudo = None

    m = re.search(
        r"Nombre Paciente\s+Fecha nacimiento:.*?\n(.+?)\n(?:Medico|Médico)",
        texto,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        nombre_crudo = compact(m.group(1))

    if not nombre_crudo:
        m = re.search(
            r"Nombre:\s*(.+?)\s*Fecha de nacimiento:",
            texto,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            nombre_crudo = compact(m.group(1))

    if not nombre_crudo:
        return "No identificado"

    nombre_limpio = re.split(
        r"\s+\d{2,4}[-/]\d{2}[-/]\d{2,4}",
        nombre_crudo,
    )[0]

    nombre_limpio = re.sub(
        r"\s+\d+\s+AÑO[S]?.*$",
        "",
        nombre_limpio,
        flags=re.IGNORECASE,
    )

    return compact(nombre_limpio).title()


def extraer_fechas_estancia(texto: str):
    m = re.search(
        r"(\d{2}-\d{2}-\d{4})\s+\d{2}:\d{2}:\d{2}\s+(\d{2}-\d{2}-\d{4})\s+\d{2}:\d{2}:\d{2}",
        texto,
    )

    if m:
        try:
            fmt = "%d-%m-%Y"
            ingreso = datetime.strptime(m.group(1), fmt)
            egreso = datetime.strptime(m.group(2), fmt)
            dias = (egreso - ingreso).days
            return m.group(1), m.group(2), dias
        except Exception:
            pass

    return None, None, None


def extraer_tipo_seguro(texto: str) -> str:
    """
    Extrae el tipo de seguro desde estado de cuenta o servicios de cirugía.
    """
    for linea in texto.splitlines():
        n = normalizar(linea.strip())

        m = re.match(r"seguro:\s*(.+)", n)
        if m:
            seguro = m.group(1).strip()
            if "particular" in seguro:
                return "particular"
            return seguro

    lineas = texto.splitlines()

    for i, linea in enumerate(lineas):
        if re.search(r"Cia\.?\s*Cliente", linea, re.IGNORECASE):
            resto = re.sub(
                r".*Cia\.?\s*Cliente\s*",
                "",
                linea,
                flags=re.IGNORECASE,
            ).strip()

            if not resto and i + 1 < len(lineas):
                resto = lineas[i + 1].strip()

            if resto:
                n = normalizar(resto)
                if "particular" in n:
                    return "particular"
                return resto.strip()[:60]

    return "desconocido"


def detectar_tipo_documento(texto: str) -> str:
    t = normalizar(texto)

    if "servicios de cirugia" in t:
        return "servicios_cirugia"

    if "nota post-quirurgica" in t or "nota postquirurgica" in t:
        return "nota_postquirurgica"

    if "estado de cuenta" in t:
        corte = re.search(r"estado de cuenta corte a:\s*([a-z]+)", t)
        if corte:
            return f"estado_cuenta_{corte.group(1).upper()}"
        return "estado_cuenta"

    return "otro"


def canonical_depto(nombre: str) -> str:
    n = normalizar(nombre)

    if "quirofano" in n:
        return "quirofano"

    if "recuperacion" in n:
        return "recuperacion"

    if "hospitalizacion" in n:
        return "hospitalizacion"

    if "caja" in n:
        return "caja"

    return "otro"
