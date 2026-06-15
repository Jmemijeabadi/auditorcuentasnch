import streamlit as st
import pdfplumber
import pandas as pd
import re
import unicodedata
import smtplib
import hashlib
import traceback
import logging
from html import escape
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from collections import defaultdict

st.set_page_config(page_title="Auditor Hospitalario", layout="wide", page_icon="🏥")

# Versión corregida con base en observaciones de auditoría:
# - Oxígeno QX se valida contra cargos QRF reales en estado de cuenta.
# - Oxígeno recuperación se mantiene separado.
# - Casilla azul de oxígeno queda como aviso documental, no diferencia financiera.
# - Sevoflurano queda como verificación clínica/anestesia, no error automático.
# - Parser de tiempo quirúrgico reconoce “horas”.
# - Habitación ambulatoria espera 1 cargo aunque la estancia calculada sea 0 días.
# - Hemotransfusión con SÍ en nota queda como verificación médica, no diferencia financiera automática.
# - Bomba de infusión vs equipo infusomat se valida por cantidades, no solo por existencia.
# - Mejor redacción para máquina de anestesia en particulares vs convenio/seguro.
# - Catálogo NCH de aseguradoras para no clasificar como seguro textos desconocidos.
# - Máquina de anestesia solo aplica cuando el pagador coincide con aseguradora NCH.
# - RPBI diferenciado: particulares con cargo inicial + adicional cada 7 días; seguros NCH con cargo diario.
# - Catálogo de códigos monitoreados: los cargos se validan por código; la descripción solo genera alerta de posible código nuevo.

# =========================================================
# CSS GLOBAL
# =========================================================
st.markdown("""
<style>
.cuenta-card{display:flex;align-items:center;gap:12px;padding:12px 16px;
  border:0.5px solid var(--color-border-tertiary);border-radius:10px;
  background:var(--color-background-primary);margin-bottom:8px}
.dot{width:11px;height:11px;border-radius:50%;flex-shrink:0}
.dot-ok{background:#639922}.dot-warn{background:#EF9F27}
.dot-err{background:#E24B4A}.dot-gray{background:#888780}
.badge{display:inline-flex;align-items:center;font-size:11px;font-weight:500;
  padding:3px 9px;border-radius:20px;white-space:nowrap}
.badge-ok{background:#EAF3DE;color:#27500A}
.badge-warn{background:#FAEEDA;color:#633806}
.badge-err{background:#FCEBEB;color:#791F1F}
.badge-gray{background:#F1EFE8;color:#444441}
.bar-wrap{background:#e8e8e4;border-radius:4px;height:9px;width:100%;overflow:hidden;margin:3px 0 2px}
.bar-fill{height:100%;border-radius:4px}
.bar-ok{background:#639922}.bar-warn{background:#EF9F27}
.bar-err{background:#E24B4A}.bar-gray{background:#888780}
.cat-title{font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:.07em;
  color:var(--color-text-tertiary);margin:16px 0 6px;padding-bottom:4px;
  border-bottom:0.5px solid var(--color-border-tertiary)}
.audit-row{padding:10px 0;border-bottom:0.5px solid var(--color-border-tertiary)}
.audit-row:last-child{border-bottom:none}
.audit-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:3px}
.audit-label{font-size:13px;font-weight:500}
.audit-sub{font-size:11px;color:var(--color-text-secondary);margin-top:2px;line-height:1.5}
.finding-box{border-left:3px solid;padding:8px 12px;border-radius:0 6px 6px 0;
  font-size:13px;margin-bottom:6px}
.finding-err{border-color:#E24B4A;background:#FCEBEB;color:#791F1F}
.finding-warn{border-color:#EF9F27;background:#FAEEDA;color:#633806}
.finding-ok{border-color:#639922;background:#EAF3DE;color:#27500A}
.finding-gray{border-color:#888780;background:#F1EFE8;color:#444441}
.ev-table{width:100%;border-collapse:collapse;font-size:12px}
.ev-table th{text-align:left;padding:5px 8px;
  background:var(--color-background-tertiary);
  border-bottom:0.5px solid var(--color-border-tertiary);
  font-weight:500;color:var(--color-text-secondary)}
.ev-table td{padding:5px 8px;border-bottom:0.5px solid var(--color-border-tertiary)}
.ev-table tr:last-child td{border-bottom:none}
.mono{font-family:var(--font-mono);font-size:11px}


/* ================= FRONTEND V2: lectura para auditor ================= */
.kpi-card{border:1px solid var(--color-border-tertiary);border-radius:14px;
  padding:14px 16px;background:var(--color-background-primary);height:100%;
  box-shadow:0 1px 2px rgba(0,0,0,.03)}
.kpi-label{font-size:11px;text-transform:uppercase;letter-spacing:.06em;
  color:var(--color-text-tertiary);font-weight:600;margin-bottom:4px}
.kpi-value{font-size:25px;font-weight:700;line-height:1.1;color:var(--color-text-primary)}
.kpi-sub{font-size:11px;color:var(--color-text-secondary);margin-top:5px;line-height:1.35}
.ux-card{border:1px solid var(--color-border-tertiary);border-radius:14px;
  padding:13px 16px;background:var(--color-background-primary);margin-bottom:10px}
.ux-card:hover{box-shadow:0 2px 8px rgba(0,0,0,.05)}
.ux-card-top{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
.ux-title{font-size:14px;font-weight:700;color:var(--color-text-primary)}
.ux-subtitle{font-size:12px;color:var(--color-text-secondary);line-height:1.45;margin-top:3px}
.ux-meta{font-size:11px;color:var(--color-text-tertiary);margin-top:6px;line-height:1.45}
.ux-pill{display:inline-flex;align-items:center;font-size:11px;font-weight:600;
  padding:3px 8px;border-radius:999px;margin:2px 4px 2px 0;white-space:nowrap}
.ux-pill-red{background:#FCEBEB;color:#791F1F}.ux-pill-yellow{background:#FAEEDA;color:#633806}
.ux-pill-blue{background:#EAF2FF;color:#174A7C}.ux-pill-green{background:#EAF3DE;color:#27500A}
.ux-pill-gray{background:#F1EFE8;color:#444441}.ux-pill-dark{background:#ECECEC;color:#222}
.badge-blue{background:#EAF2FF;color:#174A7C}.dot-blue{background:#2F74B5}
.finding-blue{border-color:#2F74B5;background:#EAF2FF;color:#174A7C}
.audit-card{border:1px solid var(--color-border-tertiary);border-radius:12px;
  padding:12px 14px;margin-bottom:10px;background:var(--color-background-primary)}
.audit-card-red{border-left:4px solid #E24B4A}.audit-card-yellow{border-left:4px solid #EF9F27}
.audit-card-blue{border-left:4px solid #2F74B5}.audit-card-green{border-left:4px solid #639922}
.audit-card-gray{border-left:4px solid #888780}
.audit-card-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:6px}
.audit-card-title{font-size:14px;font-weight:700;color:var(--color-text-primary)}
.audit-card-result{font-size:12px;line-height:1.45;color:var(--color-text-secondary);margin-top:4px}
.audit-card-note{font-size:12px;line-height:1.45;color:var(--color-text-secondary);
  background:var(--color-background-tertiary);border-radius:8px;padding:8px 10px;margin-top:8px}
.section-title-red{color:#791F1F}.section-title-yellow{color:#633806}
.section-title-blue{color:#174A7C}.section-title-green{color:#27500A}.section-title-gray{color:#444441}
.account-row{border:1px solid var(--color-border-tertiary);border-radius:14px;padding:12px 14px;
  background:var(--color-background-primary);margin-bottom:8px}
.account-row-head{display:flex;align-items:center;gap:10px;justify-content:space-between}
.account-main{display:flex;align-items:center;gap:10px;min-width:0}.account-title{font-size:14px;font-weight:700}
.account-sub{font-size:12px;color:var(--color-text-secondary);margin-top:2px}
.account-badges{text-align:right;min-width:fit-content}.muted-small{font-size:11px;color:var(--color-text-tertiary)}

</style>
""", unsafe_allow_html=True)

# =========================================================
# CONSTANTES
# =========================================================
CODIGOS_OXIGENO = {"APR-0000003"}

# Códigos QRF para sala de quirófano
CODIGO_SALA_NORMAL    = "QRF-0000002"   # primera hora
CODIGO_SALA_ADICIONAL = "QRF-0000001"   # horas adicionales

# Sevoflurano
CODIGO_SEVOFLURANO = "FAR-0000069"

# ── PUNTO 2: Máquina de anestesia ─────────────────────────
# No existe un código de cargo específico identificado aún;
# se audita verificando si el servicio está marcado y el tipo de seguro.

# ── PUNTO 8: Accesorios de electrocauterio ────────────────
CODIGO_ELECTROCAUTERIO = "IBM-0000032"
CODIGO_LAPIZ_ELECTRO   = "ALM-0001320"
CODIGO_PLACA_ELECTRO   = "ALM-0000753"

# ── PUNTO 9: Accesorio de bomba de infusión ───────────────
CODIGO_BOMBA           = "IBM-0000001"
CODIGO_EQUIPO_INFUSOMAT = "ALM-0000869"

# ── PUNTO 10: Microscopio y funda ─────────────────────────
CODIGO_MICROSCOPIO       = "IBM-0000034"
CODIGO_FUNDA_MICROSCOPIO = "ALM-0000878"

# ── PUNTO 11: Arco en C y funda ───────────────────────────
# Regla de seguridad: los cargos financieros se validan por código.
# IBM-0000023 = USO DE ARCO EN C + 120 MIN.
# IBM-0000026 = USO DE ARCO EN C 90 - 120 MIN.
CODIGOS_ARCO_C      = {"IBM-0000023", "IBM-0000026"}
CODIGO_FUNDA_ARCO_C = "ALM-0000877"

# ── PUNTO 6: RPBI ─────────────────────────────────────────
CODIGO_RPBI = "ENF-0000003"
DIAS_RPBI_ADICIONAL = 7

# ── Catálogo NCH de aseguradoras ─────────────────────────
# Regla operativa:
# - Solo estos pagadores se consideran seguro para reglas diferenciadas.
# - Todo texto no reconocido se clasifica como particular/no aseguradora NCH.
ASEGURADORAS_NCH = {
    "GNP",
    "ATLAS",
    "ALLIANZ",
    "AXA",
    "BX+",
    "BUPA GLOBAL",
    "GEOBLUE",
    "GLOBAL REACH",
    "KAISER",
    "MONTERREY",
    "METLIFE",
    "MMS",
    "MAWDY",
    "MEXICO ASISTENCIA",
    "MONTE DE PIEDAD",
    "OMA",
    "PAN-AMERICAN",
    "PREVEM",
    "REDGRIDGE",
    "SURA",
    "SOFIA",
    "ZURICH",
}

# Aliases opcionales para hacer más robusta la detección si el PDF extrae
# variantes, acentos, guiones o nombres comerciales incompletos.
ASEGURADORAS_NCH_ALIASES = {
    "BUPA": "BUPA GLOBAL",
    "BUPA GLOBAL": "BUPA GLOBAL",
    "GEO BLUE": "GEOBLUE",
    "GEOBLUE": "GEOBLUE",
    "GLOBAL REACH": "GLOBAL REACH",
    "MEXICO ASISTENCIA": "MEXICO ASISTENCIA",
    "MÉXICO ASISTENCIA": "MEXICO ASISTENCIA",
    "MONTE DE PIEDAD": "MONTE DE PIEDAD",
    "PAN AMERICAN": "PAN-AMERICAN",
    "PAN-AMERICAN": "PAN-AMERICAN",
    "RED BRIDGE": "REDGRIDGE",
    "REDBRIDGE": "REDGRIDGE",
    "REDGRIDGE": "REDGRIDGE",
}

# Sangre / hemoderivados — palabras clave en descripción
PALABRAS_SANGRE = {
    "paquete globular","plasma fresco","plaquetas","sangre total",
    "concentrado eritrocitario","hemoderivado","eritrocito",
    "globulos rojos","crioprecipitado",
}

# Patología — palabras clave en descripción
PALABRAS_PATOLOGIA = {
    "patologia","histopatolog","biopsia","estudio histol",
}

# Habitación — incluye STANDARD y AMBULATORIA
CODIGOS_HABITACION = {"HOS-0000001", "HOS-0000003"}

# Servicios binarios: (key, label, patron_en_servicios, codigos_en_cuenta, area_cuenta)
SERVICIOS_BINARIOS_DEF = [
    ("electrocauterio", "Electrocauterio",
     r"\bx\s+electrocauterio",
     {"IBM-0000032"}, "quirofano"),
    ("aspirador", "Torre de aspiración",
     r"\bx\s+torre de aspiracion",
     {"IBM-0000008"}, "quirofano"),
    ("monitor_qx", "Monitor QX",
     r"\bx\s+monitor sv\s*qx",
     {"IBM-0000035"}, "quirofano"),
    ("sala_rec", "Sala de recuperación",
     r"\bx\s+sala de recuperacion\b",
     {"REC-0000001"}, "recuperacion"),
    ("monitor_rec", "Monitor SV recuperación",
     r"\bx\s+monitor sv recuperacion",
     {"IBM-0000010"}, "recuperacion"),
    # ── PUNTO 10: Microscopio ─────────────────────────────
    ("microscopio", "Microscopio-TIVATO",
     r"\bx\s+microscopio",
     {"IBM-0000034"}, "quirofano"),
    # ── PUNTO 11: Arco en C ──────────────────────────────
    ("arco_c", "Arco en C",
     r"\bx\s+arco en c",
     CODIGOS_ARCO_C, "quirofano"),
]


# =========================================================
# CATÁLOGO MONITOREADO PARA ALERTAS DE CÓDIGO NUEVO
# =========================================================
# Regla operativa:
# - La validación financiera se hace por código.
# - La descripción NO se usa para dar por válido un cargo.
# - La descripción solo sirve para avisar que posiblemente apareció un
#   código nuevo que debe agregarse manualmente al catálogo.
# - Mantener los patrones lo más específicos posible para reducir falsos positivos.
CATALOGO_ALERTAS_DEF = [
    {
        "key": "oxigeno_por_hora",
        "label": "Oxígeno por hora",
        "codigos": CODIGOS_OXIGENO,
        "area": None,
        "patrones_desc": [r"\boxigeno por hora\b"],
    },
    {
        "key": "sala_cirugia_primera_hora",
        "label": "Sala de cirugía primera hora",
        "codigos": {CODIGO_SALA_NORMAL},
        "area": "quirofano",
        "patrones_desc": [r"\bsala de cirugia general una hora\b", r"\bsala de cirugia x hr\b"],
    },
    {
        "key": "sala_cirugia_adicional",
        "label": "Sala de cirugía adicional",
        "codigos": {CODIGO_SALA_ADICIONAL},
        "area": "quirofano",
        "patrones_desc": [r"\bsala de cirugia general por hora adicional\b", r"\bsala de cirugia adicional\b"],
    },
    {
        "key": "sevoflurano",
        "label": "Sevoflurano",
        "codigos": {CODIGO_SEVOFLURANO},
        "area": "quirofano",
        "patrones_desc": [r"\bsevoflurano\b", r"\bsevoflorane\b"],
    },
    {
        "key": "electrocauterio",
        "label": "Electrocauterio",
        "codigos": {CODIGO_ELECTROCAUTERIO},
        "area": "quirofano",
        "patrones_desc": [r"\buso de electrocauterio\b"],
    },
    {
        "key": "lapiz_electrocauterio",
        "label": "Lápiz de electrocauterio",
        "codigos": {CODIGO_LAPIZ_ELECTRO},
        "area": "quirofano",
        "patrones_desc": [r"\blapiz p/?electrocauterio\b", r"\blapiz.*electrocauterio\b"],
    },
    {
        "key": "placa_electrocauterio",
        "label": "Placa de electrocauterio",
        "codigos": {CODIGO_PLACA_ELECTRO},
        "area": "quirofano",
        "patrones_desc": [r"\bplaca p/?electrocauterio\b", r"\bplaca.*electrocauterio\b"],
    },
    {
        "key": "bomba_infusion",
        "label": "Bomba de infusión",
        "codigos": {CODIGO_BOMBA},
        "area": None,
        "patrones_desc": [r"\buso bomba de infusion\b", r"\bbomba de infusion\b"],
    },
    {
        "key": "equipo_infusomat",
        "label": "Equipo infusomat",
        "codigos": {CODIGO_EQUIPO_INFUSOMAT},
        "area": None,
        "patrones_desc": [r"\bequipo para bomba infusomat\b", r"\binfusomat\b"],
    },
    {
        "key": "microscopio",
        "label": "Microscopio",
        "codigos": {CODIGO_MICROSCOPIO},
        "area": "quirofano",
        "patrones_desc": [r"\bmicroscopio quirurgico\b", r"\bmicroscopio\b"],
    },
    {
        "key": "funda_microscopio",
        "label": "Funda de microscopio",
        "codigos": {CODIGO_FUNDA_MICROSCOPIO},
        "area": "quirofano",
        "patrones_desc": [r"\bfunda.*microscopio\b"],
    },
    {
        "key": "arco_c",
        "label": "Arco en C",
        "codigos": CODIGOS_ARCO_C,
        "area": "quirofano",
        # IMPORTANTE: no usar r"\barco en c\b" genérico porque también coincide
        # con "FUNDA ESTERIL P/ARCO EN C DESECHABLE".
        # La alerta de código nuevo para Arco en C solo debe detonar cuando parezca
        # el cargo principal del equipo, no sus accesorios.
        "patrones_desc": [r"^uso de arco en c\b"],
        "excluir_codigos": {CODIGO_FUNDA_ARCO_C},
    },
    {
        "key": "funda_arco_c",
        "label": "Funda de Arco en C",
        "codigos": {CODIGO_FUNDA_ARCO_C},
        "area": "quirofano",
        "patrones_desc": [r"\bfunda.*arco en c\b"],
    },
    {
        "key": "rpbi",
        "label": "Disposición de RPBI",
        "codigos": {CODIGO_RPBI},
        "area": None,
        "patrones_desc": [r"\bdisposicion de r\.?p\.?b\.?i\.?\b", r"\brpbi\b"],
    },
    {
        "key": "habitacion_standard",
        "label": "Habitación standard",
        "codigos": {"HOS-0000001"},
        "area": "hospitalizacion",
        "patrones_desc": [r"\bhabitacion standard\b"],
    },
    {
        "key": "habitacion_ambulatoria",
        "label": "Habitación ambulatoria",
        "codigos": {"HOS-0000003"},
        "area": "hospitalizacion",
        "patrones_desc": [r"\bhabitacion ambulatoria\b"],
    },
    {
        "key": "aspirador",
        "label": "Torre de aspiración / aspirador",
        "codigos": {"IBM-0000008"},
        "area": "quirofano",
        "patrones_desc": [r"\baspirador por evento\b", r"\btorre de aspiracion\b"],
    },
    {
        "key": "monitor_qx",
        "label": "Monitor QX",
        "codigos": {"IBM-0000035"},
        "area": "quirofano",
        "patrones_desc": [r"\bmonitor quirofano\b", r"\bmonitor signos vitales\b", r"\bblood pressure\b"],
    },
    {
        "key": "sala_recuperacion",
        "label": "Sala de recuperación",
        "codigos": {"REC-0000001"},
        "area": "recuperacion",
        "patrones_desc": [r"\bsala de recuperacion\b"],
    },
    {
        "key": "monitor_recuperacion",
        "label": "Monitor SV recuperación",
        "codigos": {"IBM-0000010"},
        "area": "recuperacion",
        "patrones_desc": [r"\bmonitor signos vitales\b", r"\bblood pressure\b", r"\bmonitor sv recuperacion\b"],
    },
]

# =========================================================
# UTILIDADES
# =========================================================
def normalizar(texto: str) -> str:
    texto = texto.lower()
    texto = "".join(c for c in unicodedata.normalize("NFD", texto)
                    if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[ \t]+", " ", texto)
    return texto

def compact(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()

def normalizar_pagador(texto: str) -> str:
    """Normaliza nombres de pagador/aseguradora para comparación robusta."""
    t = normalizar(texto or "")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return compact(t)

def identificar_aseguradora_nch(texto: str):
    """
    Devuelve el nombre canónico de la aseguradora si el texto contiene
    una aseguradora del catálogo NCH. Si no, devuelve None.
    """
    n = normalizar_pagador(texto)
    if not n:
        return None

    # Primero revisar alias para capturar variantes comunes del PDF.
    for alias, canonico in ASEGURADORAS_NCH_ALIASES.items():
        a = normalizar_pagador(alias)
        if re.search(rf"(^|\s){re.escape(a)}($|\s)", n):
            return canonico

    # Después revisar catálogo oficial.
    for aseguradora in ASEGURADORAS_NCH:
        a = normalizar_pagador(aseguradora)
        if re.search(rf"(^|\s){re.escape(a)}($|\s)", n):
            return aseguradora

    return None

def clasificar_pagador_nch(texto: str) -> str:
    """
    Clasificación operativa para mostrar y auditar:
    - Si contiene PARTICULAR => particular.
    - Si coincide con catálogo NCH => nombre canónico de aseguradora.
    - Si no coincide con catálogo NCH => conserva el texto del pagador,
      pero NO activa reglas de seguro.

    Esto evita que cualquier texto desconocido se trate como seguro,
    sin ocultar casos como CONVENIO - MÉDICOS en la tarjeta/reporte.
    """
    n = normalizar_pagador(texto)

    if not n:
        return "desconocido"

    if "particular" in n:
        return "particular"

    aseguradora = identificar_aseguradora_nch(texto)
    if aseguradora:
        return aseguradora

    # No es aseguradora NCH. Se conserva el pagador para visibilidad,
    # pero es_seguro_nch() seguirá regresando False.
    return compact(str(texto or "")).strip()[:80] or "desconocido"

def es_seguro_nch(valor: str) -> bool:
    """True solo si el valor coincide con una aseguradora del catálogo NCH."""
    return identificar_aseguradora_nch(valor) is not None

def h(valor) -> str:
    """Escapa texto para render HTML seguro en Streamlit/reportes."""
    return escape(str(valor or ""), quote=True)

def a_float(valor) -> float:
    try:
        return float(str(valor).replace(",", "").strip())
    except Exception:
        return 0.0

def extraer_texto_pdf(archivo_pdf) -> str:
    archivo_pdf.seek(0)
    partes = []
    try:
        with pdfplumber.open(archivo_pdf) as pdf:
            for i, pag in enumerate(pdf.pages, 1):
                t = pag.extract_text()
                if t:
                    partes.append(t)
                else:
                    st.warning(f"⚠️ '{getattr(archivo_pdf,'name','?')}' pág {i} sin texto.")
    except Exception as e:
        st.error(f"❌ Error leyendo '{getattr(archivo_pdf,'name','?')}': {e}")
    return "\n".join(partes)

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
        texto, re.IGNORECASE | re.DOTALL)
    if m:
        nombre_crudo = compact(m.group(1))
    if not nombre_crudo:
        m = re.search(r"Nombre:\s*(.+?)\s*Fecha de nacimiento:",
                      texto, re.IGNORECASE | re.DOTALL)
        if m:
            nombre_crudo = compact(m.group(1))
    if not nombre_crudo:
        return "No identificado"
    nombre_limpio = re.split(r"\s+\d{2,4}[-/]\d{2}[-/]\d{2,4}", nombre_crudo)[0]
    nombre_limpio = re.sub(r"\s+\d+\s+AÑO[S]?.*$", "", nombre_limpio, flags=re.IGNORECASE)
    return compact(nombre_limpio).title()

def extraer_fechas_estancia(texto: str):
    m = re.search(
        r"(\d{2}-\d{2}-\d{4})\s+\d{2}:\d{2}:\d{2}\s+(\d{2}-\d{2}-\d{4})\s+\d{2}:\d{2}:\d{2}",
        texto)
    if m:
        try:
            fmt = "%d-%m-%Y"
            ing = datetime.strptime(m.group(1), fmt)
            egr = datetime.strptime(m.group(2), fmt)
            dias = (egr - ing).days
            return m.group(1), m.group(2), dias
        except Exception:
            pass
    return None, None, None

def extraer_tipo_seguro(texto: str) -> str:
    """Extrae y clasifica el pagador como particular o aseguradora NCH."""
    candidatos = []

    # Desde servicios de cirugía: "Seguro: PARTICULAR NACIONAL" o aseguradora.
    for linea in texto.splitlines():
        n = normalizar(linea.strip())
        m = re.match(r"seguro:\s*(.+)", n)
        if m:
            candidatos.append(m.group(1).strip())

    # Desde estado de cuenta: buscar línea después de "Cia. Cliente".
    lineas = texto.splitlines()
    for i, linea in enumerate(lineas):
        if re.search(r"Cia\.?\s*Cliente", linea, re.IGNORECASE):
            resto = re.sub(
                r".*Cia\.?\s*Cliente\s*",
                "",
                linea,
                flags=re.IGNORECASE
            ).strip()

            if not resto and i + 1 < len(lineas):
                resto = lineas[i + 1].strip()

            if resto:
                candidatos.append(resto)

    for candidato in candidatos:
        clasificado = clasificar_pagador_nch(candidato)
        if clasificado != "desconocido":
            return clasificado

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
    if "quirofano" in n:     return "quirofano"
    if "recuperacion" in n:  return "recuperacion"
    if "hospitalizacion" in n: return "hospitalizacion"
    if "caja" in n:           return "caja"
    return "otro"

# =========================================================
# PUNTO 1 y 7: Cálculo de horas con regla del minuto 21
# =========================================================
def parsear_hora_ampm(texto: str):
    """Parsea '09:55 AM' o '02:41 PM' a un objeto datetime.time."""
    texto = texto.strip().upper()
    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
        try:
            return datetime.strptime(texto, fmt)
        except ValueError:
            continue
    return None

def calcular_horas_minuto21(ingreso_str: str, egreso_str: str):
    """
    Calcula horas a cobrar aplicando regla del minuto 21.
    A partir del minuto 21 se cobra la siguiente hora completa.
    Retorna (horas_calculadas, minutos_totales) o (None, None).
    """
    t_in = parsear_hora_ampm(ingreso_str)
    t_eg = parsear_hora_ampm(egreso_str)
    if not t_in or not t_eg:
        return None, None
    diff_min = (t_eg - t_in).total_seconds() / 60
    if diff_min < 0:
        diff_min += 24 * 60  # cruce de medianoche
    horas_completas = int(diff_min // 60)
    minutos_restantes = diff_min % 60
    if minutos_restantes >= 21:
        horas_completas += 1
    horas_calculadas = max(horas_completas, 1)  # mínimo 1 hora
    return horas_calculadas, diff_min

# =========================================================
# REGEX ÍTEMS
# =========================================================
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
    r"(?:\s+(?P<factura>\S+))?$",   # NCTA-XXXX y similares (campo Factura)
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
    for i, m in enumerate(matches):
        inicio = m.end()
        fin = matches[i+1].start() if i+1 < len(matches) else len(texto)
        bloques.append({
            "encabezado": m.group(1).strip(),
            "departamento": canonical_depto(m.group(1)),
            "contenido": texto[inicio:fin],
        })
    return bloques

# =========================================================
# EXTRACCIÓN COMPLETA DEL ESTADO DE CUENTA
# =========================================================
def extraer_todos_items(texto: str, nombre_archivo: str, tipo_doc: str, cuenta: str) -> list:
    items = []
    for bloque in _bloque_departamentos(texto):
        if bloque["departamento"] == "caja":
            continue
        for linea in bloque["contenido"].splitlines():
            lc = compact(linea)
            if not lc:
                continue
            m = ITEM_RE.match(lc)
            if not m:
                continue
            fecha, folio = _parsear_ff(m.group("fecha_folio"), m.group("folio2"))
            items.append({
                "cuenta":        cuenta,
                "archivo":       nombre_archivo,
                "tipo_documento": tipo_doc,
                "area":          bloque["departamento"],
                "codigo":        m.group("codigo"),
                "descripcion":   m.group("descripcion"),
                "cantidad":      a_float(m.group("cantidad")),
                "precio_unitario": a_float(m.group("precio")),
                "subtotal":      a_float(m.group("subtotal")),
                "fecha":         fecha,
                "folio":         folio,
                "linea_original": lc,
            })
    return items

# =========================================================
# EXTRACCIÓN DE SERVICIOS DE CIRUGÍA (ampliada)
# =========================================================
def extraer_servicios_cirugia(texto: str) -> dict:
    t_norm  = normalizar(compact(texto))
    t_multi = normalizar(texto)

    resultado = {
        "hora_total_qx":      None,
        "sala_hrs_normal":    0.0,
        "sala_hrs_adicional": 0.0,
        "oxigeno_qx":         0.0,
        "oxigeno_rec":         0.0,
        "sevoflurano_ml":     None,
        "servicios_marcados": {},
        "evidencias_oxigeno": [],
        # ── Nuevos campos ─────────────────────────────────
        "ingreso_sala":       None,   # Punto 1/7
        "egreso_sala":        None,   # Punto 1/7
        "horas_calculadas_m21": None, # Punto 1/7: horas según regla minuto 21
        "minutos_totales":    None,   # Punto 1/7
        "seguro":             None,   # Punto 2
        "maquina_anestesia":  False,  # Punto 2
        "arco_c_hrs":         None,   # Punto 11
        "microscopio":        False,  # Punto 10
    }

    # ── Hora total quirófano (Punto 3) ────────────────────
    m = re.search(r"hora total de quirofano:\s*(\d+(?:\.\d+)?)\s*hrs?", t_norm)
    if m:
        resultado["hora_total_qx"] = a_float(m.group(1))

    # ── Sala de cirugía — primera hora y adicionales ──────
    m = re.search(r"\bx\s+sala de cirugia x hr\s+(\d+(?:\.\d+)?)\s*hrs?", t_norm)
    if m:
        resultado["sala_hrs_normal"] = a_float(m.group(1))

    m = re.search(r"\bx\s+sala de cirugia adicional\s+(\d+(?:\.\d+)?)\s*hrs?", t_norm)
    if m:
        resultado["sala_hrs_adicional"] = a_float(m.group(1))

    # ── Oxígeno QX y recuperación (con evidencias) ────────
    for linea in texto.splitlines():
        orig = compact(linea)
        n = normalizar(orig)
        m = re.search(r"oxigeno x hr\s+(\d+(?:\.\d+)?)\s*hrs?", n)
        if m:
            hrs = a_float(m.group(1))
            resultado["oxigeno_qx"] += hrs
            resultado["evidencias_oxigeno"].append(
                {"area": "quirofano", "cantidad_esperada": hrs, "linea_original": orig})
        m = re.search(r"oxigeno recuperacion\s+(\d+(?:\.\d+)?)\s*hrs?", n)
        if m:
            hrs = a_float(m.group(1))
            resultado["oxigeno_rec"] += hrs
            resultado["evidencias_oxigeno"].append(
                {"area": "recuperacion", "cantidad_esperada": hrs, "linea_original": orig})

    # ── Sevoflurano ───────────────────────────────────────
    m = re.search(r"\bx\s+sevoflorane?\s+([\d,.]+)\s*ml", t_norm)
    if m:
        resultado["sevoflurano_ml"] = a_float(m.group(1))

    # ── PUNTO 1/7: Ingreso y egreso de sala ───────────────
    # PDF extrae la tabla como: "ingreso a sala:09:55 am 12:35 pm 09:58 am ..."
    # El segundo tiempo es el egreso de sala.
    m = re.search(
        r"ingreso a sala:\s*(\d{1,2}:\d{2}\s*[ap]m)\s+(\d{1,2}:\d{2}\s*[ap]m)",
        t_norm)
    if m:
        resultado["ingreso_sala"] = m.group(1).strip()
        resultado["egreso_sala"]  = m.group(2).strip()
        hrs_calc, mins = calcular_horas_minuto21(
            resultado["ingreso_sala"], resultado["egreso_sala"])
        resultado["horas_calculadas_m21"] = hrs_calc
        resultado["minutos_totales"]      = mins

    # ── PUNTO 2: Tipo de seguro ───────────────────────────
    m = re.search(r"seguro:\s*(.+?)(?:cirugia programada|cirugia realizada)", t_norm)
    if m:
        seg = m.group(1).strip()
        resultado["seguro"] = clasificar_pagador_nch(seg)

    # ── PUNTO 2: Máquina de anestesia marcada ─────────────
    resultado["maquina_anestesia"] = bool(
        re.search(r"\bx\s+maquina de anestesia", t_norm))

    # ── PUNTO 10: Microscopio marcado ─────────────────────
    resultado["microscopio"] = bool(
        re.search(r"\bx\s+microscopio", t_norm))

    # ── PUNTO 11: Arco en C horas ─────────────────────────
    m = re.search(r"\bx\s+arco en c\s+(\d+(?:\.\d+)?)\s*hrs?", t_norm)
    if m:
        resultado["arco_c_hrs"] = a_float(m.group(1))

    # ── Servicios binarios ────────────────────────────────
    for key, label, patron, _, _ in SERVICIOS_BINARIOS_DEF:
        resultado["servicios_marcados"][key] = bool(re.search(patron, t_norm))

    return resultado

# =========================================================
# EXTRACCIÓN DE NOTA POST-QUIRÚRGICA
# =========================================================
def _parsear_tiempo_qx(texto_norm: str):
    """
    Parsea tiempo quirúrgico en múltiples formatos:
      '2hrs' → 2.0  |  '6hrs y 26 min' → 6.43  |  '2:26' → 2.43
      '2 horeas' → 2.0  |  '30 minutos' → 0.5  |  '5 hrs' → 5.0
    Retorna horas como float o None.
    """
    bloque = ""
    m = re.search(r"tiempo quirurgico:\s*(.+?)(?:incidentes|hallazgos|$)", texto_norm)
    if m:
        bloque = m.group(1).strip()
    if not bloque:
        return None

    # Formato "H:MM" (ej: "2:26")
    m = re.match(r"(\d+):(\d{2})\b", bloque)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        return round(h + mn / 60, 2)

    # Formato "Xhrs y YY min" / "X hrs y YY minutos"
    m = re.search(r"(\d+)\s*(?:hrs?|horas?|horeas?)\s*(?:y|con)?\s*(\d+)\s*min", bloque)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        return round(h + mn / 60, 2)

    # Formato solo horas "Xhrs" / "X hrs" / "X horeas"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:hrs?|horas?|horeas?)", bloque)
    if m:
        return a_float(m.group(1))

    # Formato solo minutos "30 minutos" / "XX min"
    m = re.search(r"(\d+)\s*min", bloque)
    if m:
        return round(int(m.group(1)) / 60, 2)

    # Último intento: primer número que aparezca
    m = re.search(r"(\d+(?:\.\d+)?)", bloque)
    if m:
        return a_float(m.group(1))

    return None

def extraer_nota_postqx(texto: str) -> dict:
    t = normalizar(compact(texto))
    resultado = {
        "tiempo_quirurgico": None,
        "hemotransfusion":   None,
        "histopatologico":   None,
    }
    resultado["tiempo_quirurgico"] = _parsear_tiempo_qx(t)

    m = re.search(r"hemotransfusion:\s*(no|si|sí)", t)
    if m:
        resultado["hemotransfusion"] = m.group(1) not in ("no",)

    m = re.search(r"solicitud histopatologico:\s*(no|si|sí)", t)
    if m:
        resultado["histopatologico"] = m.group(1) not in ("no",)

    return resultado

# =========================================================
# PLANTILLA DE CUENTA
# =========================================================
def plantilla_cuenta():
    return {
        "paciente":       None,
        "archivos":       [],
        "fecha_ingreso":  None,
        "fecha_egreso":   None,
        "dias_estancia":  None,
        "seguro":         None,           # Punto 2
        "todos_los_items":    [],
        "servicios_cirugia":  None,
        "nota_postqx":        None,
        "num_cirugias":       0,          # Fix 7: contador de cirugías
        "cirugias_detalle":   [],         # Fix 7: lista de {archivo, hora_total, ingreso, egreso}
    }

# =========================================================
# CONSOLIDACIÓN
# =========================================================
@st.cache_data(show_spinner=False)
def consolidar_por_cuenta(archivos_bytes: list) -> dict:
    import io
    cuentas = {}

    for nombre, contenido in archivos_bytes:
        af = io.BytesIO(contenido)
        af.name = nombre
        texto = extraer_texto_pdf(af)
        if not texto:
            st.warning(f"⚠️ '{nombre}' sin texto; se omite.")
            continue

        cuenta  = extraer_cuenta(texto)
        paciente = extraer_paciente(texto)
        tipo    = detectar_tipo_documento(texto)

        if cuenta == "SIN_CUENTA":
            st.warning(f"⚠️ Sin NCxxxxx en '{nombre}'.")
        if tipo == "otro":
            st.info(f"ℹ️ '{nombre}' tipo no reconocido.")

        if cuenta not in cuentas:
            cuentas[cuenta] = plantilla_cuenta()

        if cuentas[cuenta]["paciente"] in (None, "No identificado") and paciente != "No identificado":
            cuentas[cuenta]["paciente"] = paciente

        cuentas[cuenta]["archivos"].append({"archivo": nombre, "tipo_documento": tipo})

        if tipo.startswith("estado_cuenta"):
            items = extraer_todos_items(texto, nombre, tipo, cuenta)
            # ── Deduplicar ítems entre cortes (EXTRAS vs PACIENTE) ──
            # La llave anterior (código, cantidad, fecha, folio) podía eliminar
            # cargos legítimos repetidos. Se usa una llave más específica.
            def _item_key(i):
                return (
                    i.get("area", ""),
                    i.get("codigo", ""),
                    normalizar(i.get("descripcion", "")),
                    round(i.get("cantidad", 0), 3),
                    round(i.get("precio_unitario", 0), 2),
                    round(i.get("subtotal", 0), 2),
                    i.get("fecha", ""),
                    i.get("folio", ""),
                )

            existentes = {_item_key(i) for i in cuentas[cuenta]["todos_los_items"]}
            items_nuevos = [i for i in items if _item_key(i) not in existentes]
            cuentas[cuenta]["todos_los_items"].extend(items_nuevos)
            if cuentas[cuenta]["fecha_ingreso"] is None:
                fi, fe, ds = extraer_fechas_estancia(texto)
                if fi:
                    cuentas[cuenta]["fecha_ingreso"] = fi
                    cuentas[cuenta]["fecha_egreso"]  = fe
                    cuentas[cuenta]["dias_estancia"] = ds
            # Extraer seguro del estado de cuenta
            if cuentas[cuenta]["seguro"] is None:
                seg = extraer_tipo_seguro(texto)
                if seg != "desconocido":
                    cuentas[cuenta]["seguro"] = seg

        elif tipo == "servicios_cirugia":
            # Fix 7: Registrar cada cirugía individual
            sc_nuevo = extraer_servicios_cirugia(texto)
            cuentas[cuenta]["num_cirugias"] += 1
            cuentas[cuenta]["cirugias_detalle"].append({
                "archivo":    nombre,
                "hora_total": sc_nuevo.get("hora_total_qx"),
                "ingreso":    sc_nuevo.get("ingreso_sala"),
                "egreso":     sc_nuevo.get("egreso_sala"),
                "cirugia_num": cuentas[cuenta]["num_cirugias"],
            })

            if cuentas[cuenta]["servicios_cirugia"] is None:
                cuentas[cuenta]["servicios_cirugia"] = sc_nuevo
            else:
                sc = cuentas[cuenta]["servicios_cirugia"]
                for k in ("oxigeno_qx", "oxigeno_rec", "sala_hrs_normal", "sala_hrs_adicional"):
                    sc[k] += sc_nuevo[k]
                sc["evidencias_oxigeno"].extend(sc_nuevo["evidencias_oxigeno"])
                if sc["hora_total_qx"] is None:
                    sc["hora_total_qx"] = sc_nuevo["hora_total_qx"]
                if sc["sevoflurano_ml"] is None:
                    sc["sevoflurano_ml"] = sc_nuevo["sevoflurano_ml"]
                # Conservar nuevos campos si no los teníamos
                if sc["ingreso_sala"] is None:
                    sc["ingreso_sala"] = sc_nuevo["ingreso_sala"]
                    sc["egreso_sala"]  = sc_nuevo["egreso_sala"]
                    sc["horas_calculadas_m21"] = sc_nuevo["horas_calculadas_m21"]
                    sc["minutos_totales"]      = sc_nuevo["minutos_totales"]
                if sc["seguro"] is None:
                    sc["seguro"] = sc_nuevo["seguro"]
                if not sc["maquina_anestesia"]:
                    sc["maquina_anestesia"] = sc_nuevo["maquina_anestesia"]
                if sc["arco_c_hrs"] is None:
                    sc["arco_c_hrs"] = sc_nuevo["arco_c_hrs"]
                if not sc["microscopio"]:
                    sc["microscopio"] = sc_nuevo["microscopio"]
                # ── Acumular servicios binarios marcados (OR lógico) ──
                if "servicios_marcados" in sc and "servicios_marcados" in sc_nuevo:
                    for k_bin in sc_nuevo["servicios_marcados"]:
                        if sc_nuevo["servicios_marcados"][k_bin]:
                            sc["servicios_marcados"][k_bin] = True

            # Actualizar seguro desde servicios (tiene prioridad sobre estado de cuenta)
            sc_actual = cuentas[cuenta]["servicios_cirugia"]
            if sc_actual.get("seguro"):
                cuentas[cuenta]["seguro"] = sc_actual["seguro"]

        elif tipo == "nota_postquirurgica":
            if cuentas[cuenta]["nota_postqx"] is None:
                cuentas[cuenta]["nota_postqx"] = extraer_nota_postqx(texto)

    return cuentas

# =========================================================
# CONSTRUCCIÓN DE AUDITORÍAS
# =========================================================
def evaluar(cobrado, esperado, tolerancia: float = 0.01):
    if esperado is None:
        return "sin regla", None, "gray"
    diff = round(cobrado - esperado, 3)
    if abs(diff) <= tolerancia:
        return "ok", diff, "ok"
    if diff < 0:
        return f"faltan {abs(diff):.2f}", diff, "err"
    return f"sobran {abs(diff):.2f}", diff, "warn"

def _precio_neto_promedio(items: list):
    """Precio neto promedio (post-descuento) por unidad. None si no calculable."""
    if not items:
        return None
    total_cant = sum(i.get("cantidad", 0) for i in items)
    total_sub  = sum(i.get("subtotal", 0) for i in items)
    if total_cant <= 0:
        return None
    return total_sub / total_cant

def _calcular_monto_diff(diff, items_cobrados):
    """
    Estima el monto en pesos de una diferencia numérica.
    - Si diff > 0 (sobran): monto exacto de lo cobrado de más.
    - Si diff < 0 (faltan): monto estimado a partir del precio de los items cobrados.
    - Si no hay items cobrados: None (sin precio de referencia).
    """
    if diff is None or abs(diff) < 0.001:
        return None
    precio = _precio_neto_promedio(items_cobrados)
    if precio is None:
        return None
    return abs(diff) * precio


def _detectar_alertas_catalogo(items: list) -> list:
    """
    Detecta posibles códigos nuevos por descripción, sin usarlos como cargo válido.

    Importante:
    - Esta función NO corrige diferencias financieras.
    - Esta función NO agrega cargos esperados/cobrados.
    - Solo avisa cuando una descripción parece pertenecer a un concepto auditado,
      pero el código no está en el catálogo configurado.
    """
    alertas = []
    vistos = set()

    for regla in CATALOGO_ALERTAS_DEF:
        codigos_validos = {str(c).upper().strip() for c in regla.get("codigos", set())}
        codigos_excluir = {str(c).upper().strip() for c in regla.get("excluir_codigos", set())}
        area_esperada = regla.get("area")
        patrones = regla.get("patrones_desc", [])
        label = regla.get("label", regla.get("key", "concepto"))
        key = regla.get("key", label)

        coincidencias = defaultdict(list)

        for item in items:
            area_item = item.get("area", "")
            if area_esperada and area_item != area_esperada:
                continue

            codigo = str(item.get("codigo", "")).upper().strip()
            # No alertar códigos que ya son válidos para este concepto, ni códigos
            # que pertenecen a accesorios/complementos conocidos del mismo concepto.
            # Ejemplo: ALM-0000877 es la funda de Arco en C; no debe detonar
            # alerta como si fuera un nuevo código del equipo Arco en C.
            if not codigo or codigo in codigos_validos or codigo in codigos_excluir:
                continue

            descripcion_norm = normalizar(item.get("descripcion", ""))
            if any(re.search(patron, descripcion_norm) for patron in patrones):
                coincidencias[codigo].append(item)

        for codigo, items_codigo in coincidencias.items():
            firma = (key, codigo)
            if firma in vistos:
                continue
            vistos.add(firma)

            descripcion_ejemplo = items_codigo[0].get("descripcion", "") if items_codigo else ""
            status = (
                f"AVISAR A JORDAN. Posible nuevo código de {label} detectado por descripción. "
                f"No se tomó como cargo válido hasta actualizar catálogo."
            )

            alertas.append({
                "categoria": "Alertas de catálogo",
                "key":       f"catalogo_{key}_{codigo}",
                "label":     f"Código no catalogado — {label}",
                "tipo":      "informativo",
                "unidad":    "",
                "cobrado":   0,
                "esperado":  None,
                "status":    status,
                "diff":      None,
                "clase":     "warn",
                "items_cobrados":  items_codigo,
                "items_esperados": [],
                "nota_auditoria": (
                    f"Código detectado: {codigo}. Descripción ejemplo: {descripcion_ejemplo}. "
                    f"Este cargo no fue usado para cerrar la validación de {label}; "
                    f"si el código es correcto, agréguelo al catálogo correspondiente."
                ),
            })

    return alertas

def construir_auditorias(data: dict, tolerancia: float) -> list:
    items     = data["todos_los_items"]
    sc        = data["servicios_cirugia"] or {}
    nota      = data["nota_postqx"] or {}
    dias      = data["dias_estancia"]
    seguro    = data.get("seguro", "desconocido")

    def por_codigo(codigos: set, area: str = None):
        r = [i for i in items if i["codigo"] in codigos]
        if area:
            r = [i for i in r if i["area"] == area]
        return r

    def contiene_palabra(desc: str, palabras: set) -> bool:
        d = normalizar(desc)
        return any(p in d for p in palabras)

    auditorias = []

    # ══════════════════════════════════════════════════════
    # Alertas de catálogo: posibles códigos nuevos detectados por descripción.
    # Estas alertas NO validan cargos. Solo avisan para actualizar catálogo.
    # ══════════════════════════════════════════════════════
    auditorias.extend(_detectar_alertas_catalogo(items))

    # ══════════════════════════════════════════════════════
    # Fix 7: Alerta de múltiples cirugías
    # ══════════════════════════════════════════════════════
    num_cx = data.get("num_cirugias", 0)
    if num_cx > 1:
        detalles = data.get("cirugias_detalle", [])
        detalle_txt = "; ".join(
            f"Cx{d['cirugia_num']}: {d.get('ingreso','?')}→{d.get('egreso','?')} "
            f"({d.get('hora_total','?')} hrs)"
            for d in detalles
        )
        auditorias.append({
            "categoria": "Validación de tiempos",
            "key":       "multi_cirugia",
            "label":     f"Múltiples cirugías detectadas ({num_cx})",
            "tipo":      "informativo",
            "unidad":    "",
            "cobrado":   0,
            "esperado":  None,
            "status":    f"{num_cx} eventos quirúrgicos — los totales son acumulados, revisar individualmente",
            "diff":      None,
            "clase":     "warn",
            "items_cobrados":  [],
            "items_esperados": [],
            "nota_auditoria": (
                f"Se encontraron {num_cx} hojas de servicios de cirugía. "
                f"Los datos de oxígeno, sala y equipos se acumularon. "
                f"Detalle: {detalle_txt}"
            ),
        })

    # ══════════════════════════════════════════════════════
    # PUNTO 1 y 7: Validación de hora total vs tiempos reales
    # ══════════════════════════════════════════════════════
    if sc:
        ingreso   = sc.get("ingreso_sala")
        egreso    = sc.get("egreso_sala")
        hora_tot  = sc.get("hora_total_qx")
        hrs_m21   = sc.get("horas_calculadas_m21")
        mins_tot  = sc.get("minutos_totales")

        if ingreso and egreso and hora_tot is not None and hrs_m21 is not None:
            if abs(hora_tot - hrs_m21) < 0.01:
                status = f"ok — {ingreso}→{egreso} = {mins_tot:.0f} min → {hrs_m21:.0f} hrs (regla min 21)"
                clase  = "ok"
            else:
                status = (f"HORA TOTAL ({hora_tot:.0f}) ≠ calculado ({hrs_m21:.0f}) "
                          f"desde {ingreso}→{egreso} ({mins_tot:.0f} min)")
                clase  = "warn"
            auditorias.append({
                "categoria": "Validación de tiempos",
                "key":       "hora_total_vs_tiempos",
                "label":     "Hora total QX vs ingreso/egreso de sala (regla minuto 21)",
                "tipo":      "informativo",
                "unidad":    "hrs",
                "cobrado":   hora_tot,
                "esperado":  hrs_m21,
                "status":    status,
                "diff":      round(hora_tot - hrs_m21, 1),
                "clase":     clase,
                "items_cobrados":  [],
                "items_esperados": [],
                "nota_auditoria": (
                    f"Ingreso a sala: {ingreso} · Egreso de sala: {egreso} · "
                    f"Tiempo real: {mins_tot:.0f} min · "
                    f"Regla minuto 21: ≥21 min se cobra hora completa."
                ),
            })
        elif ingreso is None and hora_tot is not None:
            auditorias.append({
                "categoria": "Validación de tiempos",
                "key":       "hora_total_vs_tiempos",
                "label":     "Hora total QX vs ingreso/egreso de sala",
                "tipo":      "informativo",
                "unidad":    "",
                "cobrado":   hora_tot,
                "esperado":  None,
                "status":    "sin datos de ingreso/egreso de sala",
                "diff":      None,
                "clase":     "gray",
                "items_cobrados":  [],
                "items_esperados": [],
                "nota_auditoria": "No se encontraron tiempos de ingreso/egreso en la hoja de servicios.",
            })

    # ══════════════════════════════════════════════════════
    # PUNTO 2: Máquina de anestesia
    # Regla actualizada:
    # - Solo aplica validación como seguro si el pagador coincide con
    #   el catálogo NCH de aseguradoras.
    # - Si es particular o texto no reconocido, NO se exige el cargo.
    # ══════════════════════════════════════════════════════
    if sc:
        maq_marcada = sc.get("maquina_anestesia", False)
        es_seguro = es_seguro_nch(seguro)
        es_particular = not es_seguro

        # Fix 6: Buscar cargo de máquina de anestesia en el estado de cuenta
        PALABRAS_MAQUINA = {"maquina de anestesia", "maquina anestesia", "anesthesia machine"}
        maq_items = [i for i in items
                     if any(p in normalizar(i["descripcion"]) for p in PALABRAS_MAQUINA)]
        maq_cobrada = len(maq_items) > 0

        if maq_marcada or maq_cobrada:
            if es_particular and maq_cobrada:
                status = "ERROR — máquina de anestesia cobrada en cuenta particular/no aseguradora NCH"
                clase  = "err"

            elif es_particular and not maq_cobrada:
                status = "no aplica — cuenta particular/no aseguradora NCH; no se requiere cargo"
                clase  = "gray"

            elif es_seguro and maq_cobrada:
                status = f"ok — paciente con seguro NCH ({seguro}), máquina cobrada"
                clase  = "ok"

            elif es_seguro and maq_marcada and not maq_cobrada:
                status = f"documentada pero no cobrada — paciente con seguro NCH ({seguro}), verificar"
                clase  = "warn"

            else:
                status = f"documentada: {'sí' if maq_marcada else 'no'}, cobrada: {'sí' if maq_cobrada else 'no'}"
                clase  = "gray"

            auditorias.append({
                "categoria": "Validación de tiempos",
                "key":       "maquina_anestesia",
                "label":     "Máquina de anestesia",
                "tipo":      "informativo",
                "unidad":    "",
                "cobrado":   float(maq_cobrada),
                "esperado":  None,
                "status":    status,
                "diff":      None,
                "clase":     clase,
                "items_cobrados":  maq_items,
                "items_esperados": [],
                "nota_auditoria": (
                    f"Pagador clasificado: {seguro or 'no identificado'}. "
                    f"Regla: la validación de cargo de máquina de anestesia solo aplica "
                    f"para aseguradoras del catálogo NCH. En particulares/no aseguradora NCH, "
                    f"no se requiere cargo."
                ),
            })

    # ══════════════════════════════════════════════════════
    # CAMBIO 1 — OXÍGENO QX: el esperado se calcula desde las horas de sala
    # (HORA TOTAL DE QUIRÓFANO = sala normal + sala adicional), NO del campo
    # "Oxígeno x hr" de la hoja de servicios. Indicación del auditor:
    # "No tomar dato de casilla azul" — suelen equivocarse al marcarla.
    # ══════════════════════════════════════════════════════
    ox_qx_items = por_codigo(CODIGOS_OXIGENO, "quirofano")
    cobrado_qx  = round(sum(i["cantidad"] for i in ox_qx_items), 3)

    # Fuente principal del esperado: cargos reales de sala en estado de cuenta.
    # Criterio del auditor: Oxígeno QX se relaciona contra QRF-0000002
    # (primera hora) + QRF-0000001 (horas adicionales), NO contra la
    # casilla azul "Oxígeno x hr" ni contra oxígeno de recuperación.
    sala_items_qx = por_codigo({CODIGO_SALA_NORMAL, CODIGO_SALA_ADICIONAL}, "quirofano")
    sala_total_cobrada = round(sum(i["cantidad"] for i in sala_items_qx), 3)

    if sala_total_cobrada > 0:
        esperado_qx = sala_total_cobrada
    elif sc:
        # Respaldo si el estado de cuenta no trae cargos QRF parseables.
        sala_total_doc = sc.get("sala_hrs_normal", 0.0) + sc.get("sala_hrs_adicional", 0.0)
        if sala_total_doc == 0 and sc.get("hora_total_qx"):
            sala_total_doc = sc["hora_total_qx"]
        esperado_qx = sala_total_doc if sala_total_doc > 0 else None
    else:
        esperado_qx = None

    # Solo agregar la auditoría si hay algo que validar
    if ox_qx_items or (esperado_qx is not None and esperado_qx > 0):
        status, diff, clase = evaluar(cobrado_qx, esperado_qx, tolerancia)

        # Nota explicativa con desglose y referencia al campo "casilla azul"
        nota_partes = []
        if sala_total_cobrada > 0:
            normal_cob = sum(i["cantidad"] for i in sala_items_qx if i["codigo"] == CODIGO_SALA_NORMAL)
            adicional_cob = sum(i["cantidad"] for i in sala_items_qx if i["codigo"] == CODIGO_SALA_ADICIONAL)
            nota_partes.append(
                f"Esperado calculado desde cargos QRF en estado de cuenta: "
                f"{normal_cob:.0f} hr normal + {adicional_cob:.0f} hr adicional = "
                f"{sala_total_cobrada:.0f} hrs."
            )
        elif sc:
            nota_partes.append(
                f"Sin cargos QRF parseables; esperado calculado como respaldo desde hoja de servicios: "
                f"{sc.get('sala_hrs_normal',0):.0f} hr normal + "
                f"{sc.get('sala_hrs_adicional',0):.0f} hr adicional."
            )

        if sc:
            ox_doc = sc.get("oxigeno_qx", 0)
            if ox_doc and abs(ox_doc - (esperado_qx or 0)) > 0.01:
                nota_partes.append(
                    f"Hoja de servicios marca {ox_doc:.0f} hrs en el campo 'Oxígeno x hr' "
                    f"(dato informativo; no define el cobro de oxígeno QX)."
                )

        auditorias.append({
            "categoria": "Oxígeno",
            "key":       "oxigeno_quirofano",
            "label":     "Oxígeno — Quirófano",
            "tipo":      "numerico",
            "unidad":    "hrs",
            "cobrado":   cobrado_qx,
            "esperado":  esperado_qx,
            "status":    status,
            "diff":      diff,
            "clase":     clase,
            "items_cobrados":  ox_qx_items,
            "items_esperados": [e for e in sc.get("evidencias_oxigeno", [])
                                if e["area"] == "quirofano"],
            "nota_auditoria": " ".join(nota_partes) if nota_partes else None,
        })

        # ── Aviso a enfermería: casilla azul de oxígeno mal llenada ──
        # No afecta el cobro (el cobro se valida arriba contra sala). Solo
        # documenta cuando enfermería llenó mal la casilla "Oxígeno x hr"
        # de la hoja, para que el auditor tenga evidencia al hablar con
        # el área. Aparece junto a la auditoría real de oxígeno quirófano.
        sala_total_doc = sc.get("sala_hrs_normal", 0) + sc.get("sala_hrs_adicional", 0)
        ox_qx_doc      = sc.get("oxigeno_qx", 0)
        if sala_total_doc > 0 or ox_qx_doc > 0:
            casilla_ok = abs(sala_total_doc - ox_qx_doc) < 0.01
            if casilla_ok:
                status_av = (f"ok — casilla azul correctamente llenada "
                             f"({ox_qx_doc:.0f} hrs = sala {sala_total_doc:.0f} hrs)")
                clase_av  = "ok"
            else:
                status_av = (f"casilla azul marca {ox_qx_doc:.0f} hrs cuando "
                             f"la sala fue de {sala_total_doc:.0f} hrs — "
                             f"verificar con enfermería")
                # Aviso documental: no debe convertir la cuenta en “Con diferencias”.
                clase_av  = "gray"
            auditorias.append({
                "categoria": "Avisos de documentación",
                "key":       "aviso_casilla_azul",
                "label":     "Aviso a enfermería: casilla azul de oxígeno",
                "tipo":      "informativo",
                "unidad":    "hrs",
                "cobrado":   ox_qx_doc,
                "esperado":  sala_total_doc,
                "status":    status_av,
                "diff":      round(ox_qx_doc - sala_total_doc, 1),
                "clase":     clase_av,
                "items_cobrados":  [],
                "items_esperados": [],
                "nota_auditoria": (
                    "Este dato NO se usa para validar el cobro. Es un aviso de "
                    "proceso: la casilla azul 'Oxígeno x hr' de la hoja de "
                    "servicios debe coincidir con las horas de sala. Si no "
                    "coincide, enfermería llenó mal la hoja."
                ),
            })

    # ── Oxígeno recuperación: se conserva la lógica original ──
    # (compara contra el campo "Oxígeno recuperación" de la hoja de servicios)
    ox_rec_items = por_codigo(CODIGOS_OXIGENO, "recuperacion")
    cobrado_rec  = round(sum(i["cantidad"] for i in ox_rec_items), 3)
    esperado_rec = sc.get("oxigeno_rec", 0.0) if sc else None
    if not sc:
        esperado_rec = None
    elif sc.get("oxigeno_rec", 0.0) == 0 and cobrado_rec == 0:
        esperado_rec = None  # nada que validar, omitimos

    if esperado_rec is not None or ox_rec_items:
        status, diff, clase = evaluar(cobrado_rec, esperado_rec, tolerancia)
        auditorias.append({
            "categoria": "Oxígeno",
            "key":       "oxigeno_recuperacion",
            "label":     "Oxígeno — Recuperación",
            "tipo":      "numerico",
            "unidad":    "hrs",
            "cobrado":   cobrado_rec,
            "esperado":  esperado_rec,
            "status":    status,
            "diff":      diff,
            "clase":     clase,
            "items_cobrados":  ox_rec_items,
            "items_esperados": [e for e in sc.get("evidencias_oxigeno", [])
                                if e["area"] == "recuperacion"],
            "nota_auditoria": None,
        })

    # ── Oxígeno hospitalización: solo informativo ──
    ox_hosp = por_codigo(CODIGOS_OXIGENO, "hospitalizacion")
    if ox_hosp:
        cobrado_h = round(sum(i["cantidad"] for i in ox_hosp), 3)
        detalle = "; ".join(
            f"{i['cantidad']:.2f} hr {i['fecha']} folio {i['folio']}"
            for i in ox_hosp
        )
        auditorias.append({
            "categoria": "Oxígeno",
            "key":       "oxigeno_hosp",
            "label":     "Oxígeno — Hospitalización",
            "tipo":      "numerico",
            "unidad":    "hrs",
            "cobrado":   cobrado_h,
            "esperado":  None,
            "status":    "sin regla",
            "diff":      None,
            "clase":     "gray",
            "items_cobrados":  ox_hosp,
            "items_esperados": [],
            "nota_auditoria": (
                f"Sin documento clínico de referencia ({detalle}). "
                "Verificar con nota de enfermería u orden médica."
            ),
        })

    # ══════════════════════════════════════════════════════
    # 2. SALA QUIRÚRGICA
    # ══════════════════════════════════════════════════════
    sala_items = por_codigo({CODIGO_SALA_NORMAL, CODIGO_SALA_ADICIONAL}, "quirofano")
    sala_cobrado = round(sum(i["cantidad"] for i in sala_items), 3)
    sala_esp = sc.get("hora_total_qx") if sc else None

    if sala_items or sala_esp:
        status, diff, clase = evaluar(sala_cobrado, sala_esp, tolerancia)
        auditorias.append({
            "categoria": "Sala quirúrgica",
            "key":       "sala_hrs",
            "label":     "Horas de sala quirúrgica",
            "tipo":      "numerico",
            "unidad":    "hrs",
            "cobrado":   sala_cobrado,
            "esperado":  sala_esp,
            "status":    status,
            "diff":      diff,
            "clase":     clase,
            "items_cobrados":  sala_items,
            "items_esperados": [],
            "nota_auditoria": (
                f"Servicios documenta: {sc.get('sala_hrs_normal',0):.0f} hr normal + "
                f"{sc.get('sala_hrs_adicional',0):.0f} hr(s) adicional = "
                f"{sala_esp:.0f} hrs total."
            ) if sala_esp else None,
        })

    # ── Fix 5: Validar desglose normal vs adicional ───────
    if sala_items and sala_esp and sala_esp >= 1:
        items_normal   = [i for i in sala_items if i["codigo"] == CODIGO_SALA_NORMAL]
        items_adicional = [i for i in sala_items if i["codigo"] == CODIGO_SALA_ADICIONAL]
        cant_normal    = round(sum(i["cantidad"] for i in items_normal), 3)
        cant_adicional = round(sum(i["cantidad"] for i in items_adicional), 3)
        esp_normal     = 1.0
        esp_adicional  = max(sala_esp - 1, 0)

        problemas = []
        if abs(cant_normal - esp_normal) > tolerancia:
            problemas.append(f"primera hora: cobrado {cant_normal:.0f}, esperado {esp_normal:.0f}")
        if abs(cant_adicional - esp_adicional) > tolerancia:
            problemas.append(f"adicionales: cobrado {cant_adicional:.0f}, esperado {esp_adicional:.0f}")

        if problemas:
            status_d = "desglose incorrecto — " + "; ".join(problemas)
            clase_d  = "err"
        else:
            status_d = f"ok — 1 hr normal + {esp_adicional:.0f} hr(s) adicional"
            clase_d  = "ok"

        auditorias.append({
            "categoria": "Sala quirúrgica",
            "key":       "sala_desglose",
            "label":     "Desglose sala (normal vs adicional)",
            "tipo":      "informativo",
            "unidad":    "",
            "cobrado":   0,
            "esperado":  None,
            "status":    status_d,
            "diff":      None,
            "clase":     clase_d,
            "items_cobrados":  sala_items,
            "items_esperados": [],
            "nota_auditoria": (
                f"Debe haber exactamente 1 cargo de primera hora (QRF-0000002) y "
                f"{esp_adicional:.0f} cargo(s) de hora adicional (QRF-0000001)."
            ),
        })

    # ── Sevoflurano ───────────────────────────────────────
    sevo_items = [i for i in items if i["codigo"] == CODIGO_SEVOFLURANO]
    sevo_cobrado = round(sum(i["cantidad"] for i in sevo_items), 2)
    sevo_esp = sc.get("sevoflurano_ml") if sc else None

    if sevo_items or sevo_esp:
        status, diff, clase = evaluar(sevo_cobrado, sevo_esp, tolerancia=1.0)
        # Criterio del auditor: sevoflurano es una verificación clínica/anestesia,
        # no una diferencia financiera automática. Si no coincide, se muestra como
        # informativo para revisión médica.
        if clase in ("err", "warn"):
            status = (
                f"verificar con anestesia — documentado {sevo_esp or 0:.2f} ml; "
                f"cobrado {sevo_cobrado:.2f} ml"
            )
            clase = "gray"
        # Fix 4: Desglose por folio
        desglose = " + ".join(
            f"{i['cantidad']:.0f} ml ({i['folio']})" for i in sevo_items
        ) if len(sevo_items) > 1 else ""
        nota_sevo = "Tolerancia de ±1.0 ml por redondeo."
        if desglose:
            nota_sevo += f" Desglose: {desglose} = {sevo_cobrado:.0f} ml total."
        auditorias.append({
            "categoria": "Sala quirúrgica",
            "key":       "sevoflurano",
            "label":     "Sevoflurano",
            "tipo":      "numerico",
            "unidad":    "ml",
            "cobrado":   sevo_cobrado,
            "esperado":  sevo_esp,
            "status":    status,
            "diff":      diff,
            "clase":     clase,
            "items_cobrados":  sevo_items,
            "items_esperados": [],
            "nota_auditoria": nota_sevo,
        })

    # ══════════════════════════════════════════════════════
    # 3. SERVICIOS BINARIOS (incluye microscopio y arco en C)
    # ══════════════════════════════════════════════════════
    for key, label, _, codigos_cuenta, area_cuenta in SERVICIOS_BINARIOS_DEF:
        marcado       = sc.get("servicios_marcados", {}).get(key, False) if sc else False
        cobrado_items = por_codigo(codigos_cuenta, area_cuenta)
        cobrado_bool  = len(cobrado_items) > 0

        if not marcado and not cobrado_bool:
            continue

        if marcado and cobrado_bool:
            status, clase = "ok — documentado y cobrado", "ok"
        elif marcado and not cobrado_bool:
            status, clase = "documentado, no cobrado", "gray"
        else:
            status, clase = "cobrado sin documentar uso", "err"

        auditorias.append({
            "categoria": "Equipos y servicios",
            "key":       f"bin_{key}",
            "label":     label,
            "tipo":      "binario",
            "unidad":    "",
            "cobrado":   float(cobrado_bool),
            "esperado":  float(marcado),
            "marcado":   marcado,
            "cobrado_bool": cobrado_bool,
            "status":    status,
            "diff":      None,
            "clase":     clase,
            "items_cobrados":  cobrado_items,
            "items_esperados": [],
            "nota_auditoria": None,
        })

    # ══════════════════════════════════════════════════════
    # PUNTO 8: Electrocauterio + lápiz + placa
    # ══════════════════════════════════════════════════════
    electro_items = por_codigo({CODIGO_ELECTROCAUTERIO}, "quirofano")
    if electro_items:
        lapiz_items = por_codigo({CODIGO_LAPIZ_ELECTRO}, "quirofano")
        placa_items = por_codigo({CODIGO_PLACA_ELECTRO}, "quirofano")
        falta_lapiz = len(lapiz_items) == 0
        falta_placa = len(placa_items) == 0
        faltantes = []
        if falta_lapiz: faltantes.append("lápiz (ALM-0001320)")
        if falta_placa: faltantes.append("placa (ALM-0000753)")

        if faltantes:
            status = f"falta(n): {', '.join(faltantes)}"
            clase  = "err"
        else:
            status = "ok — electrocauterio, lápiz y placa presentes"
            clase  = "ok"

        auditorias.append({
            "categoria": "Accesorios complementarios",
            "key":       "electro_accesorios",
            "label":     "Electrocauterio → lápiz + placa",
            "tipo":      "informativo",
            "unidad":    "",
            "cobrado":   0,
            "esperado":  None,
            "status":    status,
            "diff":      None,
            "clase":     clase,
            "items_cobrados":  electro_items + lapiz_items + placa_items,
            "items_esperados": [],
            "nota_auditoria": "Cuando se cobra electrocauterio, deben existir lápiz y placa.",
        })

    # ══════════════════════════════════════════════════════
    # PUNTO 9: Bomba de infusión + equipo infusomat
    # Validación por cantidad: no basta con que exista un equipo; debe
    # haber al menos la misma cantidad de equipos infusomat que usos de bomba.
    # ══════════════════════════════════════════════════════
    bomba_items_qx = por_codigo({CODIGO_BOMBA})
    equipo_inf = por_codigo({CODIGO_EQUIPO_INFUSOMAT})
    cant_bombas = round(sum(i.get("cantidad", 0) for i in bomba_items_qx), 3)
    cant_infusomat = round(sum(i.get("cantidad", 0) for i in equipo_inf), 3)

    if bomba_items_qx:
        if cant_infusomat == 0:
            status_bomba = "bomba cobrada sin equipo infusomat (ALM-0000869)"
            clase_bomba = "err"
            nota_bomba = "Cada uso de bomba de infusión debe ir con equipo infusomat."
        elif cant_infusomat < cant_bombas:
            status_bomba = (
                f"verificar — {cant_bombas:.0f} bomba(s) y "
                f"{cant_infusomat:.0f} equipo(s) infusomat"
            )
            clase_bomba = "warn"
            nota_bomba = (
                "La validación se realiza por cantidad. Si un solo equipo infusomat "
                "cubre varios días por continuidad clínica, confirmar con enfermería/almacén."
            )
        else:
            status_bomba = f"ok — {cant_bombas:.0f} bomba(s), {cant_infusomat:.0f} equipo(s)"
            clase_bomba = "ok"
            nota_bomba = None

        auditorias.append({
            "categoria": "Accesorios complementarios",
            "key":       "bomba_infusomat",
            "label":     "Bomba de infusión → equipo infusomat",
            "tipo":      "informativo",
            "unidad":    "",
            "cobrado":   cant_bombas,
            "esperado":  cant_infusomat,
            "status":    status_bomba,
            "diff":      None,
            "clase":     clase_bomba,
            "items_cobrados":  bomba_items_qx + equipo_inf,
            "items_esperados": [],
            "nota_auditoria": nota_bomba,
        })

    # ══════════════════════════════════════════════════════
    # CAMBIO 4 — MICROSCOPIO + FUNDA (validación bidireccional)
    # Antes: solo si está el microscopio se buscaba la funda.
    # Ahora: si la funda aparece sin microscopio documentado ni cobrado,
    # también se genera un aviso para que el revisor lo confirme con el área.
    # ══════════════════════════════════════════════════════
    micro_items = por_codigo({CODIGO_MICROSCOPIO}, "quirofano")
    funda_micro = por_codigo({CODIGO_FUNDA_MICROSCOPIO}, "quirofano")
    micro_marcado = sc.get("servicios_marcados", {}).get("microscopio", False) if sc else False

    if micro_items or funda_micro or micro_marcado:
        if micro_items:
            # Caso original: microscopio presente, validar que tenga funda
            if funda_micro:
                status = "ok — microscopio y funda presentes"
                clase  = "ok"
            else:
                status = "microscopio cobrado sin funda (ALM-0000878)"
                clase  = "err"
        elif funda_micro and not micro_marcado:
            # Nuevo caso: funda sin microscopio cobrado ni marcado
            status = ("funda de microscopio cobrada sin uso documentado de microscopio — "
                      "verificar con el área")
            clase  = "warn"
        elif funda_micro and micro_marcado:
            # Marcado pero no cobrado, con funda presente
            status = ("funda presente y microscopio marcado en hoja de servicios "
                      "pero no cobrado — confirmar con el área")
            clase  = "warn"
        else:
            # Marcado pero ni microscopio ni funda cobrados
            status = ("microscopio marcado en hoja de servicios pero no cobrado — "
                      "verificar con el área")
            clase  = "warn"

        auditorias.append({
            "categoria": "Accesorios complementarios",
            "key":       "microscopio_funda",
            "label":     "Microscopio ↔ funda",
            "tipo":      "informativo",
            "unidad":    "",
            "cobrado":   0,
            "esperado":  None,
            "status":    status,
            "diff":      None,
            "clase":     clase,
            "items_cobrados":  micro_items + funda_micro,
            "items_esperados": [],
            "nota_auditoria": (
                "Validación bidireccional: el uso de microscopio debe ir con funda desechable, "
                "y la presencia de funda sin microscopio documentado se verifica con el área."
            ),
        })

    # ══════════════════════════════════════════════════════
    # CAMBIO 4 — ARCO EN C + FUNDA (validación bidireccional)
    # Antes: solo si está el arco se buscaba la funda.
    # Ahora: si la funda aparece sin arco documentado ni cobrado,
    # también se genera un aviso para que el revisor lo confirme con el área.
    # ══════════════════════════════════════════════════════
    arco_items   = por_codigo(CODIGOS_ARCO_C, "quirofano")
    funda_arco   = por_codigo({CODIGO_FUNDA_ARCO_C}, "quirofano")
    arco_marcado = sc.get("servicios_marcados", {}).get("arco_c", False) if sc else False

    if arco_items or funda_arco or arco_marcado:
        if arco_items:
            # Caso original: arco presente, validar que tenga funda
            if funda_arco:
                status = "ok — arco en C y funda presentes"
                clase  = "ok"
            else:
                status = "arco en C cobrado sin funda (ALM-0000877)"
                clase  = "err"
        elif funda_arco and not arco_marcado:
            # Nuevo caso: funda sin arco cobrado ni marcado
            status = ("funda de arco en C cobrada sin uso documentado de arco — "
                      "verificar con el área")
            clase  = "warn"
        elif funda_arco and arco_marcado:
            # Marcado pero no cobrado, con funda presente
            status = ("funda presente y arco marcado en hoja de servicios "
                      "pero no cobrado — confirmar con el área")
            clase  = "warn"
        else:
            # Marcado pero ni arco ni funda cobrados
            status = ("arco en C marcado en hoja de servicios pero no cobrado — "
                      "verificar con el área")
            clase  = "warn"

        auditorias.append({
            "categoria": "Accesorios complementarios",
            "key":       "arco_funda",
            "label":     "Arco en C ↔ funda",
            "tipo":      "informativo",
            "unidad":    "",
            "cobrado":   0,
            "esperado":  None,
            "status":    status,
            "diff":      None,
            "clase":     clase,
            "items_cobrados":  arco_items + funda_arco,
            "items_esperados": [],
            "nota_auditoria": (
                "Validación bidireccional: el uso de arco en C debe ir con funda estéril desechable, "
                "y la presencia de funda sin arco documentado se verifica con el área."
            ),
        })

    # ══════════════════════════════════════════════════════
    # CAMBIO 2 — TRÍO DE RECUPERACIÓN (sala + monitor + oxígeno)
    # Antes: warning automático si faltaba alguno.
    # Ahora: comparación bidireccional contra lo marcado en la hoja de servicios.
    # Por indicación del auditor: a veces enfermería se les pasa marcarlo
    # o cargarlo, y desde ahí entran a corroborar con el área (WhatsApp).
    # ══════════════════════════════════════════════════════
    rec_sala    = por_codigo({"REC-0000001"}, "recuperacion")
    rec_monitor = por_codigo({"IBM-0000010"}, "recuperacion")
    rec_oxigeno = por_codigo(CODIGOS_OXIGENO, "recuperacion")

    # Lo marcado en hoja de servicios
    sm = sc.get("servicios_marcados", {}) if sc else {}
    marc_sala    = sm.get("sala_rec", False)
    marc_monitor = sm.get("monitor_rec", False)
    marc_oxigeno = (sc.get("oxigeno_rec", 0) > 0) if sc else False

    cobrado_dict = {
        "Sala de recuperación":  len(rec_sala) > 0,
        "Monitor SV":            len(rec_monitor) > 0,
        "Oxígeno recuperación":  len(rec_oxigeno) > 0,
    }
    marcado_dict = {
        "Sala de recuperación":  marc_sala,
        "Monitor SV":            marc_monitor,
        "Oxígeno recuperación":  marc_oxigeno,
    }

    # Solo evaluar si hay algo marcado o cobrado
    hay_actividad = any(cobrado_dict.values()) or any(marcado_dict.values())

    if hay_actividad:
        # Buscar discrepancias en cualquier dirección
        marcados_no_cobrados = [
            k for k in cobrado_dict
            if marcado_dict[k] and not cobrado_dict[k]
        ]
        cobrados_no_marcados = [
            k for k in cobrado_dict
            if cobrado_dict[k] and not marcado_dict[k]
        ]

        if not marcados_no_cobrados and not cobrados_no_marcados:
            # Todo coincide: lo que está marcado está cobrado y viceversa
            n_presentes = sum(cobrado_dict.values())
            if n_presentes == 3:
                status = "ok — los 3 conceptos coinciden entre hoja de servicios y cuenta"
            else:
                presentes = [k for k, v in cobrado_dict.items() if v]
                status = f"ok — coinciden hoja vs cuenta ({', '.join(presentes) or 'sin cargos'})"
            clase = "ok"
            nota_trio = None
        else:
            # Hay discrepancia: dejar como informativo (no warning ni error rojo)
            partes = []
            if marcados_no_cobrados:
                partes.append(
                    f"marcado(s) en hoja pero no cobrado(s): {', '.join(marcados_no_cobrados)}"
                )
            if cobrados_no_marcados:
                partes.append(
                    f"cobrado(s) sin estar marcado(s) en hoja: {', '.join(cobrados_no_marcados)}"
                )
            status = "discrepancia — " + "; ".join(partes)
            clase  = "warn"
            nota_trio = (
                "Comparación entre hoja de servicios y estado de cuenta. "
                "Puede ser que enfermería haya omitido marcarlo o cargarlo. "
                "Confirmar con el área (grupo de WhatsApp)."
            )

        auditorias.append({
            "categoria": "Consistencia de servicios",
            "key":       "trio_recuperacion",
            "label":     "Trío de recuperación (sala + monitor + oxígeno)",
            "tipo":      "informativo",
            "unidad":    "",
            "cobrado":   0,
            "esperado":  None,
            "status":    status,
            "diff":      None,
            "clase":     clase,
            "items_cobrados":  rec_sala + rec_monitor + rec_oxigeno,
            "items_esperados": [],
            "nota_auditoria": nota_trio,
        })

    # ══════════════════════════════════════════════════════
    # 4. VERIFICACIONES NEGATIVAS (existente)
    # ══════════════════════════════════════════════════════
    hemotrans = nota.get("hemotransfusion")
    sangre_items = [i for i in items
                    if contiene_palabra(i["descripcion"], PALABRAS_SANGRE)]
    if hemotrans is not None or sangre_items:
        if hemotrans is False and not sangre_items:
            status, clase = "ok — nota dice NO y no hay cargos", "ok"
        elif hemotrans is False and sangre_items:
            status, clase = "nota dice NO pero hay cargos — verificar", "err"
        elif hemotrans is True and sangre_items:
            status, clase = "verificar con equipo médico — nota dice SÍ y hay cargos de sangre", "gray"
        elif hemotrans is True and not sangre_items:
            status, clase = "verificar con equipo médico — nota dice SÍ pero no hay cargos de sangre", "gray"
        else:
            status, clase = "sin información en nota post-qx", "gray"
        auditorias.append({
            "categoria": "Verificaciones negativas",
            "key":       "hemotransfusion",
            "label":     "Hemotransfusión",
            "tipo":      "negativo",
            "unidad":    "",
            "cobrado":   float(len(sangre_items)),
            "esperado":  None,
            "status":    status,
            "diff":      None,
            "clase":     clase,
            "items_cobrados":  sangre_items,
            "items_esperados": [],
            "nota_auditoria": (
                f"Nota post-quirúrgica: hemotransfusión = "
                f"{'SÍ' if hemotrans else 'NO' if hemotrans is False else 'no documentada'}. "
                f"Este punto se deja como verificación médica cuando la nota indica SÍ; "
                f"no se considera diferencia financiera automática."
            ),
        })

    histo = nota.get("histopatologico")
    pato_items = [i for i in items
                  if contiene_palabra(i["descripcion"], PALABRAS_PATOLOGIA)]
    if histo is not None or pato_items:
        if histo is False and not pato_items:
            status, clase = "ok — nota dice NO y no hay cargos", "ok"
        elif histo is False and pato_items:
            status, clase = "nota dice NO pero hay cargos de patología — verificar", "err"
        elif histo is True:
            status, clase = "nota dice SÍ — verificar cargos concordantes", "warn"
        else:
            status, clase = "sin información en nota post-qx", "gray"
        auditorias.append({
            "categoria": "Verificaciones negativas",
            "key":       "histopatologico",
            "label":     "Histopatológico",
            "tipo":      "negativo",
            "unidad":    "",
            "cobrado":   float(len(pato_items)),
            "esperado":  None,
            "status":    status,
            "diff":      None,
            "clase":     clase,
            "items_cobrados":  pato_items,
            "items_esperados": [],
            "nota_auditoria": (
                f"Nota post-quirúrgica: histopatológico = "
                f"{'SÍ' if histo else 'NO' if histo is False else 'no documentado'}."
            ),
        })

    # ══════════════════════════════════════════════════════
    # 5. ESTANCIA
    # ══════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════
    # RPBI: regla diferenciada por tipo de cuenta
    # - Particular/no aseguradora NCH: 1 cargo al ingreso + adicional pasando 7 días.
    # - Seguro NCH: cargo diario de ingreso a egreso.
    # ══════════════════════════════════════════════════════
    rpbi_items = por_codigo({CODIGO_RPBI})
    rpbi_count = len(rpbi_items)

    es_seguro = es_seguro_nch(seguro)

    if dias is None:
        rpbi_esperado = None

        if rpbi_count == 0:
            status = (
                f"FALTA cargo de RPBI — no hay fechas de estancia para calcular frecuencia, "
                f"pero debe existir mínimo 1 cargo al ingreso a habitación ({CODIGO_RPBI})"
            )
            clase = "err"
        else:
            status = (
                f"{rpbi_count} cargo(s) de RPBI detectado(s); sin fechas de estancia "
                f"no se puede validar frecuencia"
            )
            clase = "gray"

    elif es_seguro:
        # Seguro NCH: cargo diario de ingreso a egreso.
        # La variable dias viene de fecha_egreso - fecha_ingreso.
        # Por eso se usa dias + 1 para contar días calendario incluyendo ingreso y egreso.
        rpbi_esperado = max(dias + 1, 1)

        if rpbi_count == 0:
            status = f"FALTA cargo diario de RPBI — seguro NCH ({seguro})"
            clase = "err"
        elif rpbi_count < rpbi_esperado:
            status = (
                f"insuficiente — seguro NCH ({seguro}): {rpbi_count} cargo(s) "
                f"para {dias} noche(s) / {rpbi_esperado} día(s) calendario; "
                f"se esperan {rpbi_esperado}"
            )
            clase = "err"
        elif rpbi_count == rpbi_esperado:
            status = (
                f"ok — seguro NCH ({seguro}): {rpbi_count} cargo(s) diario(s) "
                f"de ingreso a egreso"
            )
            clase = "ok"
        else:
            status = (
                f"verificar — seguro NCH ({seguro}): {rpbi_count} cargo(s); "
                f"se esperaban {rpbi_esperado}"
            )
            clase = "warn"

    else:
        # Particular/no aseguradora NCH:
        # 1 cargo inicial; pasando 7 días, segundo cargo; y así sucesivamente.
        rpbi_esperado = 1 + (max(dias - 1, 0) // DIAS_RPBI_ADICIONAL)

        if rpbi_count == 0:
            status = "FALTA cargo inicial de RPBI — cuenta particular/no aseguradora NCH"
            clase = "err"
        elif rpbi_count < rpbi_esperado:
            status = (
                f"insuficiente — cuenta particular/no aseguradora NCH: {rpbi_count} cargo(s) "
                f"para {dias} día(s); se esperan {rpbi_esperado}"
            )
            clase = "err"
        elif rpbi_count == rpbi_esperado:
            status = (
                f"ok — cuenta particular/no aseguradora NCH: {rpbi_count} cargo(s) "
                f"para {dias} día(s)"
            )
            clase = "ok"
        else:
            status = (
                f"verificar — cuenta particular/no aseguradora NCH: {rpbi_count} cargo(s) "
                f"para {dias} día(s); se esperaban {rpbi_esperado}"
            )
            clase = "warn"

    auditorias.append({
        "categoria": "Estancia",
        "key":       "rpbi",
        "label":     "Disposición de RPBI",
        "tipo":      "numerico",
        "unidad":    "cargo(s)",
        "cobrado":   float(rpbi_count),
        "esperado":  float(rpbi_esperado) if rpbi_esperado is not None else None,
        "status":    status,
        "diff":      None,
        "clase":     clase,
        "items_cobrados":  rpbi_items,
        "items_esperados": [],
        "nota_auditoria": (
            f"Pagador clasificado: {seguro or 'no identificado'}. "
            f"Regla RPBI: particulares/no aseguradora NCH = 1 cargo inicial y "
            f"1 adicional pasando cada {DIAS_RPBI_ADICIONAL} días; "
            f"seguros NCH = cargo diario de ingreso a egreso. "
            f"Estancia calculada: {dias if dias is not None else '?'} día(s)."
        ),
    })

    # Días de habitación
    # Regla ajustada: habitación ambulatoria (HOS-0000003) espera 1 cargo
    # aunque el cálculo de noches sea 0. Para habitación estándar se conserva
    # la comparación contra noches, pero las diferencias se dejan como verificar
    # para evitar falso error crítico cuando hay paquetes/convenios.
    hab_items = por_codigo(CODIGOS_HABITACION)
    hab_cobrado = len(hab_items)
    hay_hab_ambulatoria = any(i["codigo"] == "HOS-0000003" for i in hab_items)

    if hay_hab_ambulatoria:
        esperado_hab = 1.0
        nota_hab_base = (
            "Cuenta con habitación ambulatoria (HOS-0000003): se espera 1 cargo "
            "aunque la estancia calculada sea 0 noches."
        )
    elif dias is not None:
        esperado_hab = float(dias)
        nota_hab_base = (
            f"Ingreso {data['fecha_ingreso']} → egreso {data['fecha_egreso']} "
            f"= {dias} noche(s). Confirmar política de cobro en paquetes/convenios "
            f"si existe diferencia."
        )
    else:
        esperado_hab = None
        nota_hab_base = "Sin fechas de estancia suficientes para calcular días esperados."

    if hab_items or dias is not None:
        status, diff, clase = evaluar(float(hab_cobrado), esperado_hab, 0)
        if clase == "err":
            # La diferencia de habitación requiere confirmación operativa antes
            # de tratarse como error financiero crítico.
            clase = "warn"
            status = "verificar — " + status
        auditorias.append({
            "categoria": "Estancia",
            "key":       "habitacion",
            "label":     "Días de habitación",
            "tipo":      "numerico",
            "unidad":    "días",
            "cobrado":   float(hab_cobrado),
            "esperado":  esperado_hab,
            "status":    status,
            "diff":      diff,
            "clase":     clase,
            "items_cobrados":  hab_items,
            "items_esperados": [],
            "nota_auditoria": nota_hab_base,
        })

    # Bomba de infusión (existente)
    bomba_items = por_codigo({CODIGO_BOMBA})
    bomba_cobrado = len(bomba_items)
    if bomba_items:
        limite = dias if dias else None
        if limite and bomba_cobrado > limite:
            status, clase = f"cobradas {bomba_cobrado} de {limite} días — revisar", "warn"
        elif limite:
            status, clase = f"ok — {bomba_cobrado} de {limite} días", "ok"
        else:
            status, clase = f"{bomba_cobrado} cargo(s)", "gray"
        auditorias.append({
            "categoria": "Estancia",
            "key":       "bomba",
            "label":     "Bomba de infusión",
            "tipo":      "numerico",
            "unidad":    "días",
            "cobrado":   float(bomba_cobrado),
            "esperado":  float(dias) if dias is not None else None,
            "status":    status,
            "diff":      None,
            "clase":     clase,
            "items_cobrados":  bomba_items,
            "items_esperados": [],
            "nota_auditoria": "Cargos de IBM-0000001 vs días de estancia.",
        })

    # Dietas
    nut_items = [i for i in items if i["codigo"].startswith("NUT-")]
    nut_cobrado = sum(i["cantidad"] for i in nut_items)
    if nut_items and dias:
        max_esperado = dias * 4
        if nut_cobrado > max_esperado:
            status, clase = f"{nut_cobrado:.0f} dietas para {dias} día(s) — revisar", "warn"
        else:
            status, clase = f"{nut_cobrado:.0f} dietas en {dias} día(s) — normal", "ok"
        auditorias.append({
            "categoria": "Estancia",
            "key":       "dietas",
            "label":     "Dietas",
            "tipo":      "numerico",
            "unidad":    "servicios",
            "cobrado":   nut_cobrado,
            "esperado":  None,
            "status":    status,
            "diff":      None,
            "clase":     clase,
            "items_cobrados":  nut_items,
            "items_esperados": [],
            "nota_auditoria": (
                f"Máximo razonable: {dias} día(s) × 4 = {dias*4} servicios. "
                f"Se cobraron {nut_cobrado:.0f}."
            ),
        })

    # ══════════════════════════════════════════════════════
    # Post-proceso: calcular monto económico de cada hallazgo
    # cuando sea posible. Solo aplica a auditorías numéricas
    # con diff distinto de cero y donde haya items cobrados
    # como referencia de precio.
    # ══════════════════════════════════════════════════════
    for a in auditorias:
        a["monto_diff"] = None
        if a.get("tipo") != "numerico":
            continue
        if a.get("clase") not in ("err", "warn"):
            continue
        diff = a.get("diff")
        if diff is None:
            continue
        items_ref = a.get("items_cobrados") or []
        a["monto_diff"] = _calcular_monto_diff(diff, items_ref)

    return auditorias

# =========================================================
# Fix 3: REPORTE HTML DESCARGABLE POR CUENTA
# =========================================================
def _construir_html_reporte_cuenta(
    cuenta: str, data: dict, auds: list, file_hash: str,
) -> str:
    """Genera un HTML imprimible para una sola cuenta."""
    ICON  = {"ok": "✅", "err": "❌", "warn": "⚠️", "gray": "ℹ️"}
    COLOR = {"ok": "#27500A", "err": "#791F1F", "warn": "#633806", "gray": "#444441"}
    BG    = {"ok": "#EAF3DE", "err": "#FCEBEB", "warn": "#FAEEDA", "gray": "#F1EFE8"}

    estado_txt, clase = estado_global(auds)
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    archivos_cuenta = ", ".join(af["archivo"] for af in data["archivos"])

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Auditoría {cuenta}</title>
<style>
  body{{font-family:Arial,sans-serif;max-width:900px;margin:20px auto;color:#222;font-size:13px}}
  h1{{color:#185FA5;font-size:20px;border-bottom:2px solid #185FA5;padding-bottom:6px}}
  .meta{{color:#777;font-size:11px;margin-bottom:16px}}
  .finding{{border-left:3px solid;padding:6px 12px;margin:6px 0;border-radius:0 6px 6px 0}}
  .finding-err{{border-color:#E24B4A;background:#FCEBEB;color:#791F1F}}
  .finding-warn{{border-color:#EF9F27;background:#FAEEDA;color:#633806}}
  table{{border-collapse:collapse;width:100%;margin:10px 0}}
  th{{background:#f0f0ec;padding:6px 10px;text-align:left;font-weight:500;font-size:12px;
      border-bottom:1px solid #ddd}}
  td{{padding:6px 10px;border-bottom:1px solid #eee;font-size:12px}}
  .cat{{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.07em;
       color:#555;margin:18px 0 6px;padding-bottom:4px;border-bottom:1px solid #ddd}}
  @media print{{ body{{margin:0}} }}
</style></head><body>

<h1>🏥 Auditoría — {cuenta}</h1>
<p><b>Paciente:</b> {data["paciente"] or "No identificado"}<br>
<b>Seguro:</b> {data.get("seguro","N/A")}<br>
<b>Ingreso:</b> {data.get("fecha_ingreso","?")} → <b>Egreso:</b> {data.get("fecha_egreso","?")}
  ({data.get("dias_estancia","?")} día(s))<br>
<b>Estado:</b> <span style="color:{COLOR[clase]}">{ICON[clase]} {estado_txt}</span></p>
<p class="meta">Generado: {timestamp} · Hash archivos: {file_hash[:12]}…<br>
Archivos: {archivos_cuenta}</p>
"""
    # Hallazgos
    errores = [a for a in auds if a["clase"] in ("err", "warn")]
    if errores:
        html += "<h2>Hallazgos</h2>"
        for a in errores:
            cls = "finding-err" if a["clase"] == "err" else "finding-warn"
            html += (f'<div class="finding {cls}"><b>{a["label"]}:</b> {a["status"]}.'
                     + (f' {a["nota_auditoria"]}' if a.get("nota_auditoria") else "")
                     + '</div>')

    # Tabla de auditorías
    categorias = []
    for a in auds:
        if a["categoria"] not in categorias:
            categorias.append(a["categoria"])

    for cat in categorias:
        html += f'<div class="cat">{cat}</div>'
        html += '<table><tr><th>Auditoría</th><th style="text-align:right">Cobrado</th>'
        html += '<th style="text-align:right">Esperado</th><th>Resultado</th></tr>'
        for a in [x for x in auds if x["categoria"] == cat]:
            u = a.get("unidad", "")
            cob = f"{a['cobrado']:.2f} {u}".strip() if a["cobrado"] is not None else "—"
            esp = f"{a['esperado']:.2f} {u}".strip() if a.get("esperado") is not None else "—"
            icon = ICON.get(a["clase"], "")
            color = COLOR.get(a["clase"], "#222")
            html += (f'<tr><td>{a["label"]}</td>'
                     f'<td style="text-align:right">{cob}</td>'
                     f'<td style="text-align:right">{esp}</td>'
                     f'<td style="color:{color}">{icon} {a["status"]}</td></tr>')
            if a.get("nota_auditoria") and a["clase"] in ("err","warn","gray"):
                html += (f'<tr><td colspan="4" style="padding:2px 10px 6px 24px;'
                         f'font-size:11px;color:#777;font-style:italic">'
                         f'{a["nota_auditoria"]}</td></tr>')
        html += '</table>'

    html += """
<p style="font-size:10px;color:#aaa;margin-top:30px;border-top:1px solid #eee;padding-top:6px">
  Reporte generado automáticamente por Auditor Hospitalario.
</p></body></html>"""
    return html

# =========================================================
# ESTADO GLOBAL DE CUENTA
# =========================================================
def estado_global(auditorias: list):
    clases = [a["clase"] for a in auditorias]
    if "err"  in clases: return "Con diferencias", "err"
    if "warn" in clases: return "Revisar",         "warn"
    if "ok"   in clases: return "Sin diferencias", "ok"
    return "Sin referencias", "gray"

# =========================================================
# COMPONENTES DE UI
# =========================================================
def badge_html(txt, cls):
    return f'<span class="badge badge-{cls}">{txt}</span>'

def dot_html(cls):
    return f'<span class="dot dot-{cls}"></span>'

def barra_html(cobrado, esperado, cls):
    if not esperado or esperado == 0:
        pct = 100
    else:
        pct = min(round(cobrado / esperado * 100), 100)
    return (f'<div class="bar-wrap">'
            f'<div class="bar-fill bar-{cls}" style="width:{pct}%"></div>'
            f'</div>')

def render_tabla_items(items: list, cols: list):
    if not items:
        st.markdown('<p style="font-size:12px;color:var(--color-text-secondary)">Sin ítems.</p>',
                    unsafe_allow_html=True)
        return
    encabezados = "".join(
        f'<th{"" if c[1]!="r" else " style=text-align:right"}>{c[0]}</th>'
        for c in cols
    )
    filas = ""
    for it in items:
        celdas = ""
        for c in cols:
            v = it.get(c[2], "")
            align = ' style="text-align:right"' if c[1] == "r" else ""
            mono  = ' class="mono"' if c[1] == "m" else ""
            if isinstance(v, float):
                v = f"{v:.3f}" if "cantidad" in c[2] else f"{v:.2f}"
            celdas += f'<td{align}{mono}>{h(v)}</td>'
        filas += f"<tr>{celdas}</tr>"
    st.markdown(
        f'<table class="ev-table"><thead><tr>{encabezados}</tr></thead>'
        f'<tbody>{filas}</tbody></table>',
        unsafe_allow_html=True,
    )

COLS_COBRO = [
    ("Área",       "",  "area"),
    ("Código",     "m", "codigo"),
    ("Descripción","",  "descripcion"),
    ("Cant.",      "r", "cantidad"),
    ("Fecha",      "",  "fecha"),
    ("Folio",      "m", "folio"),
]

COLS_ESPERADO = [
    ("Área",          "",  "area"),
    ("Hrs esperadas", "r", "cantidad_esperada"),
    ("Línea original","m", "linea_original"),
]


def _ui_audit_is_catalogo(a: dict) -> bool:
    return a.get("categoria") == "Alertas de catálogo" or str(a.get("key", "")).startswith("catalogo_")


def _ui_audit_is_financiero(a: dict) -> bool:
    """Clasificación visual solamente. No modifica la lógica de auditoría."""
    if _ui_audit_is_catalogo(a):
        return False
    if a.get("clase") not in ("err", "warn"):
        return False
    categoria = a.get("categoria", "")
    if a.get("monto_diff"):
        return True
    if a.get("tipo") == "numerico" and a.get("diff") is not None:
        return categoria in {"Oxígeno", "Sala quirúrgica", "Estancia"}
    return categoria in {"Accesorios complementarios", "Verificaciones negativas"} and a.get("clase") == "err"


def _ui_audit_is_operativo(a: dict) -> bool:
    if a.get("clase") not in ("err", "warn"):
        return False
    if _ui_audit_is_catalogo(a):
        return False
    if _ui_audit_is_financiero(a):
        return False
    return True


def _ui_loader_markup(total_archivos: int) -> str:
    plural = "archivo" if total_archivos == 1 else "archivos"
    return f"""
    <div class="audit-loader-overlay">
      <div class="audit-loader-card">
        <div class="audit-loader-logo-wrap"><img class="audit-loader-logo" src="{LOGO_NCH_URL}" /></div>
        <div class="audit-loader-ring"></div>
        <div class="audit-loader-title">Analizando cuentas hospitalarias</div>
        <div class="audit-loader-sub">
          Estamos leyendo {total_archivos} {plural}, cruzando hoja de servicios, estado de cuenta,
          nota post-quirúrgica, códigos y reglas de auditoría.
        </div>
        <div class="audit-loader-steps">
          <span class="audit-loader-step">PDFs</span>
          <span class="audit-loader-step">Códigos</span>
          <span class="audit-loader-step">Reglas</span>
          <span class="audit-loader-step">Evidencia</span>
        </div>
        <div class="audit-loader-bar"><div class="audit-loader-bar-fill"></div></div>
      </div>
    </div>
    """


def _ui_groups(auds: list) -> dict:
    financieros = [a for a in auds if _ui_audit_is_financiero(a)]
    catalogo = [a for a in auds if _ui_audit_is_catalogo(a) and a.get("clase") in ("err", "warn")]
    operativos = [a for a in auds if _ui_audit_is_operativo(a)]
    ok = [a for a in auds if a.get("clase") == "ok"]
    informativos = [a for a in auds if a.get("clase") == "gray" and not _ui_audit_is_catalogo(a)]
    return {
        "financieros": financieros,
        "operativos": operativos,
        "catalogo": catalogo,
        "ok": ok,
        "informativos": informativos,
    }


def _ui_count(auds: list) -> dict:
    g = _ui_groups(auds)
    return {k: len(v) for k, v in g.items()}


def _ui_riesgo(auds: list):
    c = _ui_count(auds)
    if c["financieros"] > 0:
        return "Alto", "err", "Diferencias financieras o cargos a corregir"
    if c["operativos"] > 0:
        return "Medio", "warn", "Requiere confirmación operativa"
    if c["catalogo"] > 0:
        return "Catálogo", "blue", "Revisar códigos con sistemas/Jordan"
    if c["ok"] > 0:
        return "Bajo", "ok", "Sin hallazgos relevantes"
    return "Sin referencias", "gray", "Sin evidencia suficiente"


def _ui_money(auds: list) -> float:
    return sum(
        a.get("monto_diff") or 0
        for a in auds
        if a.get("clase") in ("err", "warn") and a.get("monto_diff")
    )


def _ui_pill(txt: str, cls: str) -> str:
    return f'<span class="ux-pill ux-pill-{cls}">{h(txt)}</span>'


def _ui_kpi(label: str, value: str, sub: str = ""):
    st.markdown(
        f'<div class="kpi-card"><div class="kpi-label">{h(label)}</div>'
        f'<div class="kpi-value">{h(value)}</div>'
        f'<div class="kpi-sub">{h(sub)}</div></div>',
        unsafe_allow_html=True,
    )


def _ui_format_num(v, unidad=""):
    if v is None:
        return "—"
    try:
        if isinstance(v, float):
            txt = f"{v:.2f}"
        else:
            txt = str(v)
    except Exception:
        txt = str(v)
    return f"{txt} {unidad}".strip()


def _ui_audit_card_class(audit: dict) -> str:
    if _ui_audit_is_catalogo(audit):
        return "blue"
    if audit.get("clase") == "err":
        return "red"
    if audit.get("clase") == "warn":
        return "yellow"
    if audit.get("clase") == "ok":
        return "green"
    return "gray"


def render_auditoria(audit: dict):
    """Render visual v2. Solo cambia presentación, no modifica reglas."""
    tipo  = audit.get("tipo", "")
    label = audit.get("label", "Auditoría")
    status = audit.get("status", "")
    unidad = audit.get("unidad", "")
    card_cls = _ui_audit_card_class(audit)

    if _ui_audit_is_catalogo(audit):
        badge = _ui_pill("Catálogo / sistemas", "blue")
    elif audit.get("clase") == "err":
        badge = _ui_pill("Crítico", "red")
    elif audit.get("clase") == "warn":
        badge = _ui_pill("Revisar", "yellow")
    elif audit.get("clase") == "ok":
        badge = _ui_pill("OK", "green")
    else:
        badge = _ui_pill("Informativo", "gray")

    detalle = ""
    if tipo == "numerico":
        detalle = (
            f"Cobrado: <b>{h(_ui_format_num(audit.get('cobrado'), unidad))}</b> · "
            f"Esperado: <b>{h(_ui_format_num(audit.get('esperado'), unidad))}</b>"
        )
        monto = audit.get("monto_diff")
        if monto is not None and monto >= 1:
            diff = audit.get("diff", 0) or 0
            etiqueta = "sobrecobro" if diff > 0 else "faltante"
            detalle += f" · <b>≈ ${monto:,.0f} {h(etiqueta)}</b>"
    elif tipo == "binario":
        marcado = audit.get("marcado")
        cobrado_b = audit.get("cobrado_bool")
        detalle = (
            f"Servicios de cirugía: <b>{'marcado' if marcado else 'no marcado'}</b> · "
            f"Estado de cuenta: <b>{'cobrado' if cobrado_b else 'no cobrado'}</b>"
        )
    elif tipo == "negativo":
        detalle = f"Cargos encontrados en estado de cuenta: <b>{int(audit.get('cobrado') or 0)}</b>"
    else:
        detalle = h(status)

    nota = audit.get("nota_auditoria")
    nota_html = f'<div class="audit-card-note">{h(nota)}</div>' if nota else ""

    st.markdown(
        f'<div class="audit-card audit-card-{card_cls}">'
        f'<div class="audit-card-head">'
        f'<div><div class="audit-card-title">{h(label)}</div>'
        f'<div class="audit-card-result"><b>Resultado:</b> {h(status)}</div></div>'
        f'<div>{badge}</div>'
        f'</div>'
        f'<div class="audit-card-result">{detalle}</div>'
        f'{nota_html}'
        f'</div>',
        unsafe_allow_html=True,
    )

    items_cob = audit.get("items_cobrados", [])
    items_esp = audit.get("items_esperados", [])
    if items_cob or items_esp:
        with st.expander("Ver evidencia", expanded=False):
            if items_esp:
                st.markdown("**Esperado / documentado**")
                render_tabla_items(items_esp, COLS_ESPERADO)
            if items_cob:
                st.markdown("**Cobrado en estado de cuenta**")
                render_tabla_items(items_cob, COLS_COBRO)


def render_grupo_auditorias(titulo: str, descripcion: str, auds: list, color: str, empty_msg: str = "Sin hallazgos.", expanded: bool = True):
    total = len(auds)
    st.markdown(
        f'<div class="cat-title section-title-{h(color)}">{h(titulo)} '
        f'<span style="font-weight:400;text-transform:none;letter-spacing:0">· {total}</span></div>',
        unsafe_allow_html=True,
    )
    if descripcion:
        st.caption(descripcion)
    if not auds:
        st.markdown(
            f'<div class="finding-box finding-gray">{h(empty_msg)}</div>',
            unsafe_allow_html=True,
        )
        return
    cont = st.container()
    with cont:
        for audit in auds:
            render_auditoria(audit)

# =========================================================
# LOG POR EMAIL  (invisible al usuario)
# =========================================================
def _hash_archivos(archivos_bytes: list) -> str:
    h = hashlib.sha256()
    for nombre, contenido in archivos_bytes:
        h.update(nombre.encode("utf-8"))
        h.update(str(len(contenido)).encode("utf-8"))
        h.update(contenido)
    return h.hexdigest()

def _construir_html_log(
    cuentas: dict,
    todas_auditorias: dict,
    archivos_bytes: list,
    timestamp: str,
) -> str:
    ICON = {"ok": "✅", "err": "❌", "warn": "⚠️", "gray": "ℹ️"}
    COLOR = {"ok": "#27500A", "err": "#791F1F", "warn": "#633806", "gray": "#444441"}
    BG    = {"ok": "#EAF3DE", "err": "#FCEBEB", "warn": "#FAEEDA", "gray": "#F1EFE8"}

    total = len(cuentas)
    con_err  = sum(1 for auds in todas_auditorias.values()
                   if any(a["clase"] == "err"  for a in auds))
    con_warn = sum(1 for auds in todas_auditorias.values()
                   if any(a["clase"] == "warn" for a in auds))
    sin_diff = total - con_err - con_warn

    archivos_lista = "".join(
        f"<li style='font-size:12px;color:#555'>{n}</li>"
        for n, _ in archivos_bytes
    )

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:800px;margin:0 auto;color:#222">
    <h2 style="border-bottom:2px solid #185FA5;padding-bottom:8px;color:#185FA5">
      🏥 Log de auditoría hospitalaria
    </h2>
    <p style="color:#555;font-size:13px">
      <b>Fecha y hora:</b> {timestamp}<br>
      <b>Archivos procesados ({len(archivos_bytes)}):</b>
    </p>
    <ul style="margin:0 0 16px">{archivos_lista}</ul>
    <table style="border-collapse:collapse;width:100%;font-size:13px;margin-bottom:24px">
      <tr style="background:#185FA5;color:#fff">
        <td style="padding:8px 12px">Cuentas analizadas</td>
        <td style="padding:8px 12px">Con errores críticos</td>
        <td style="padding:8px 12px">Con advertencias</td>
        <td style="padding:8px 12px">Sin diferencias</td>
      </tr>
      <tr style="background:#f5f5f5">
        <td style="padding:8px 12px;text-align:center;font-weight:bold">{total}</td>
        <td style="padding:8px 12px;text-align:center;color:#791F1F;font-weight:bold">{con_err}</td>
        <td style="padding:8px 12px;text-align:center;color:#633806;font-weight:bold">{con_warn}</td>
        <td style="padding:8px 12px;text-align:center;color:#27500A;font-weight:bold">{sin_diff}</td>
      </tr>
    </table>
    """

    for cuenta, data in cuentas.items():
        auds       = todas_auditorias[cuenta]
        estado_txt, clase = estado_global(auds)
        archivos_cuenta = ", ".join(af["archivo"] for af in data["archivos"])

        html += f"""
        <div style="border:1px solid #ddd;border-radius:8px;margin-bottom:20px;overflow:hidden">
          <div style="background:{BG[clase]};padding:10px 16px;border-bottom:1px solid #ddd">
            <span style="font-weight:bold;font-size:15px;color:{COLOR[clase]}">
              {ICON[clase]} {cuenta}
            </span>
            <span style="font-size:13px;color:#555;margin-left:12px">
              {data["paciente"] or "No identificado"}
            </span>
            <span style="float:right;font-size:12px;color:#777">
              {data.get("fecha_ingreso","?")} → {data.get("fecha_egreso","?")}
              ({data.get("dias_estancia","?")} día(s))
            </span>
          </div>
          <div style="padding:8px 16px;font-size:12px;color:#555;background:#fafafa;
                      border-bottom:1px solid #eee">
            Archivos: {archivos_cuenta}
          </div>
          <table style="border-collapse:collapse;width:100%;font-size:13px">
            <tr style="background:#f0f0ec">
              <th style="padding:7px 12px;text-align:left;font-weight:500;color:#444">Auditoría</th>
              <th style="padding:7px 12px;text-align:left;font-weight:500;color:#444">Categoría</th>
              <th style="padding:7px 12px;text-align:right;font-weight:500;color:#444">Cobrado</th>
              <th style="padding:7px 12px;text-align:right;font-weight:500;color:#444">Esperado</th>
              <th style="padding:7px 12px;text-align:left;font-weight:500;color:#444">Resultado</th>
            </tr>
        """

        for i, a in enumerate(auds):
            bg_fila = "#fff" if i % 2 == 0 else "#fafafa"
            unidad  = a.get("unidad", "")
            cobrado_txt  = f"{a['cobrado']:.2f} {unidad}".strip() if a["cobrado"] is not None else "—"
            esperado_txt = f"{a['esperado']:.2f} {unidad}".strip() if a.get("esperado") is not None else "—"
            icon_r = ICON.get(a["clase"], "?")
            color_r = COLOR.get(a["clase"], "#222")

            html += f"""
            <tr style="background:{bg_fila}">
              <td style="padding:6px 12px">{a["label"]}</td>
              <td style="padding:6px 12px;color:#777">{a["categoria"]}</td>
              <td style="padding:6px 12px;text-align:right">{cobrado_txt}</td>
              <td style="padding:6px 12px;text-align:right">{esperado_txt}</td>
              <td style="padding:6px 12px;color:{color_r};font-weight:500">
                {icon_r} {a["status"]}
              </td>
            </tr>
            """
            if a.get("nota_auditoria") and a["clase"] in ("err", "warn", "gray"):
                html += f"""
                <tr style="background:{bg_fila}">
                  <td colspan="5" style="padding:2px 12px 8px 24px;
                      font-size:11px;color:#777;font-style:italic">
                    {a["nota_auditoria"]}
                  </td>
                </tr>
                """

        html += "</table></div>"

    html += """
    <p style="font-size:11px;color:#aaa;margin-top:24px;border-top:1px solid #eee;padding-top:8px">
      Este correo es un log automático generado por el Auditor Hospitalario.
      No responder a este mensaje.
    </p>
    </body></html>
    """
    return html

def _enviar_log_email(
    cuentas: dict,
    todas_auditorias: dict,
    archivos_bytes: list,
) -> None:
    try:
        cfg = st.secrets.get("email_log", {})
        if not cfg:
            return

        smtp_host = cfg.get("smtp_host", "")
        smtp_port = int(cfg.get("smtp_port", 587))
        smtp_user = cfg.get("smtp_user", "")
        smtp_pass = cfg.get("smtp_password", "")
        destino   = cfg.get("destino", "")

        if not all([smtp_host, smtp_user, smtp_pass, destino]):
            return

        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        total     = len(cuentas)
        con_diff  = sum(
            1 for auds in todas_auditorias.values()
            if any(a["clase"] in ("err","warn") for a in auds)
        )

        asunto = (
            f"[Auditoría] {total} cuenta(s) analizadas — "
            f"{con_diff} con diferencias — {timestamp}"
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"]    = smtp_user
        msg["To"]      = destino

        cuerpo_html = _construir_html_log(
            cuentas, todas_auditorias, archivos_bytes, timestamp
        )
        msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as servidor:
            servidor.ehlo()
            servidor.starttls()
            servidor.login(smtp_user, smtp_pass)
            servidor.sendmail(smtp_user, destino, msg.as_string())

    except Exception:
        logging.exception("Error enviando log de auditoría")


# =========================================================
# FRONTEND V4 — PRODUCTO DE AUDITORÍA OPERATIVA
# =========================================================
LOGO_NCH_URL = "https://newcityhospital.com/wp-content/uploads/2023/08/logo_newcity_hospital.png"

# Mantener la misma tolerancia por defecto del MVP original.
if "tolerancia_ui" not in st.session_state:
    st.session_state["tolerancia_ui"] = 0.01

tolerancia_ui = float(st.session_state.get("tolerancia_ui", 0.01))

st.markdown("""
<style>
/* ================= FRONTEND V4 ================= */
.block-container{
  max-width:1280px;
  padding-top:1.25rem;
  padding-left:2rem;
  padding-right:2rem;
}
#MainMenu, footer {visibility:hidden;}
header[data-testid="stHeader"]{background:rgba(255,255,255,.72);backdrop-filter:blur(10px);}

.nch-header{
  width:100%;
  border:1px solid #E6EAF0;
  border-radius:26px;
  padding:22px 26px;
  background:linear-gradient(135deg,#FFFFFF 0%,#F8FBFD 48%,#F3FAFB 100%);
  box-shadow:0 18px 50px rgba(16,24,40,.07);
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:24px;
  margin-bottom:16px;
}
.nch-brand{display:flex;align-items:center;gap:18px;min-width:0;}
.nch-logo-wrap{
  width:86px;height:70px;border-radius:18px;background:#FFFFFF;
  border:1px solid #E6EAF0;display:flex;align-items:center;justify-content:center;
  box-shadow:0 8px 24px rgba(16,24,40,.06);flex-shrink:0;
}
.nch-logo{max-width:72px;max-height:55px;object-fit:contain;}
.nch-eyebrow{font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.12em;color:#0E7490;margin-bottom:4px;}
.nch-title{font-size:34px;font-weight:850;line-height:1.05;color:#101828;letter-spacing:-.03em;}
.nch-subtitle{font-size:14px;color:#667085;line-height:1.45;margin-top:8px;max-width:760px;}
.nch-header-right{text-align:right;min-width:180px;}
.nch-status{
  display:inline-flex;align-items:center;gap:8px;background:#ECFDF3;color:#027A48;
  border:1px solid #ABEFC6;padding:8px 12px;border-radius:999px;font-size:12px;font-weight:800;
}
.nch-status-dot{width:8px;height:8px;border-radius:50%;background:#12B76A;display:inline-block;}
.nch-version{font-size:11px;color:#98A2B3;margin-top:8px;}

.action-bar{
  display:flex;align-items:center;justify-content:space-between;gap:14px;
  border:1px solid #EEF2F6;border-radius:18px;padding:12px 14px;background:#FFFFFF;
  margin-bottom:24px;box-shadow:0 4px 18px rgba(16,24,40,.035);
}
.action-help{font-size:13px;color:#667085;line-height:1.4;}

.upload-shell{
  border:1px dashed #B8CBD8;border-radius:22px;padding:18px;background:#F8FBFD;margin-bottom:24px;
}
.upload-title{font-size:16px;font-weight:800;color:#101828;margin-bottom:4px;}
.upload-sub{font-size:13px;color:#667085;margin-bottom:8px;}

.empty-state{
  border:1px solid #E6EAF0;border-radius:26px;padding:34px;
  background:linear-gradient(135deg,#FFFFFF 0%,#F8FBFD 100%);
  box-shadow:0 16px 45px rgba(16,24,40,.06);margin-top:12px;
}
.empty-title{font-size:26px;font-weight:850;letter-spacing:-.02em;color:#101828;margin-bottom:8px;}
.empty-sub{font-size:15px;color:#667085;line-height:1.55;max-width:780px;}
.empty-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:22px;}
.empty-card{border:1px solid #EEF2F6;border-radius:18px;padding:16px;background:#FFFFFF;}
.empty-card-title{font-size:14px;font-weight:800;color:#101828;margin-bottom:6px;}
.empty-card-sub{font-size:12px;color:#667085;line-height:1.5;}

.executive-title{font-size:24px;font-weight:850;color:#101828;letter-spacing:-.02em;margin:10px 0 4px;}
.executive-sub{font-size:13px;color:#667085;margin-bottom:14px;}
.kpi-card{
  border:1px solid #E6EAF0;border-radius:18px;padding:16px 18px;background:#FFFFFF;height:100%;
  box-shadow:0 6px 24px rgba(16,24,40,.045);
}
.kpi-label{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#667085;font-weight:850;margin-bottom:8px;}
.kpi-value{font-size:28px;font-weight:850;line-height:1;color:#101828;letter-spacing:-.03em;}
.kpi-sub{font-size:11px;color:#667085;margin-top:8px;line-height:1.35;}
.kpi-red .kpi-value{color:#B42318}.kpi-yellow .kpi-value{color:#B54708}.kpi-blue .kpi-value{color:#175CD3}.kpi-green .kpi-value{color:#027A48}
.audit-meta-line{font-size:12px;color:#98A2B3;margin:14px 0 26px;}
.audit-meta-line code{color:#344054;background:#F2F4F7;padding:2px 6px;border-radius:6px;}

.filter-card{
  border:1px solid #EEF2F6;border-radius:20px;padding:16px;background:#FFFFFF;margin:18px 0;
  box-shadow:0 4px 18px rgba(16,24,40,.035);
}
.case-card{
  border:1px solid #E6EAF0;border-radius:22px;padding:18px 20px;background:#FFFFFF;margin-bottom:12px;
  box-shadow:0 8px 28px rgba(16,24,40,.045);
}
.case-card:hover{box-shadow:0 12px 34px rgba(16,24,40,.075);border-color:#D0D5DD;}
.case-top{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;}
.case-left{display:flex;align-items:flex-start;gap:14px;min-width:0;}
.case-dot{width:13px;height:13px;border-radius:50%;margin-top:5px;flex-shrink:0;}
.case-dot-red{background:#F04438}.case-dot-yellow{background:#F79009}.case-dot-blue{background:#2E90FA}.case-dot-green{background:#12B76A}.case-dot-gray{background:#98A2B3}
.case-title{font-size:17px;font-weight:850;color:#101828;letter-spacing:-.01em;}
.case-sub{font-size:13px;color:#667085;line-height:1.45;margin-top:4px;}
.case-meta{font-size:12px;color:#98A2B3;line-height:1.45;margin-top:7px;}
.case-badges{text-align:right;min-width:260px;}
.ux-pill{display:inline-flex;align-items:center;font-size:11px;font-weight:800;padding:5px 9px;border-radius:999px;margin:2px 3px;white-space:nowrap;}
.ux-pill-red{background:#FEE4E2;color:#B42318}.ux-pill-yellow{background:#FEF0C7;color:#B54708}
.ux-pill-blue{background:#D1E9FF;color:#175CD3}.ux-pill-green{background:#D1FADF;color:#027A48}
.ux-pill-gray{background:#F2F4F7;color:#475467}.ux-pill-dark{background:#101828;color:#FFFFFF}

.audit-card{
  border:1px solid #E6EAF0;border-radius:16px;padding:14px 16px;margin-bottom:10px;background:#FFFFFF;
  box-shadow:0 3px 14px rgba(16,24,40,.025);
}
.audit-card-red{border-left:5px solid #F04438}.audit-card-yellow{border-left:5px solid #F79009}
.audit-card-blue{border-left:5px solid #2E90FA}.audit-card-green{border-left:5px solid #12B76A}.audit-card-gray{border-left:5px solid #98A2B3}
.audit-card-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:6px;}
.audit-card-title{font-size:14px;font-weight:850;color:#101828;}
.audit-card-result{font-size:12px;line-height:1.48;color:#667085;margin-top:4px;}
.audit-card-note{font-size:12px;line-height:1.48;color:#475467;background:#F8FAFC;border-radius:10px;padding:9px 11px;margin-top:9px;}
.cat-title{font-size:12px;font-weight:850;text-transform:uppercase;letter-spacing:.07em;color:#667085;margin:18px 0 8px;padding-bottom:6px;border-bottom:1px solid #EEF2F6;}
.section-title-red{color:#B42318}.section-title-yellow{color:#B54708}.section-title-blue{color:#175CD3}.section-title-green{color:#027A48}.section-title-gray{color:#475467}
.finding-box{border-left:4px solid;padding:10px 12px;border-radius:0 10px 10px 0;font-size:13px;margin-bottom:8px;line-height:1.5;}
.finding-err{border-color:#F04438;background:#FEF3F2;color:#B42318}.finding-warn{border-color:#F79009;background:#FFFAEB;color:#B54708}
.finding-blue{border-color:#2E90FA;background:#EFF8FF;color:#175CD3}.finding-ok{border-color:#12B76A;background:#ECFDF3;color:#027A48}.finding-gray{border-color:#98A2B3;background:#F8FAFC;color:#475467}
.ev-table{width:100%;border-collapse:collapse;font-size:12px;background:#FFFFFF;border:1px solid #EEF2F6;border-radius:10px;overflow:hidden;}
.ev-table th{text-align:left;padding:8px 10px;background:#F8FAFC;border-bottom:1px solid #EEF2F6;font-weight:800;color:#475467;}
.ev-table td{padding:8px 10px;border-bottom:1px solid #F2F4F7;color:#344054;vertical-align:top;}
.ev-table tr:last-child td{border-bottom:none;}
.mono{font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;font-size:11px;}
.muted-small{font-size:11px;color:#98A2B3;}
.config-note{font-size:13px;color:#667085;line-height:1.55;background:#F8FAFC;border:1px solid #EEF2F6;border-radius:14px;padding:12px;margin-bottom:12px;}


/* Modal de detalle: vista amplia tipo app, sin perder al auditor en la pantalla principal */
div[data-testid="stDialog"] div[role="dialog"]{
  width:min(1120px, calc(100vw - 48px)) !important;
  max-width:1120px !important;
  border-radius:24px !important;
}
div[data-testid="stDialog"] section{
  max-height:88vh !important;
}
.modal-helper{
  font-size:12px;
  color:#667085;
  background:#F8FAFC;
  border:1px solid #EEF2F6;
  border-radius:14px;
  padding:10px 12px;
  margin-bottom:12px;
}

/* Loader central de análisis */
.audit-loader-overlay{
  position:fixed;
  inset:0;
  z-index:999999;
  display:flex;
  align-items:center;
  justify-content:center;
  background:rgba(248,250,252,.82);
  backdrop-filter:blur(9px);
  -webkit-backdrop-filter:blur(9px);
}
.audit-loader-card{
  width:min(520px, calc(100vw - 36px));
  border:1px solid #E6EAF0;
  border-radius:28px;
  padding:28px 30px 26px;
  background:linear-gradient(135deg,#FFFFFF 0%,#F8FBFD 100%);
  box-shadow:0 24px 70px rgba(16,24,40,.18);
  text-align:center;
  position:relative;
  overflow:hidden;
}
.audit-loader-card:before{
  content:"";
  position:absolute;
  left:-35%;
  top:0;
  width:35%;
  height:100%;
  background:linear-gradient(90deg, transparent, rgba(46,144,250,.10), transparent);
  animation:auditLoaderSweep 1.85s ease-in-out infinite;
}
.audit-loader-logo-wrap{
  width:92px;
  height:72px;
  margin:0 auto 16px;
  border-radius:20px;
  background:#FFFFFF;
  border:1px solid #E6EAF0;
  display:flex;
  align-items:center;
  justify-content:center;
  box-shadow:0 10px 26px rgba(16,24,40,.08);
  position:relative;
  z-index:1;
}
.audit-loader-logo{max-width:76px;max-height:56px;object-fit:contain;}
.audit-loader-ring{
  width:54px;
  height:54px;
  border-radius:50%;
  border:5px solid #EAF2FF;
  border-top-color:#2E90FA;
  border-right-color:#0E7490;
  margin:0 auto 16px;
  animation:auditLoaderSpin .9s linear infinite;
  position:relative;
  z-index:1;
}
.audit-loader-title{
  font-size:22px;
  font-weight:850;
  color:#101828;
  letter-spacing:-.02em;
  margin-bottom:8px;
  position:relative;
  z-index:1;
}
.audit-loader-sub{
  font-size:13px;
  color:#667085;
  line-height:1.55;
  margin:0 auto 18px;
  max-width:410px;
  position:relative;
  z-index:1;
}
.audit-loader-steps{
  display:flex;
  justify-content:center;
  gap:8px;
  flex-wrap:wrap;
  margin-bottom:18px;
  position:relative;
  z-index:1;
}
.audit-loader-step{
  font-size:11px;
  font-weight:800;
  color:#175CD3;
  background:#D1E9FF;
  border:1px solid #B2DDFF;
  border-radius:999px;
  padding:6px 9px;
}
.audit-loader-bar{
  width:100%;
  height:8px;
  border-radius:999px;
  background:#EEF2F6;
  overflow:hidden;
  position:relative;
  z-index:1;
}
.audit-loader-bar-fill{
  width:42%;
  height:100%;
  border-radius:999px;
  background:linear-gradient(90deg,#0E7490,#2E90FA,#12B76A);
  animation:auditLoaderBar 1.35s ease-in-out infinite;
}
@keyframes auditLoaderSpin{to{transform:rotate(360deg)}}
@keyframes auditLoaderSweep{0%{left:-35%}55%,100%{left:105%}}
@keyframes auditLoaderBar{
  0%{transform:translateX(-115%);}
  50%{transform:translateX(75%);}
  100%{transform:translateX(235%);}
}

@media(max-width:900px){
  .nch-header{flex-direction:column;align-items:flex-start}.nch-header-right{text-align:left}.case-top{flex-direction:column}.case-badges{text-align:left;min-width:0}.empty-grid{grid-template-columns:1fr}
}
</style>
""", unsafe_allow_html=True)


def _ui_kpi(label: str, value: str, sub: str = "", tone: str = ""):
    tone_cls = f" kpi-{tone}" if tone else ""
    st.markdown(
        f'<div class="kpi-card{tone_cls}"><div class="kpi-label">{h(label)}</div>'
        f'<div class="kpi-value">{h(value)}</div>'
        f'<div class="kpi-sub">{h(sub)}</div></div>',
        unsafe_allow_html=True,
    )


def _ui_groups(auds: list) -> dict:
    financieros = [a for a in auds if _ui_audit_is_financiero(a)]
    catalogo = [a for a in auds if _ui_audit_is_catalogo(a) and a.get("clase") in ("err", "warn")]
    operativos = [a for a in auds if _ui_audit_is_operativo(a)]
    ok = [a for a in auds if a.get("clase") == "ok"]
    informativos = [a for a in auds if a.get("clase") == "gray" and not _ui_audit_is_catalogo(a)]
    return {"financieros": financieros, "operativos": operativos, "catalogo": catalogo, "ok": ok, "informativos": informativos}


def _ui_count(auds: list) -> dict:
    g = _ui_groups(auds)
    return {k: len(v) for k, v in g.items()}


def _ui_riesgo(auds: list):
    c = _ui_count(auds)
    if c["financieros"] > 0:
        return "Alto", "red", "Puede impactar cuenta o cobro"
    if c["operativos"] > 0:
        return "Medio", "yellow", "Requiere confirmación operativa"
    if c["catalogo"] > 0:
        return "Catálogo", "blue", "Revisar códigos con sistemas/Jordan"
    if c["ok"] > 0:
        return "Bajo", "green", "Sin hallazgos relevantes"
    return "Sin referencias", "gray", "Sin evidencia suficiente"


def _ui_money(auds: list) -> float:
    return sum(a.get("monto_diff") or 0 for a in auds if a.get("clase") in ("err", "warn") and a.get("monto_diff"))


def _ui_pill(txt: str, cls: str) -> str:
    return f'<span class="ux-pill ux-pill-{cls}">{h(txt)}</span>'


def _ui_format_num(v, unidad=""):
    if v is None:
        return "—"
    try:
        txt = f"{v:.2f}" if isinstance(v, float) else str(v)
    except Exception:
        txt = str(v)
    return f"{txt} {unidad}".strip()


def _ui_audit_card_class(audit: dict) -> str:
    if _ui_audit_is_catalogo(audit):
        return "blue"
    if audit.get("clase") == "err":
        return "red"
    if audit.get("clase") == "warn":
        return "yellow"
    if audit.get("clase") == "ok":
        return "green"
    return "gray"


def _ui_trace_catalogo_rows() -> list:
    rows = []
    for regla in CATALOGO_ALERTAS_DEF:
        codigos = regla.get("codigos", set()) or set()
        excluidos = regla.get("excluir_codigos", set()) or set()
        rows.append({
            "Concepto": regla.get("label", regla.get("key", "")),
            "Área": regla.get("area") or "Todas",
            "Códigos válidos": ", ".join(sorted(str(c) for c in codigos)) or "—",
            "Códigos excluidos": ", ".join(sorted(str(c) for c in excluidos)) or "—",
            "Patrones de alerta": ", ".join(regla.get("patrones_desc", [])) or "—",
        })
    return rows


def _ui_audit_trace_row(a: dict) -> dict:
    key = str(a.get("key", ""))
    codigos = "—"
    patrones = "—"
    area = "Según regla"

    # Alertas de catálogo: key viene como catalogo_<concepto>_<codigo>
    for regla in CATALOGO_ALERTAS_DEF:
        rkey = regla.get("key", "")
        if key == rkey or key.startswith(f"catalogo_{rkey}_"):
            codigos = ", ".join(sorted(str(c) for c in (regla.get("codigos", set()) or set()))) or "—"
            patrones = ", ".join(regla.get("patrones_desc", [])) or "—"
            area = regla.get("area") or "Todas"
            break

    # Binarios de servicios de cirugía.
    if codigos == "—":
        for bkey, _label, patron, codigos_def, area_def in SERVICIOS_BINARIOS_DEF:
            if key == f"bin_{bkey}" or key == bkey:
                codigos = ", ".join(sorted(str(c) for c in codigos_def)) or "—"
                patrones = patron
                area = area_def or "Todas"
                break

    return {
        "Auditoría": a.get("label", ""),
        "Categoría": a.get("categoria", ""),
        "Tipo": a.get("tipo", ""),
        "Clave interna": key,
        "Área": area,
        "Códigos usados": codigos,
        "Patrón documental / alerta": patrones,
        "Resultado": a.get("status", ""),
    }


def mostrar_configuracion():
    st.markdown("### Configuración de auditoría")
    st.markdown(
        '<div class="config-note">La configuración vive oculta para que la pantalla principal se mantenga ejecutiva. '
        'Cambiar la tolerancia recalcula las validaciones al volver a correr la app.</div>',
        unsafe_allow_html=True,
    )
    nueva_tol = st.slider(
        "Tolerancia (hrs / ml / días)",
        0.0, 1.0, float(st.session_state.get("tolerancia_ui", 0.01)), 0.01,
        help="Diferencia mínima para marcar una discrepancia.",
        key="cfg_tolerancia_slider",
    )
    col_a, col_b = st.columns([1, 3])
    with col_a:
        if st.button("Aplicar", type="primary", use_container_width=True):
            st.session_state["tolerancia_ui"] = float(nueva_tol)
            st.rerun()
    with col_b:
        st.caption(f"Tolerancia actual en uso: {float(st.session_state.get('tolerancia_ui', 0.01)):.2f}")

    st.markdown("#### Documentos reconocidos")
    st.markdown("- Estado de cuenta, cualquier corte\n- Servicios de cirugía\n- Nota post-quirúrgica")
    st.markdown("#### Categorías auditadas")
    st.markdown(
        "- Validación de tiempos y minuto 21\n"
        "- Consistencia de servicios contra estado de cuenta\n"
        "- Oxígeno, sala quirúrgica, recuperación y estancia\n"
        "- Equipos, accesorios, códigos monitoreados y alertas de catálogo\n"
        "- RPBI, habitación, bomba, dietas y validaciones negativas"
    )


def mostrar_reglas_codigos():
    st.markdown("### Códigos monitoreados")
    st.markdown(
        '<div class="config-note">Esta vista es informativa. La herramienta valida cargos por código. '
        'La descripción solo genera alertas para detectar posibles códigos nuevos.</div>',
        unsafe_allow_html=True,
    )
    df_cat = pd.DataFrame(_ui_trace_catalogo_rows())
    st.dataframe(df_cat, use_container_width=True, hide_index=True)

    st.markdown("### Servicios binarios documentados en hoja de servicios")
    rows = []
    for key, label, patron, codigos, area in SERVICIOS_BINARIOS_DEF:
        rows.append({
            "Servicio": label,
            "Clave": key,
            "Área de cobro": area,
            "Códigos esperados": ", ".join(sorted(str(c) for c in codigos)),
            "Patrón en hoja": patron,
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_auditoria(audit: dict):
    """Render visual. Solo presentación; no modifica reglas ni cálculos."""
    tipo = audit.get("tipo", "")
    label = audit.get("label", "Auditoría")
    status = audit.get("status", "")
    unidad = audit.get("unidad", "")
    card_cls = _ui_audit_card_class(audit)

    if _ui_audit_is_catalogo(audit):
        badge = _ui_pill("Catálogo / sistemas", "blue")
    elif audit.get("clase") == "err":
        badge = _ui_pill("Crítico", "red")
    elif audit.get("clase") == "warn":
        badge = _ui_pill("Revisar", "yellow")
    elif audit.get("clase") == "ok":
        badge = _ui_pill("OK", "green")
    else:
        badge = _ui_pill("Informativo", "gray")

    if tipo == "numerico":
        detalle = (
            f"Cobrado: <b>{h(_ui_format_num(audit.get('cobrado'), unidad))}</b> · "
            f"Esperado: <b>{h(_ui_format_num(audit.get('esperado'), unidad))}</b>"
        )
        monto = audit.get("monto_diff")
        if monto is not None and monto >= 1:
            diff = audit.get("diff", 0) or 0
            etiqueta = "sobrecobro" if diff > 0 else "faltante"
            detalle += f" · <b>≈ ${monto:,.0f} {h(etiqueta)}</b>"
    elif tipo == "binario":
        detalle = (
            f"Servicios de cirugía: <b>{'marcado' if audit.get('marcado') else 'no marcado'}</b> · "
            f"Estado de cuenta: <b>{'cobrado' if audit.get('cobrado_bool') else 'no cobrado'}</b>"
        )
    elif tipo == "negativo":
        detalle = f"Cargos encontrados en estado de cuenta: <b>{int(audit.get('cobrado') or 0)}</b>"
    else:
        detalle = h(status)

    nota = audit.get("nota_auditoria")
    nota_html = f'<div class="audit-card-note">{h(nota)}</div>' if nota else ""

    st.markdown(
        f'<div class="audit-card audit-card-{card_cls}">'
        f'<div class="audit-card-head">'
        f'<div><div class="audit-card-title">{h(label)}</div>'
        f'<div class="audit-card-result"><b>Resultado:</b> {h(status)}</div></div>'
        f'<div>{badge}</div>'
        f'</div>'
        f'<div class="audit-card-result">{detalle}</div>'
        f'{nota_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_evidencia_audit(audit: dict):
    items_cob = audit.get("items_cobrados", [])
    items_esp = audit.get("items_esperados", [])
    if not items_cob and not items_esp:
        st.caption("Sin evidencia tabular asociada a esta validación.")
        return
    if items_esp:
        st.markdown("**Esperado / documentado**")
        render_tabla_items(items_esp, COLS_ESPERADO)
    if items_cob:
        st.markdown("**Cobrado en estado de cuenta**")
        render_tabla_items(items_cob, COLS_COBRO)


def render_grupo_auditorias(titulo: str, descripcion: str, auds: list, color: str, empty_msg: str = "Sin hallazgos."):
    total = len(auds)
    st.markdown(
        f'<div class="cat-title section-title-{h(color)}">{h(titulo)} '
        f'<span style="font-weight:500;text-transform:none;letter-spacing:0">· {total}</span></div>',
        unsafe_allow_html=True,
    )
    if descripcion:
        st.caption(descripcion)
    if not auds:
        st.markdown(f'<div class="finding-box finding-gray">{h(empty_msg)}</div>', unsafe_allow_html=True)
        return
    for audit in auds:
        render_auditoria(audit)




st.markdown("""
<style>
.v6-trust-box{border:1px solid #EAECF0;border-radius:18px;background:#FFFFFF;padding:16px 18px;margin:12px 0 18px;box-shadow:0 8px 26px rgba(16,24,40,.05)}
.v6-trust-top{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}
.v6-trust-eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:#667085;font-weight:800;margin-bottom:3px}
.v6-trust-title{font-size:20px;line-height:1.15;font-weight:900;color:#101828}
.v6-trust-sub{font-size:13px;color:#667085;margin-top:5px;line-height:1.45}
.v6-trust-score{font-size:34px;font-weight:900;line-height:1;color:#101828;white-space:nowrap}
.v6-trust-bar{height:10px;background:#F2F4F7;border-radius:999px;overflow:hidden;margin-top:14px}
.v6-trust-fill{height:100%;border-radius:999px}.v6-trust-fill-green{background:#12B76A}.v6-trust-fill-yellow{background:#F79009}.v6-trust-fill-red{background:#F04438}.v6-trust-fill-gray{background:#98A2B3}
.v6-trust-green{border-color:#ABEFC6}.v6-trust-yellow{border-color:#FEDF89}.v6-trust-red{border-color:#FECDCA}.v6-trust-gray{border-color:#D0D5DD}
.v6-mini-note{font-size:12px;color:#667085;line-height:1.45;margin-top:4px}
</style>
""", unsafe_allow_html=True)

# =========================================================
# V6 — CONFIABILIDAD DEL ANÁLISIS
# =========================================================
def _v6_doc_type_counts(data: dict) -> dict:
    counts = defaultdict(int)
    for af in data.get("archivos", []):
        tipo = af.get("tipo_documento") or "otro"
        if str(tipo).startswith("estado_cuenta"):
            counts["estado_cuenta"] += 1
        elif tipo == "servicios_cirugia":
            counts["servicios_cirugia"] += 1
        elif tipo == "nota_postquirurgica":
            counts["nota_postquirurgica"] += 1
        else:
            counts["otro"] += 1
    return dict(counts)


def _v6_confianza_tone(score: int) -> str:
    if score >= 90:
        return "green"
    if score >= 75:
        return "yellow"
    if score >= 60:
        return "yellow"
    return "red"


def _v6_confianza_label(score: int) -> str:
    if score >= 90:
        return "Alta"
    if score >= 75:
        return "Media"
    if score >= 60:
        return "Baja"
    return "Crítica"


def _v6_agregar_check(checks: list, componente: str, estado: str, detalle: str, impacto: int = 0, severidad: str = "ok"):
    checks.append({"Componente": componente, "Estado": estado, "Detalle": detalle, "Impacto": impacto, "Severidad": severidad})


def _v6_construir_diagnostico_cuenta(cuenta: str, data: dict, auds: list) -> dict:
    """Capa de confianza. No modifica reglas ni resultados; solo mide evidencia y cautela."""
    checks = []
    penalizacion = 0
    docs = _v6_doc_type_counts(data)
    items = data.get("todos_los_items", []) or []
    sc = data.get("servicios_cirugia")
    grupos = _ui_groups(auds)

    if docs.get("estado_cuenta", 0) > 0:
        _v6_agregar_check(checks, "Estado de cuenta", "Detectado", f"{docs.get('estado_cuenta', 0)} documento(s) de cuenta procesado(s).", 0, "ok")
    else:
        penalizacion += 35
        _v6_agregar_check(checks, "Estado de cuenta", "Faltante", "Sin estado de cuenta no se pueden validar cargos cobrados.", -35, "err")

    if docs.get("servicios_cirugia", 0) > 0:
        _v6_agregar_check(checks, "Hoja de servicios de cirugía", "Detectada", f"{docs.get('servicios_cirugia', 0)} hoja(s) procesada(s).", 0, "ok")
    else:
        penalizacion += 20
        _v6_agregar_check(checks, "Hoja de servicios de cirugía", "Faltante", "Las reglas basadas en servicios marcados pueden quedar no evaluables.", -20, "warn")

    if docs.get("nota_postquirurgica", 0) > 0:
        _v6_agregar_check(checks, "Nota post-quirúrgica", "Detectada", f"{docs.get('nota_postquirurgica', 0)} nota(s) procesada(s).", 0, "ok")
    else:
        penalizacion += 8
        _v6_agregar_check(checks, "Nota post-quirúrgica", "No detectada", "No bloquea toda la auditoría, pero limita validaciones clínicas/documentales.", -8, "warn")

    if docs.get("otro", 0) > 0:
        pen = min(12, docs.get("otro", 0) * 4)
        penalizacion += pen
        _v6_agregar_check(checks, "Documentos no reconocidos", "Revisar", f"{docs.get('otro', 0)} archivo(s) no clasificado(s) automáticamente.", -pen, "warn")

    if len(items) >= 15:
        _v6_agregar_check(checks, "Extracción de cargos", "Correcta", f"{len(items)} ítem(s) extraídos del estado de cuenta.", 0, "ok")
    elif len(items) > 0:
        penalizacion += 10
        _v6_agregar_check(checks, "Extracción de cargos", "Limitada", f"Solo {len(items)} ítem(s) extraídos. Revisar si el PDF tiene formato parcial o corte incompleto.", -10, "warn")
    else:
        penalizacion += 25
        _v6_agregar_check(checks, "Extracción de cargos", "Sin cargos extraídos", "No se detectaron ítems cobrados. La auditoría financiera no es confiable.", -25, "err")

    if data.get("paciente") and data.get("paciente") != "No identificado":
        _v6_agregar_check(checks, "Paciente", "Identificado", str(data.get("paciente")), 0, "ok")
    else:
        penalizacion += 5
        _v6_agregar_check(checks, "Paciente", "No identificado", "El nombre del paciente no fue extraído con confianza.", -5, "warn")

    if data.get("seguro") and data.get("seguro") != "desconocido":
        _v6_agregar_check(checks, "Pagador / seguro", "Identificado", str(data.get("seguro")), 0, "ok")
    else:
        penalizacion += 6
        _v6_agregar_check(checks, "Pagador / seguro", "No identificado", "Algunas reglas dependen del pagador/aseguradora.", -6, "warn")

    if cuenta == "SIN_CUENTA":
        penalizacion += 20
        _v6_agregar_check(checks, "Cuenta NC", "No detectada", "El archivo no permitió identificar NCxxxxx con claridad.", -20, "err")
    else:
        _v6_agregar_check(checks, "Cuenta NC", "Detectada", cuenta, 0, "ok")

    if sc:
        campos_sc = [sc.get("hora_total_qx"), sc.get("ingreso_sala"), sc.get("egreso_sala"), sc.get("sala_hrs_normal"), sc.get("sala_hrs_adicional"), sc.get("oxigeno_qx")]
        completos = sum(1 for v in campos_sc if v not in (None, "", 0))
        if completos >= 3:
            _v6_agregar_check(checks, "Datos quirúrgicos", "Suficientes", f"{completos}/6 campos clave detectados en hoja de servicios.", 0, "ok")
        else:
            penalizacion += 8
            _v6_agregar_check(checks, "Datos quirúrgicos", "Parciales", f"Solo {completos}/6 campos clave detectados. Revisar hoja de servicios.", -8, "warn")

    if data.get("num_cirugias", 0) > 1:
        pen = min(10, 4 * data.get("num_cirugias", 0))
        penalizacion += pen
        _v6_agregar_check(checks, "Múltiples cirugías", "Cautela", f"{data.get('num_cirugias')} eventos quirúrgicos detectados. Los totales pueden requerir revisión individual.", -pen, "warn")

    if grupos["catalogo"]:
        pen = min(18, len(grupos["catalogo"]) * 6)
        penalizacion += pen
        _v6_agregar_check(checks, "Alertas de catálogo", "Revisar", f"{len(grupos['catalogo'])} posible(s) código(s) no catalogado(s).", -pen, "warn")
    else:
        _v6_agregar_check(checks, "Alertas de catálogo", "Sin alertas", "No se detectaron posibles códigos nuevos por descripción.", 0, "ok")

    if grupos["financieros"]:
        _v6_agregar_check(checks, "Resultado financiero", "Con hallazgos", f"{len(grupos['financieros'])} diferencia(s) financiera(s) detectada(s).", 0, "warn")
    else:
        _v6_agregar_check(checks, "Resultado financiero", "Sin diferencias críticas", "No se detectaron diferencias financieras relevantes con las reglas actuales.", 0, "ok")

    reglas_ejecutadas = len(auds)
    reglas_ok = len(grupos["ok"])
    reglas_grises = len(grupos["informativos"])
    no_evaluable = [a for a in auds if a.get("clase") == "gray" and "sin" in normalizar(a.get("status", ""))]
    if no_evaluable:
        pen = min(12, len(no_evaluable) * 3)
        penalizacion += pen
        _v6_agregar_check(checks, "Reglas no evaluables", "Cautela", f"{len(no_evaluable)} regla(s) quedaron sin evidencia suficiente.", -pen, "warn")

    score = int(max(0, min(100, round(100 - penalizacion))))
    tone = _v6_confianza_tone(score)
    label = _v6_confianza_label(score)

    areas = defaultdict(int)
    for i in items:
        areas[i.get("area", "sin_area")] += 1

    limitaciones = [c for c in checks if c["Severidad"] in ("warn", "err") and c["Impacto"] < 0]
    return {"score": score, "label": label, "tone": tone, "checks": checks, "limitaciones": limitaciones, "docs": docs, "items_count": len(items), "areas": dict(areas), "reglas_ejecutadas": reglas_ejecutadas, "reglas_ok": reglas_ok, "reglas_informativas": reglas_grises, "reglas_no_evaluables": len(no_evaluable), "resumen": f"Confiabilidad {label.lower()} ({score}%). Reglas ejecutadas: {reglas_ejecutadas}; ítems extraídos: {len(items)}."}


def _v6_render_confianza_box(diag: dict):
    score = diag.get("score", 0)
    label = diag.get("label", "")
    tone = diag.get("tone", "gray")
    st.markdown(f"""
        <div class="v6-trust-box v6-trust-{tone}">
          <div class="v6-trust-top">
            <div>
              <div class="v6-trust-eyebrow">Control de calidad del análisis</div>
              <div class="v6-trust-title">Confiabilidad {h(label)} · {score}%</div>
              <div class="v6-trust-sub">{h(diag.get('resumen',''))}</div>
            </div>
            <div class="v6-trust-score">{score}%</div>
          </div>
          <div class="v6-trust-bar"><div class="v6-trust-fill v6-trust-fill-{tone}" style="width:{score}%;"></div></div>
        </div>
        """, unsafe_allow_html=True)


def _v6_render_diagnostico(data: dict, auds: list, cuenta: str):
    diag = _v6_construir_diagnostico_cuenta(cuenta, data, auds)
    _v6_render_confianza_box(diag)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _ui_kpi("Ítems extraídos", str(diag["items_count"]), "Cargos leídos de cuenta", "green" if diag["items_count"] else "red")
    with c2:
        _ui_kpi("Reglas ejecutadas", str(diag["reglas_ejecutadas"]), f"OK: {diag['reglas_ok']}", "green")
    with c3:
        _ui_kpi("No evaluables", str(diag["reglas_no_evaluables"]), "Por falta de evidencia", "yellow" if diag["reglas_no_evaluables"] else "green")
    with c4:
        _ui_kpi("Limitaciones", str(len(diag["limitaciones"])), "Advertencias de confianza", "yellow" if diag["limitaciones"] else "green")
    st.markdown("#### Diagnóstico de documentos y lectura")
    df_checks = pd.DataFrame(diag["checks"])
    if not df_checks.empty:
        st.dataframe(df_checks, use_container_width=True, hide_index=True)
    st.markdown("#### Distribución de cargos extraídos por área")
    areas = diag.get("areas", {})
    if areas:
        df_areas = pd.DataFrame([{"Área": k, "Ítems": v} for k, v in sorted(areas.items())])
        st.dataframe(df_areas, use_container_width=True, hide_index=True)
    else:
        st.info("No hay cargos extraídos por área.")
    if diag["limitaciones"]:
        st.warning("La cuenta tiene limitaciones de análisis. El resultado debe revisarse con la evidencia antes de cerrarse.")
    else:
        st.success("No se detectaron limitaciones relevantes de lectura o evidencia.")


def render_header():
    st.markdown(
        f"""
        <div class="nch-header">
          <div class="nch-brand">
            <div class="nch-logo-wrap"><img class="nch-logo" src="{LOGO_NCH_URL}" /></div>
            <div>
              <div class="nch-eyebrow">NewCity Hospital · Auditoría</div>
              <div class="nch-title">Auditor Hospitalario</div>
              <div class="nch-subtitle">Preauditoría automática de cuentas hospitalarias. El auditor ve primero prioridades, después evidencia y trazabilidad solo cuando la necesita.</div>
            </div>
          </div>
          <div class="nch-header-right">
            <div class="nch-status"><span class="nch-status-dot"></span>Motor activo</div>
            <div class="nch-version">Frontend v6 · confiabilidad · detalle en modal · reglas intactas</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _toggle_session_bool(key: str):
    st.session_state[key] = not bool(st.session_state.get(key, False))


def _modal_decorator(title: str):
    """Usa st.dialog cuando está disponible. Si el servidor tiene Streamlit viejo, no rompe la app."""
    dialog_fn = getattr(st, "dialog", None) or getattr(st, "experimental_dialog", None)
    if dialog_fn is None:
        def passthrough(fn):
            return fn
        return passthrough
    try:
        return dialog_fn(title, width="large")
    except TypeError:
        return dialog_fn(title)


_MODAL_DISPONIBLE = bool(getattr(st, "dialog", None) or getattr(st, "experimental_dialog", None))


def render_detalle_cuenta_body(cuenta_key: str, cuentas: dict, todas_auditorias: dict, hash_archivos: str, dentro_modal: bool = False):
    """Contenido del detalle. Se renderiza dentro del modal para no perder al auditor."""
    if cuenta_key not in cuentas:
        st.warning("La cuenta seleccionada ya no está disponible en este lote.")
        return

    data = cuentas[cuenta_key]
    auds = todas_auditorias[cuenta_key]
    grupos = _ui_groups(auds)
    diag = _v6_construir_diagnostico_cuenta(cuenta_key, data, auds)
    riesgo_txt, riesgo_cls, riesgo_desc = _ui_riesgo(auds)
    monto_total = _ui_money(auds)
    seguro_label = data.get("seguro", "") or "No identificado"

    if dentro_modal:
        st.markdown(
            '<div class="modal-helper">Detalle abierto en modal. La pantalla principal permanece limpia; cierra esta ventana para volver a la lista de cuentas.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.warning("Tu versión de Streamlit no soporta modales. Actualiza Streamlit para ver el detalle como ventana emergente.")

    dtop1, dtop2 = st.columns([5, 1])
    with dtop1:
        st.markdown(
            f'<div class="case-card">'
            f'<div class="case-top"><div class="case-left"><span class="case-dot case-dot-{riesgo_cls}"></span>'
            f'<div><div class="case-title">{h(cuenta_key)} · {h(data.get("paciente") or "No identificado")}</div>'
            f'<div class="case-sub">Pagador: {h(seguro_label)} · {len(data.get("archivos", []))} archivo(s)</div>'
            f'<div class="case-meta">Ingreso {h(data.get("fecha_ingreso", "?"))} → Egreso {h(data.get("fecha_egreso", "?"))} · {h(data.get("dias_estancia", "?"))} día(s)</div></div></div>'
            f'<div class="case-badges">{_ui_pill(riesgo_txt, riesgo_cls)}<br><span class="muted-small">{h(riesgo_desc)}</span></div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with dtop2:
        st.write("")
        st.write("")
        if st.button("Cerrar", key=f"cerrar_modal_v5_{cuenta_key}", use_container_width=True):
            st.session_state["cuenta_modal_v5"] = None
            st.rerun()

    _v6_render_confianza_box(diag)

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        _ui_kpi("Financieros", str(len(grupos["financieros"])), f"≈ ${monto_total:,.0f}", "red" if grupos["financieros"] else "green")
    with m2:
        _ui_kpi("Operativos", str(len(grupos["operativos"])), "Confirmación humana", "yellow" if grupos["operativos"] else "green")
    with m3:
        _ui_kpi("Catálogo", str(len(grupos["catalogo"])), "Jordan / sistemas", "blue" if grupos["catalogo"] else "green")
    with m4:
        _ui_kpi("OK", str(len(grupos["ok"])), "Ocultas por defecto", "green")

    tab_resumen, tab_hallazgos, tab_confiabilidad, tab_evidencia, tab_traza, tab_docs = st.tabs([
        "Resumen", "Hallazgos", "Confiabilidad", "Evidencia", "Cómo auditó", "Documentos"
    ])

    with tab_resumen:
        st.markdown("### Resumen de la cuenta")
        resumen_rows = [
            {"Campo": "Cuenta", "Valor": cuenta_key},
            {"Campo": "Paciente", "Valor": data.get("paciente") or "No identificado"},
            {"Campo": "Pagador", "Valor": seguro_label},
            {"Campo": "Riesgo", "Valor": f"{riesgo_txt} — {riesgo_desc}"},
            {"Campo": "Archivos procesados", "Valor": str(len(data.get("archivos", [])))},
            {"Campo": "Monto estimado", "Valor": f"≈ ${monto_total:,.0f}"},
        ]
        st.dataframe(pd.DataFrame(resumen_rows), use_container_width=True, hide_index=True)
        if grupos["financieros"] or grupos["operativos"] or grupos["catalogo"]:
            st.warning("Esta cuenta tiene puntos que requieren revisión antes de cerrarse.")
        else:
            st.success("No se detectaron hallazgos relevantes para revisión.")

    with tab_hallazgos:
        render_grupo_auditorias("🔴 Hallazgos financieros", "Diferencias que pueden impactar el cargo o cobro.", grupos["financieros"], "red", "No hay diferencias financieras relevantes.")
        render_grupo_auditorias("🟡 Validaciones operativas", "Requieren confirmación con enfermería, almacén, quirófano o área médica.", grupos["operativos"], "yellow", "No hay validaciones operativas pendientes.")
        render_grupo_auditorias("🔵 Alertas de catálogo / sistemas", "Códigos potencialmente nuevos. No cierran validaciones hasta actualizar catálogo.", grupos["catalogo"], "blue", "No hay alertas de catálogo.")
        if grupos["informativos"]:
            with st.expander(f"ℹ️ Informativos ({len(grupos['informativos'])})", expanded=False):
                for a in grupos["informativos"]:
                    render_auditoria(a)
        if grupos["ok"]:
            with st.expander(f"🟢 Validaciones correctas ({len(grupos['ok'])})", expanded=False):
                for a in grupos["ok"]:
                    render_auditoria(a)

    with tab_confiabilidad:
        st.markdown("### Confiabilidad y limitaciones del análisis")
        st.caption("Esta capa no cambia ninguna regla. Solo indica qué tan defendible es el análisis según documentos, extracción, evidencia y alertas.")
        _v6_render_diagnostico(data, auds, cuenta_key)

    with tab_evidencia:
        st.markdown("### Evidencia trazada por validación")
        st.caption("Solo se despliega cuando el auditor necesita revisar códigos, cantidades o documentos asociados a la regla.")
        auds_con_evidencia = [a for a in auds if a.get("items_cobrados") or a.get("items_esperados")]
        if not auds_con_evidencia:
            st.info("No hay evidencia tabular asociada a las validaciones de esta cuenta.")
        for a in auds_con_evidencia:
            with st.expander(f"{a.get('label', 'Auditoría')} — {a.get('status', '')}", expanded=False):
                render_evidencia_audit(a)

    with tab_traza:
        st.markdown("### Cómo auditó esta cuenta")
        st.caption("Trazabilidad informativa: muestra claves internas, códigos buscados, área y resultado. No modifica ninguna regla.")
        df_trace = pd.DataFrame([_ui_audit_trace_row(a) for a in auds])
        st.dataframe(df_trace, use_container_width=True, hide_index=True)

    with tab_docs:
        st.markdown("### Documentos procesados")
        rows = []
        for af in data.get("archivos", []):
            tipo_label = {
                "servicios_cirugia": "Servicios de cirugía",
                "nota_postquirurgica": "Nota post-quirúrgica",
                "otro": "Tipo no reconocido",
            }.get(af.get("tipo_documento"), str(af.get("tipo_documento", "")).replace("estado_cuenta_", "Estado de cuenta — corte "))
            rows.append({"Archivo": af.get("archivo", ""), "Tipo detectado": tipo_label})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    html_reporte = _construir_html_reporte_cuenta(cuenta_key, data, auds, hash_archivos)
    st.download_button(
        "📥 Descargar reporte de esta cuenta (HTML)",
        data=html_reporte.encode("utf-8"),
        file_name=f"auditoria_{cuenta_key}.html",
        mime="text/html",
        key=f"dl_reporte_v5_{cuenta_key}",
        use_container_width=True,
    )


@_modal_decorator("Detalle de auditoría de la cuenta")
def render_detalle_cuenta_modal(cuenta_key: str, cuentas: dict, todas_auditorias: dict, hash_archivos: str):
    render_detalle_cuenta_body(cuenta_key, cuentas, todas_auditorias, hash_archivos, dentro_modal=_MODAL_DISPONIBLE)

# =========================================================
# APP V6 — FRONTEND CONFIABILIDAD + DETALLE EN MODAL
# =========================================================
render_header()

if "show_config_v4" not in st.session_state:
    st.session_state["show_config_v4"] = False
if "show_rules_v4" not in st.session_state:
    st.session_state["show_rules_v4"] = False
if "cuenta_modal_v5" not in st.session_state:
    st.session_state["cuenta_modal_v5"] = None
# Se conserva la llave vieja para no romper sesiones previas, pero ya no controla el detalle.
if "cuenta_seleccionada_v4" not in st.session_state:
    st.session_state["cuenta_seleccionada_v4"] = None

acol1, acol2, acol3, acol4 = st.columns([3.5, 1, 1, 1])
with acol1:
    st.markdown('<div class="action-help">Carga los PDFs y revisa primero las cuentas con impacto financiero, operativo o de catálogo. Las reglas y configuraciones están ocultas para no saturar al auditor.</div>', unsafe_allow_html=True)
with acol2:
    if st.button("⚙️ Configuración", use_container_width=True):
        _toggle_session_bool("show_config_v4")
with acol3:
    if st.button("📚 Reglas", use_container_width=True):
        _toggle_session_bool("show_rules_v4")
with acol4:
    st.button("📥 Exportar", use_container_width=True, disabled=True, help="La exportación aparece al final después de cargar documentos.")

if st.session_state.get("show_config_v4"):
    with st.expander("⚙️ Configuración de auditoría", expanded=True):
        mostrar_configuracion()

if st.session_state.get("show_rules_v4"):
    with st.expander("📚 Reglas y códigos auditados", expanded=True):
        mostrar_reglas_codigos()

st.markdown(
    '<div class="upload-shell"><div class="upload-title">Carga de documentos</div>'
    '<div class="upload-sub">Sube estado de cuenta, servicios de cirugía y nota post-quirúrgica. Puedes cargar una o varias cuentas al mismo tiempo.</div></div>',
    unsafe_allow_html=True,
)

archivos_subidos = st.file_uploader(
    "Selecciona los documentos PDF",
    type=["pdf"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

if not archivos_subidos:
    st.markdown(
        """
        <div class="empty-state">
          <div class="empty-title">Listo para auditar cuentas hospitalarias</div>
          <div class="empty-sub">La pantalla principal muestra solo lo necesario para tomar decisiones. La configuración, códigos y trazabilidad quedan ocultos en paneles informativos.</div>
          <div class="empty-grid">
            <div class="empty-card"><div class="empty-card-title">1. Prioriza cuentas</div><div class="empty-card-sub">Identifica rápidamente qué cuenta requiere revisión y por qué.</div></div>
            <div class="empty-card"><div class="empty-card-title">2. Separa hallazgos</div><div class="empty-card-sub">Distingue diferencias financieras, validaciones operativas y alertas de catálogo.</div></div>
            <div class="empty-card"><div class="empty-card-title">3. Revisa evidencia</div><div class="empty-card-sub">Abre el detalle solo cuando el auditor necesita validar códigos, cantidades o documentos.</div></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

archivos_bytes = [(f.name, f.read()) for f in archivos_subidos]

_hash_actual = _hash_archivos(archivos_bytes)
_ts_auditoria = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

# Loader central mientras se leen PDFs y se construyen auditorías.
# No modifica la lógica del motor; solo mejora la experiencia visual durante el procesamiento.
_loader_placeholder = st.empty()
_loader_placeholder.markdown(_ui_loader_markup(len(archivos_bytes)), unsafe_allow_html=True)
try:
    with st.spinner("Analizando documentos…"):
        cuentas = consolidar_por_cuenta(archivos_bytes)
        todas_auditorias = {cta: construir_auditorias(data, tolerancia_ui) for cta, data in cuentas.items()}
        diagnosticos_cuenta = {cta: _v6_construir_diagnostico_cuenta(cta, data, todas_auditorias[cta]) for cta, data in cuentas.items()}

        if st.session_state.get("_ultimo_log_enviado") != _hash_actual:
            _enviar_log_email(cuentas, todas_auditorias, archivos_bytes)
            st.session_state["_ultimo_log_enviado"] = _hash_actual
finally:
    _loader_placeholder.empty()

# =========================================================
# MÉTRICAS GLOBALES
# =========================================================

total_cuentas = len(cuentas)
total_financieros = sum(len(_ui_groups(auds)["financieros"]) for auds in todas_auditorias.values())
total_operativos = sum(len(_ui_groups(auds)["operativos"]) for auds in todas_auditorias.values())
total_catalogo = sum(len(_ui_groups(auds)["catalogo"]) for auds in todas_auditorias.values())
total_ok = sum(len(_ui_groups(auds)["ok"]) for auds in todas_auditorias.values())
cuentas_atencion = sum(1 for auds in todas_auditorias.values() if len(_ui_groups(auds)["financieros"]) or len(_ui_groups(auds)["operativos"]) or len(_ui_groups(auds)["catalogo"]))
monto_global = sum(_ui_money(auds) for auds in todas_auditorias.values())
confianza_global = int(round(sum(d.get("score", 0) for d in diagnosticos_cuenta.values()) / max(1, len(diagnosticos_cuenta)))) if diagnosticos_cuenta else 0
confianza_global_label = _v6_confianza_label(confianza_global)
confianza_global_tone = _v6_confianza_tone(confianza_global)

st.markdown('<div class="executive-title">Resumen ejecutivo del lote</div>', unsafe_allow_html=True)
st.markdown('<div class="executive-sub">Vista rápida para decidir qué cuenta revisar primero.</div>', unsafe_allow_html=True)

k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
with k1:
    _ui_kpi("Cuentas", str(total_cuentas), f"{len(archivos_bytes)} archivo(s)")
with k2:
    _ui_kpi("A revisar", str(cuentas_atencion), "Cuentas con atención", "yellow" if cuentas_atencion else "green")
with k3:
    _ui_kpi("Financieros", str(total_financieros), "Impacto en cuenta", "red" if total_financieros else "green")
with k4:
    _ui_kpi("Operativos", str(total_operativos), "Confirmar con área", "yellow" if total_operativos else "green")
with k5:
    _ui_kpi("Catálogo", str(total_catalogo), "Avisar a Jordan/sistemas", "blue" if total_catalogo else "green")
with k6:
    _ui_kpi("Monto", f"≈ ${monto_global:,.0f}", "Hallazgos estimados", "red" if monto_global else "green")
with k7:
    _ui_kpi("Confianza", f"{confianza_global}%", confianza_global_label, confianza_global_tone)

_v6_render_confianza_box({
    "score": confianza_global,
    "label": confianza_global_label,
    "tone": confianza_global_tone,
    "resumen": f"Promedio de confiabilidad del lote. Cuentas: {total_cuentas}; archivos: {len(archivos_bytes)}; validaciones OK: {total_ok}.",
})

st.markdown(
    f'<div class="audit-meta-line">Auditoría generada: {h(_ts_auditoria)} · Hash de archivos: <code>{h(_hash_actual[:12])}…</code> · Validaciones OK: {total_ok} · Tolerancia: {tolerancia_ui:.2f}</div>',
    unsafe_allow_html=True,
)

st.markdown('<div class="executive-title">Cuentas analizadas</div>', unsafe_allow_html=True)
st.markdown('<div class="executive-sub">Ordenadas por prioridad para que el auditor revise primero lo que puede impactar cuenta, operación o catálogo.</div>', unsafe_allow_html=True)

with st.container():
    st.markdown('<div class="filter-card">', unsafe_allow_html=True)
    fcol1, fcol2, fcol3 = st.columns([2.2, 2, 1])
    with fcol1:
        filtro_busqueda = st.text_input("Buscar cuenta o paciente", "", placeholder="Ej. NC13377 o Blank")
    with fcol2:
        filtro_tipo = st.selectbox("Filtrar por atención", ["Todas", "Financieros", "Operativos", "Catálogo", "Sin hallazgos"], index=0)
    with fcol3:
        solo_pendientes = st.toggle("Solo pendientes", value=False)
    st.markdown('</div>', unsafe_allow_html=True)


def _orden_urgencia(item):
    cta, _ = item
    auds = todas_auditorias[cta]
    g = _ui_groups(auds)
    monto = _ui_money(auds)
    return (-len(g["financieros"]), -len(g["operativos"]), -len(g["catalogo"]), -monto, cta)


def _pasa_filtros(cuenta: str, data: dict) -> bool:
    auds = todas_auditorias[cuenta]
    g = _ui_groups(auds)
    q = normalizar(filtro_busqueda or "")
    if q:
        base = normalizar(f"{cuenta} {data.get('paciente','')} {data.get('seguro','')}")
        if q not in base:
            return False
    if solo_pendientes and not (g["financieros"] or g["operativos"] or g["catalogo"]):
        return False
    if filtro_tipo == "Financieros" and not g["financieros"]:
        return False
    if filtro_tipo == "Operativos" and not g["operativos"]:
        return False
    if filtro_tipo == "Catálogo" and not g["catalogo"]:
        return False
    if filtro_tipo == "Sin hallazgos" and (g["financieros"] or g["operativos"] or g["catalogo"]):
        return False
    return True


cuentas_ordenadas = [item for item in sorted(cuentas.items(), key=_orden_urgencia) if _pasa_filtros(item[0], item[1])]

if not cuentas_ordenadas:
    st.info("No hay cuentas que coincidan con los filtros seleccionados.")

for cuenta, data in cuentas_ordenadas:
    auds = todas_auditorias[cuenta]
    grupos = _ui_groups(auds)
    diag = diagnosticos_cuenta.get(cuenta) or _v6_construir_diagnostico_cuenta(cuenta, data, auds)
    riesgo_txt, riesgo_cls, riesgo_desc = _ui_riesgo(auds)
    monto_total = _ui_money(auds)

    pills = ""
    if grupos["financieros"]:
        pills += _ui_pill(f"{len(grupos['financieros'])} financiero(s)", "red")
    if grupos["operativos"]:
        pills += _ui_pill(f"{len(grupos['operativos'])} operativo(s)", "yellow")
    if grupos["catalogo"]:
        pills += _ui_pill(f"{len(grupos['catalogo'])} catálogo", "blue")
    if not (grupos["financieros"] or grupos["operativos"] or grupos["catalogo"]):
        pills += _ui_pill("Sin hallazgos", "green")
    if monto_total >= 1:
        pills += _ui_pill(f"≈ ${monto_total:,.0f}", "dark")
    pills += _ui_pill(f"Confianza {diag.get('score', 0)}%", diag.get("tone", "gray"))

    seguro_label = data.get("seguro", "") or "No identificado"
    archivos_txt = f"{len(data.get('archivos', []))} archivo(s)"
    modal_abierto = st.session_state.get("cuenta_modal_v5") == cuenta
    card_border = "border-color:#2E90FA;box-shadow:0 12px 38px rgba(46,144,250,.14);" if modal_abierto else ""

    col_card, col_btn = st.columns([6, 1.1])
    with col_card:
        st.markdown(
            f'<div class="case-card" style="{card_border}">'
            f'<div class="case-top"><div class="case-left"><span class="case-dot case-dot-{riesgo_cls}"></span>'
            f'<div><div class="case-title">{h(cuenta)} · {h(data.get("paciente") or "No identificado")}</div>'
            f'<div class="case-sub">Pagador: {h(seguro_label)} · {h(archivos_txt)}</div>'
            f'<div class="case-meta">{h(riesgo_desc)}</div></div></div>'
            f'<div class="case-badges">{_ui_pill(riesgo_txt, riesgo_cls)}<br>{pills}</div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col_btn:
        st.write("")
        st.write("")
        if st.button("Ver detalle", key=f"btn_detalle_v5_{cuenta}", type="primary", use_container_width=True):
            st.session_state["cuenta_modal_v5"] = cuenta
            st.session_state["cuenta_seleccionada_v4"] = None
            st.rerun()

modal_cuenta = st.session_state.get("cuenta_modal_v5")
if modal_cuenta and modal_cuenta in cuentas:
    render_detalle_cuenta_modal(modal_cuenta, cuentas, todas_auditorias, _hash_actual)

st.divider()

# =========================================================
# EXPORTAR
# =========================================================
st.markdown('<div class="executive-title">Exportar</div>', unsafe_allow_html=True)
st.markdown('<div class="executive-sub">Descarga resultados para seguimiento fuera de la aplicación.</div>', unsafe_allow_html=True)

filas_res = []
for cuenta, auds in todas_auditorias.items():
    fila = {
        "Cuenta": cuenta,
        "Paciente": cuentas[cuenta]["paciente"],
        "Seguro": cuentas[cuenta].get("seguro", ""),
        "Fecha_auditoria": _ts_auditoria,
        "Hash_archivos": _hash_actual[:12],
        "Confiabilidad_%": diagnosticos_cuenta.get(cuenta, {}).get("score", ""),
        "Confiabilidad_estado": diagnosticos_cuenta.get(cuenta, {}).get("label", ""),
        "Items_extraidos": diagnosticos_cuenta.get(cuenta, {}).get("items_count", ""),
        "Reglas_no_evaluables": diagnosticos_cuenta.get(cuenta, {}).get("reglas_no_evaluables", ""),
    }
    for a in auds:
        fila[a["label"]] = a["status"]
    filas_res.append(fila)
df_res = pd.DataFrame(filas_res)

todos_items = [{**i, "tipo_auditoria": "cobrado"} for data in cuentas.values() for i in data["todos_los_items"]]
df_items = pd.DataFrame(todos_items) if todos_items else pd.DataFrame()

col1, col2 = st.columns(2)
with col1:
    st.download_button(
        "Resumen de auditoría (CSV)",
        data=df_res.to_csv(index=False).encode("utf-8"),
        file_name="auditoria_resumen.csv",
        mime="text/csv",
        use_container_width=True,
    )
with col2:
    if not df_items.empty:
        st.download_button(
            "Todos los ítems del estado de cuenta (CSV)",
            data=df_items.to_csv(index=False).encode("utf-8"),
            file_name="auditoria_items.csv",
            mime="text/csv",
            use_container_width=True,
        )
    else:
        st.button("Todos los ítems del estado de cuenta (CSV)", disabled=True, use_container_width=True)
