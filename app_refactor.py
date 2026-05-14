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
CODIGO_ARCO_C       = "IBM-0000023"
CODIGO_FUNDA_ARCO_C = "ALM-0000877"

# ── PUNTO 6: RPBI ─────────────────────────────────────────
CODIGO_RPBI = "ENF-0000003"
DIAS_RPBI_ADICIONAL = 7

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
     {"IBM-0000023"}, "quirofano"),
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
    """Extrae el tipo de seguro del estado de cuenta o servicios."""
    # Buscar en múltiples líneas (no compact) para mejor precisión
    for linea in texto.splitlines():
        n = normalizar(linea.strip())
        # Desde servicios de cirugía: "Seguro: PARTICULAR NACIONAL"
        m = re.match(r"seguro:\s*(.+)", n)
        if m:
            seg = m.group(1).strip()
            if "particular" in seg:
                return "particular"
            return seg
    # Desde estado de cuenta: buscar línea después de "Cia. Cliente"
    lineas = texto.splitlines()
    for i, linea in enumerate(lineas):
        if re.search(r"Cia\.?\s*Cliente", linea, re.IGNORECASE):
            # El valor puede estar en la misma línea o en la siguiente
            resto = re.sub(r".*Cia\.?\s*Cliente\s*", "", linea, flags=re.IGNORECASE).strip()
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
        resultado["seguro"] = "particular" if "particular" in seg else seg

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
    # PUNTO 2: Máquina de anestesia (particular vs seguro)
    # ══════════════════════════════════════════════════════
    if sc:
        maq_marcada = sc.get("maquina_anestesia", False)
        es_particular = "particular" in (seguro or "")

        # Fix 6: Buscar cargo de máquina de anestesia en el estado de cuenta
        PALABRAS_MAQUINA = {"maquina de anestesia", "maquina anestesia", "anesthesia machine"}
        maq_items = [i for i in items
                     if any(p in normalizar(i["descripcion"]) for p in PALABRAS_MAQUINA)]
        maq_cobrada = len(maq_items) > 0

        if maq_marcada or maq_cobrada:
            if es_particular and maq_cobrada:
                status = "ERROR — paciente PARTICULAR con cargo de máquina de anestesia"
                clase  = "err"
            elif es_particular and not maq_cobrada:
                status = "ok — documentada en servicios, no cobrada (particular)"
                clase  = "ok"
            elif not es_particular and maq_cobrada:
                status = "ok — paciente con seguro, máquina cobrada"
                clase  = "ok"
            elif not es_particular and maq_marcada and not maq_cobrada:
                status = "documentada pero no cobrada — paciente con seguro, verificar"
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
                    f"Seguro: {seguro or 'no identificado'}. "
                    f"Regla: no se cobra en particulares; en convenios/seguros, "
                    f"si está documentada y no cobrada, verificar."
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
    arco_items   = por_codigo({CODIGO_ARCO_C}, "quirofano")
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
    # CAMBIO 3 — RPBI: regla actualizada con mínimo obligatorio
    # Por indicación del auditor: en TODAS las cuentas (particulares,
    # convenio y seguros), desde el ingreso a habitación debe existir
    # mínimo un cargo de Disposición de RPBI. Pasando 7 días, otro cargo
    # adicional, y así sucesivamente.
    # ══════════════════════════════════════════════════════
    rpbi_items = por_codigo({CODIGO_RPBI})
    rpbi_count = len(rpbi_items)

    # Calcular cantidad esperada según días de estancia
    if dias is not None and dias > 0:
        # 1 cargo al ingreso + 1 adicional por cada 7 días completos posteriores
        rpbi_esperado = 1 + (max(dias - 1, 0) // DIAS_RPBI_ADICIONAL)
    elif dias == 0:
        # Mismo día de ingreso/egreso — al menos 1 cargo
        rpbi_esperado = 1
    else:
        # Sin datos de estancia, se requiere mínimo 1
        rpbi_esperado = 1

    # Determinar status y clase
    if rpbi_count == 0:
        # Caso crítico: ninguna cuenta debería tener cero RPBI
        status = (f"FALTA cargo de RPBI — toda cuenta debe tener mínimo 1 "
                  f"({CODIGO_RPBI})")
        clase  = "err"
    elif rpbi_count < rpbi_esperado:
        # Tiene RPBI pero menos de los esperados por días
        status = (f"insuficiente — {rpbi_count} cargo(s) para "
                  f"{dias if dias is not None else '?'} día(s); "
                  f"se esperan {rpbi_esperado}")
        clase = "err"
    elif rpbi_count == rpbi_esperado:
        status = (f"ok — {rpbi_count} cargo(s) para "
                  f"{dias if dias is not None else '?'} día(s)")
        clase = "ok"
    else:
        # Hay más cargos de los esperados — no es error pero conviene revisar
        status = (f"{rpbi_count} cargo(s) para {dias if dias is not None else '?'} día(s); "
                  f"se esperaban {rpbi_esperado}")
        clase = "warn"

    auditorias.append({
        "categoria": "Estancia",
        "key":       "rpbi",
        "label":     "Disposición de RPBI",
        "tipo":      "numerico",
        "unidad":    "cargo(s)",
        "cobrado":   float(rpbi_count),
        "esperado":  float(rpbi_esperado),
        "status":    status,
        "diff":      None,
        "clase":     clase,
        "items_cobrados":  rpbi_items,
        "items_esperados": [],
        "nota_auditoria": (
            f"Regla: toda cuenta (particular, convenio o seguro) debe tener mínimo "
            f"1 cargo de RPBI al ingreso a habitación; un cargo adicional por cada "
            f"{DIAS_RPBI_ADICIONAL} días completos posteriores. "
            f"Estancia: {dias if dias is not None else '?'} día(s)."
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

def render_auditoria(audit: dict):
    tipo  = audit["tipo"]
    clase = audit["clase"]
    label = audit["label"]
    status_txt = audit["status"].upper() if audit["status"] == "ok" else audit["status"]

    st.markdown(
        f'<div class="audit-row">'
        f'<div class="audit-header">'
        f'<span class="audit-label">{label}</span>'
        f'{badge_html(status_txt, clase)}'
        f'</div>',
        unsafe_allow_html=True,
    )

    if tipo == "numerico":
        cobrado  = audit["cobrado"]
        esperado = audit["esperado"]
        unidad   = audit["unidad"]
        if esperado is not None:
            st.markdown(barra_html(cobrado, esperado, clase), unsafe_allow_html=True)
            sub = f"Cobrado {cobrado:.2f} {unidad}  ·  Esperado {esperado:.2f} {unidad}"
        else:
            sub = f"Cobrado {cobrado:.2f} {unidad}"
        # Monto económico de la diferencia (cuando aplica)
        monto = audit.get("monto_diff")
        if monto is not None and monto >= 1:
            diff = audit.get("diff", 0)
            etiqueta = "sobrecobro" if diff > 0 else "faltante"
            sub += (f'  ·  <b style="color:{("#791F1F" if diff < 0 else "#633806")}">'
                    f'≈ ${monto:,.0f} {etiqueta}</b>')
        if audit.get("nota_auditoria"):
            sub += f"<br>{audit['nota_auditoria']}"
        st.markdown(f'<div class="audit-sub">{sub}</div>', unsafe_allow_html=True)

    elif tipo == "binario":
        marcado = audit["marcado"]
        cobrado_b = audit["cobrado_bool"]
        sub = (f"Servicios de cirugía: {'✓ marcado' if marcado else '— no marcado'}  ·  "
               f"Estado de cuenta: {'✓ cobrado' if cobrado_b else '— no cobrado'}")
        st.markdown(f'<div class="audit-sub">{sub}</div>', unsafe_allow_html=True)

    elif tipo == "negativo":
        n = int(audit["cobrado"])
        sub = f"{n} cargo(s) encontrado(s) en el estado de cuenta."
        if audit.get("nota_auditoria"):
            sub = audit["nota_auditoria"] + "  " + sub
        st.markdown(f'<div class="audit-sub">{sub}</div>', unsafe_allow_html=True)

    elif tipo == "informativo":
        sub = audit["status"]
        if audit.get("nota_auditoria"):
            sub += f"<br>{audit['nota_auditoria']}"
        st.markdown(f'<div class="audit-sub">{sub}</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # Evidencia expandible
    items_cob = audit.get("items_cobrados", [])
    items_esp = audit.get("items_esperados", [])
    if items_cob or items_esp:
        with st.expander("Ver evidencia"):
            if items_esp:
                st.markdown("**Esperado (servicios de cirugía)**")
                render_tabla_items(items_esp, COLS_ESPERADO)
            if items_cob:
                st.markdown("**Cobrado (estado de cuenta)**")
                render_tabla_items(items_cob, COLS_COBRO)

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
# SIDEBAR
# =========================================================
with st.sidebar:
    st.markdown("### ⚙️ Configuración")
    tolerancia_ui = st.slider("Tolerancia (hrs / ml / días)",
                              0.0, 1.0, 0.01, 0.01,
                              help="Diferencia mínima para marcar una discrepancia.")
    st.markdown("---")
    st.markdown(
        "**Documentos reconocidos:**\n"
        "- Estado de cuenta (cualquier corte)\n"
        "- Servicios de cirugía\n"
        "- Nota post-quirúrgica"
    )
    st.markdown("---")
    st.markdown(
        "**Categorías auditadas:**\n"
        "- Validación de tiempos (hora total, minuto 21)\n"
        "- Consistencia de servicios (sala vs O₂, trío recuperación)\n"
        "- Oxígeno (QX vs sala, recuperación, hosp.)\n"
        "- Sala quirúrgica (horas, sevoflurano)\n"
        "- Equipos y servicios (binarios)\n"
        "- Accesorios complementarios (bidireccionales)\n"
        "- Verificaciones negativas\n"
        "- Estancia (habitación, bomba, dietas, RPBI)"
    )

# =========================================================
# ENCABEZADO
# =========================================================
st.title("🏥 Auditor Hospitalario")
st.markdown(
    "Sube los PDFs de la cuenta. El sistema cruza automáticamente "
    "el **estado de cuenta** contra los **servicios de cirugía** y la **nota post-quirúrgica**."
)

archivos_subidos = st.file_uploader(
    "Selecciona los documentos PDF",
    type=["pdf"],
    accept_multiple_files=True,
)

if not archivos_subidos:
    st.info("Sube uno o más archivos PDF para comenzar.")
    st.stop()

archivos_bytes = [(f.name, f.read()) for f in archivos_subidos]

with st.spinner("Analizando documentos…"):
    cuentas = consolidar_por_cuenta(archivos_bytes)

# =========================================================
# MÉTRICAS GLOBALES
# =========================================================
todas_auditorias = {
    cta: construir_auditorias(data, tolerancia_ui)
    for cta, data in cuentas.items()
}

# ── Log por email ─────────────────────────────────────────
_hash_actual = _hash_archivos(archivos_bytes)
if st.session_state.get("_ultimo_log_enviado") != _hash_actual:
    _enviar_log_email(cuentas, todas_auditorias, archivos_bytes)
    st.session_state["_ultimo_log_enviado"] = _hash_actual

total_cuentas    = len(cuentas)
cuentas_con_diff = sum(
    1 for auds in todas_auditorias.values()
    if estado_global(auds)[1] in ("err", "warn")
)
total_reglas_err  = sum(
    sum(1 for a in auds if a["clase"] == "err")
    for auds in todas_auditorias.values()
)
total_reglas_warn = sum(
    sum(1 for a in auds if a["clase"] == "warn")
    for auds in todas_auditorias.values()
)
# Suma global de hallazgos económicos (sobrecobros + faltantes estimados)
monto_global = sum(
    a.get("monto_diff") or 0
    for auds in todas_auditorias.values()
    for a in auds
    if a.get("clase") in ("err", "warn") and a.get("monto_diff")
)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Cuentas",          total_cuentas)
c2.metric("Con diferencias",  cuentas_con_diff)
c3.metric("Errores críticos", total_reglas_err)
c4.metric("Advertencias",     total_reglas_warn)
c5.metric("Monto en hallazgos", f"≈ ${monto_global:,.0f}")

# ── Fix 8: Timestamp y trazabilidad ───────────────────────
_ts_auditoria = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
st.caption(
    f"Auditoría generada: {_ts_auditoria} · "
    f"Hash de archivos: `{_hash_actual[:12]}…` · "
    f"{len(archivos_bytes)} archivo(s) procesados"
)

st.divider()

# =========================================================
# DIALOG POPUP PARA DETALLE DE CUENTA
# =========================================================
@st.dialog("Detalle de cuenta", width="large")
def mostrar_detalle(cuenta_key: str):
    """Muestra el detalle completo de una cuenta en un popup modal."""
    data = cuentas[cuenta_key]
    auds = todas_auditorias[cuenta_key]
    estado_txt, clase = estado_global(auds)

    # ── Encabezado del popup ──────────────────────────────
    seguro_label = data.get("seguro", "")
    st.markdown(
        f'**{cuenta_key}** — {data["paciente"] or "No identificado"}'
        + (f' · {seguro_label}' if seguro_label else "")
    )
    if data.get("fecha_ingreso"):
        st.caption(
            f"Ingreso {data['fecha_ingreso']} → Egreso {data['fecha_egreso']} "
            f"({data['dias_estancia']} día(s))"
        )

    # ── Hallazgos destacados ──────────────────────────────
    errores  = [a for a in auds if a["clase"] == "err"]
    avisos   = [a for a in auds if a["clase"] == "warn"]
    if errores or avisos:
        st.markdown("#### Hallazgos que requieren atención")
        for a in errores + avisos:
            cls = "finding-err" if a["clase"] == "err" else "finding-warn"
            monto = a.get("monto_diff")
            monto_txt = ""
            if monto is not None and monto >= 1:
                etiqueta = "sobrecobro" if (a.get("diff") or 0) > 0 else "faltante"
                monto_txt = f' <b>(≈ ${monto:,.0f} {etiqueta})</b>'
            st.markdown(
                f'<div class="finding-box {cls}">'
                f'<b>{a["label"]}:</b> {a["status"]}.{monto_txt}'
                + (f' {a["nota_auditoria"]}' if a["nota_auditoria"] else "")
                + '</div>',
                unsafe_allow_html=True,
            )

    # ── Toggle: mostrar también auditorías OK ─────────────
    n_ok = sum(1 for a in auds if a["clase"] == "ok")
    mostrar_ok = False
    if n_ok > 0:
        mostrar_ok = st.checkbox(
            f"Mostrar también las {n_ok} validaciones que pasaron correctamente",
            value=False,
            key=f"chk_mostrar_ok_{cuenta_key}",
        )

    # ── Auditorías por categoría (filtradas) ──────────────
    categorias = []
    for a in auds:
        if a["categoria"] not in categorias:
            categorias.append(a["categoria"])

    for cat in categorias:
        items_cat_all = [a for a in auds if a["categoria"] == cat]
        if mostrar_ok:
            items_cat = items_cat_all
        else:
            items_cat = [a for a in items_cat_all if a["clase"] != "ok"]

        # Si la categoría no tiene nada que mostrar, saltarla
        if not items_cat:
            continue

        # Header de categoría con nota de OK ocultas
        n_ok_cat = sum(1 for a in items_cat_all if a["clase"] == "ok")
        sufijo = ""
        if not mostrar_ok and n_ok_cat > 0:
            sufijo = (f' <span style="color:var(--color-text-tertiary);'
                      f'font-weight:400;text-transform:none;letter-spacing:0">'
                      f'· {n_ok_cat} OK ocultas</span>')
        st.markdown(f'<div class="cat-title">{cat}{sufijo}</div>',
                    unsafe_allow_html=True)
        for audit in items_cat:
            render_auditoria(audit)

    # ── Archivos procesados ───────────────────────────────
    st.markdown('<div class="cat-title">Archivos procesados</div>', unsafe_allow_html=True)
    for af in data["archivos"]:
        tipo_label = {
            "servicios_cirugia": "Servicios de cirugía",
            "nota_postquirurgica": "Nota post-quirúrgica",
            "otro": "Tipo no reconocido",
        }.get(af["tipo_documento"],
              af["tipo_documento"].replace("estado_cuenta_", "Estado de cuenta — corte "))
        st.markdown(f"- `{af['archivo']}` → {tipo_label}")

    # ── Fix 3: Botón de descarga de reporte ───────────────
    st.divider()
    html_reporte = _construir_html_reporte_cuenta(
        cuenta_key, data, auds, _hash_actual)
    st.download_button(
        "📥 Descargar reporte de esta cuenta (HTML)",
        data=html_reporte.encode("utf-8"),
        file_name=f"auditoria_{cuenta_key}.html",
        mime="text/html",
        key=f"dl_reporte_{cuenta_key}",
    )


# =========================================================
# LISTA DE CUENTAS
# =========================================================
st.subheader("Cuentas analizadas")

# Ordenar por urgencia: más errores arriba, luego más warnings,
# luego limpias al final. Empate: orden alfabético de cuenta.
def _orden_urgencia(item):
    cta, _ = item
    auds = todas_auditorias[cta]
    n_err  = sum(1 for a in auds if a["clase"] == "err")
    n_warn = sum(1 for a in auds if a["clase"] == "warn")
    return (-n_err, -n_warn, cta)

cuentas_ordenadas = sorted(cuentas.items(), key=_orden_urgencia)

for cuenta, data in cuentas_ordenadas:
    auds        = todas_auditorias[cuenta]
    estado_txt, clase = estado_global(auds)
    n_err  = sum(1 for a in auds if a["clase"] == "err")
    n_warn = sum(1 for a in auds if a["clase"] == "warn")

    resumen_badge = ""
    if n_err:
        resumen_badge += f'<span class="badge badge-err" style="margin-right:4px">{n_err} error(es)</span>'
    if n_warn:
        resumen_badge += f'<span class="badge badge-warn" style="margin-right:4px">{n_warn} aviso(s)</span>'
    if not n_err and not n_warn:
        resumen_badge = badge_html("Sin diferencias", "ok")

    # Sumar monto económico de los hallazgos
    monto_total = sum(
        a.get("monto_diff") or 0
        for a in auds
        if a.get("clase") in ("err", "warn") and a.get("monto_diff")
    )
    monto_html = ""
    if monto_total >= 1:
        monto_html = (f'<span style="font-size:11px;color:#791F1F;font-weight:500;'
                      f'margin-right:10px">≈ ${monto_total:,.0f}</span>')

    # Mostrar seguro en la tarjeta
    seguro_label = data.get("seguro", "")
    seguro_html = f' · <span style="font-size:11px">{seguro_label}</span>' if seguro_label else ""

    # ── Tarjeta + botón de detalle en la misma fila ───────
    col_card, col_btn = st.columns([6, 1])
    with col_card:
        st.markdown(
            f'<div class="cuenta-card">'
            f'{dot_html(clase)}'
            f'<div style="flex:1">'
            f'<span style="font-weight:500;font-size:14px">{cuenta}</span>'
            f'<span style="color:var(--color-text-secondary);font-size:13px;margin-left:10px">'
            f'{data["paciente"] or "No identificado"}{seguro_html}</span>'
            f'</div>'
            f'<span style="font-size:11px;color:var(--color-text-tertiary);margin-right:12px">'
            f'{len(data["archivos"])} archivo(s)</span>'
            f'{monto_html}'
            f'{resumen_badge}'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col_btn:
        if st.button("Ver detalle", key=f"btn_detalle_{cuenta}", use_container_width=True):
            mostrar_detalle(cuenta)

st.divider()

# =========================================================
# EXPORTAR
# =========================================================
st.subheader("📥 Exportar")

filas_res = []
for cuenta, auds in todas_auditorias.items():
    fila = {
        "Cuenta": cuenta,
        "Paciente": cuentas[cuenta]["paciente"],
        "Seguro": cuentas[cuenta].get("seguro", ""),
        "Fecha_auditoria": _ts_auditoria,
        "Hash_archivos": _hash_actual[:12],
    }
    for a in auds:
        fila[a["label"]] = a["status"]
    filas_res.append(fila)
df_res = pd.DataFrame(filas_res)

todos_items = [
    {**i, "tipo_auditoria": "cobrado"}
    for data in cuentas.values()
    for i in data["todos_los_items"]
]
df_items = pd.DataFrame(todos_items) if todos_items else pd.DataFrame()

col1, col2 = st.columns(2)
with col1:
    st.download_button(
        "Resumen de auditoría (CSV)",
        data=df_res.to_csv(index=False).encode("utf-8"),
        file_name="auditoria_resumen.csv",
        mime="text/csv",
    )
with col2:
    if not df_items.empty:
        st.download_button(
            "Todos los ítems del estado de cuenta (CSV)",
            data=df_items.to_csv(index=False).encode("utf-8"),
            file_name="auditoria_items.csv",
            mime="text/csv",
        )

