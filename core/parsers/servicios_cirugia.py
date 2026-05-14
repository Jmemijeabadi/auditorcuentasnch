import re
from datetime import datetime

from core.config_codigos import SERVICIOS_BINARIOS_DEF
from core.utils import normalizar, compact, a_float


def parsear_hora_ampm(texto: str):
    """
    Parsea horas tipo:
    - 09:55 AM
    - 02:41 PM
    - 09:55AM
    - 14:30
    """
    texto = str(texto or "").strip().upper()

    for formato in ("%I:%M %p", "%I:%M%p", "%H:%M"):
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue

    return None


def calcular_horas_minuto21(ingreso_str: str, egreso_str: str):
    """
    Calcula horas a cobrar aplicando regla del minuto 21.

    Regla:
    - A partir del minuto 21 se cobra la siguiente hora completa.
    - Siempre se cobra mínimo 1 hora.

    Retorna:
    - horas_calculadas
    - minutos_totales
    """
    t_ingreso = parsear_hora_ampm(ingreso_str)
    t_egreso = parsear_hora_ampm(egreso_str)

    if not t_ingreso or not t_egreso:
        return None, None

    diff_min = (t_egreso - t_ingreso).total_seconds() / 60

    if diff_min < 0:
        diff_min += 24 * 60

    horas_completas = int(diff_min // 60)
    minutos_restantes = diff_min % 60

    if minutos_restantes >= 21:
        horas_completas += 1

    horas_calculadas = max(horas_completas, 1)

    return horas_calculadas, diff_min


def extraer_servicios_cirugia(texto: str) -> dict:
    t_norm = normalizar(compact(texto))

    resultado = {
        "hora_total_qx": None,
        "sala_hrs_normal": 0.0,
        "sala_hrs_adicional": 0.0,
        "oxigeno_qx": 0.0,
        "oxigeno_rec": 0.0,
        "sevoflurano_ml": None,
        "servicios_marcados": {},
        "evidencias_oxigeno": [],
        "ingreso_sala": None,
        "egreso_sala": None,
        "horas_calculadas_m21": None,
        "minutos_totales": None,
        "seguro": None,
        "maquina_anestesia": False,
        "arco_c_hrs": None,
        "microscopio": False,
    }

    # Hora total quirófano
    match = re.search(
        r"hora total de quirofano:\s*(\d+(?:\.\d+)?)\s*hrs?",
        t_norm,
    )
    if match:
        resultado["hora_total_qx"] = a_float(match.group(1))

    # Sala de cirugía — primera hora
    match = re.search(
        r"\bx\s+sala de cirugia x hr\s+(\d+(?:\.\d+)?)\s*hrs?",
        t_norm,
    )
    if match:
        resultado["sala_hrs_normal"] = a_float(match.group(1))

    # Sala de cirugía — horas adicionales
    match = re.search(
        r"\bx\s+sala de cirugia adicional\s+(\d+(?:\.\d+)?)\s*hrs?",
        t_norm,
    )
    if match:
        resultado["sala_hrs_adicional"] = a_float(match.group(1))

    # Oxígeno QX y recuperación
    for linea in texto.splitlines():
        linea_original = compact(linea)
        linea_norm = normalizar(linea_original)

        match = re.search(
            r"oxigeno x hr\s+(\d+(?:\.\d+)?)\s*hrs?",
            linea_norm,
        )
        if match:
            horas = a_float(match.group(1))
            resultado["oxigeno_qx"] += horas
            resultado["evidencias_oxigeno"].append(
                {
                    "area": "quirofano",
                    "cantidad_esperada": horas,
                    "linea_original": linea_original,
                }
            )

        match = re.search(
            r"oxigeno recuperacion\s+(\d+(?:\.\d+)?)\s*hrs?",
            linea_norm,
        )
        if match:
            horas = a_float(match.group(1))
            resultado["oxigeno_rec"] += horas
            resultado["evidencias_oxigeno"].append(
                {
                    "area": "recuperacion",
                    "cantidad_esperada": horas,
                    "linea_original": linea_original,
                }
            )

    # Sevoflurano
    match = re.search(
        r"\bx\s+sevoflorane?\s+([\d,.]+)\s*ml",
        t_norm,
    )
    if match:
        resultado["sevoflurano_ml"] = a_float(match.group(1))

    # Ingreso y egreso de sala
    match = re.search(
        r"ingreso a sala:\s*(\d{1,2}:\d{2}\s*[ap]m)\s+(\d{1,2}:\d{2}\s*[ap]m)",
        t_norm,
    )
    if match:
        resultado["ingreso_sala"] = match.group(1).strip()
        resultado["egreso_sala"] = match.group(2).strip()

        horas_calc, minutos = calcular_horas_minuto21(
            resultado["ingreso_sala"],
            resultado["egreso_sala"],
        )

        resultado["horas_calculadas_m21"] = horas_calc
        resultado["minutos_totales"] = minutos

    # Tipo de seguro
    match = re.search(
        r"seguro:\s*(.+?)(?:cirugia programada|cirugia realizada)",
        t_norm,
    )
    if match:
        seguro = match.group(1).strip()
        resultado["seguro"] = "particular" if "particular" in seguro else seguro

    # Máquina de anestesia
    resultado["maquina_anestesia"] = bool(
        re.search(r"\bx\s+maquina de anestesia", t_norm)
    )

    # Microscopio
    resultado["microscopio"] = bool(
        re.search(r"\bx\s+microscopio", t_norm)
    )

    # Arco en C horas
    match = re.search(
        r"\bx\s+arco en c\s+(\d+(?:\.\d+)?)\s*hrs?",
        t_norm,
    )
    if match:
        resultado["arco_c_hrs"] = a_float(match.group(1))

    # Servicios binarios
    for key, label, patron, _, _ in SERVICIOS_BINARIOS_DEF:
        resultado["servicios_marcados"][key] = bool(
            re.search(patron, t_norm)
        )

    return resultado
