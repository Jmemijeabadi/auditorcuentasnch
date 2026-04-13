import streamlit as st
import pdfplumber
import pandas as pd
import re
import unicodedata
import smtplib
import hashlib
import traceback
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from collections import defaultdict

st.set_page_config(page_title="Auditor Hospitalario", layout="wide", page_icon="🏥")

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

# Habitación
CODIGO_HABITACION = "HOS-0000001"

# Servicios binarios: (key, label, patron_en_servicios, codigos_en_cuenta, area_cuenta)
SERVICIOS_BINARIOS_DEF = [
    ("electrocauterio", "Electrocauterio",
     r"x\s+electrocauterio",
     {"IBM-0000032"}, "quirofano"),
    ("aspirador", "Torre de aspiración",
     r"x\s+torre de aspiracion",
     {"IBM-0000008"}, "quirofano"),
    ("monitor_qx", "Monitor QX",
     r"x\s+monitor sv\s*qx",
     {"IBM-0000035"}, "quirofano"),
    ("sala_rec", "Sala de recuperación",
     r"x\s+sala de recuperacion\b",
     {"REC-0000001"}, "recuperacion"),
    ("monitor_rec", "Monitor SV recuperación",
     r"x\s+monitor sv recuperacion",
     {"IBM-0000010"}, "recuperacion"),
    # ── PUNTO 10: Microscopio ─────────────────────────────
    ("microscopio", "Microscopio-TIVATO",
     r"x\s+microscopio",
     {"IBM-0000034"}, "quirofano"),
    # ── PUNTO 11: Arco en C ──────────────────────────────
    ("arco_c", "Arco en C",
     r"x\s+arco en c",
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
    t = normalizar(compact(texto))
    # Desde servicios de cirugía
    m = re.search(r"seguro:\s*(.+?)(?:cirugia programada|$)", t)
    if m:
        seg = m.group(1).strip()
        if "particular" in seg:
            return "particular"
        return seg
    # Desde estado de cuenta
    m = re.search(r"cia\.?\s*cliente\s*(.+?)(?:codigo|$)", t)
    if m:
        seg = m.group(1).strip()
        if "particular" in seg:
            return "particular"
        return seg
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
    r"(?:\s+(?P<folio2>\S+))?$",
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
    m = re.search(r"x\s+sala de cirugia x hr\s+(\d+(?:\.\d+)?)\s*hrs?", t_norm)
    if m:
        resultado["sala_hrs_normal"] = a_float(m.group(1))

    m = re.search(r"x\s+sala de cirugia adicional\s+(\d+(?:\.\d+)?)\s*hrs?", t_norm)
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
    m = re.search(r"x\s+sevoflorane?\s+([\d,.]+)\s*ml", t_norm)
    if m:
        resultado["sevoflurano_ml"] = a_float(m.group(1))

    # ── PUNTO 1/7: Ingreso y egreso de sala ───────────────
    m = re.search(
        r"ingreso a sala:\s*(\d{1,2}:\d{2}\s*[ap]m)\s+egreso de\s*sala:\s*(\d{1,2}:\d{2}\s*[ap]m)",
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
        re.search(r"x\s+maquina de anestesia", t_norm))

    # ── PUNTO 10: Microscopio marcado ─────────────────────
    resultado["microscopio"] = bool(
        re.search(r"x\s+microscopio", t_norm))

    # ── PUNTO 11: Arco en C horas ─────────────────────────
    m = re.search(r"x\s+arco en c\s+(\d+(?:\.\d+)?)\s*hrs?", t_norm)
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
    m = re.search(r"(\d+)\s*(?:hrs?|horeas?)\s*(?:y|con)?\s*(\d+)\s*min", bloque)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        return round(h + mn / 60, 2)

    # Formato solo horas "Xhrs" / "X hrs" / "X horeas"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:hrs?|horeas?)", bloque)
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
            # ── Fix 2: Deduplicar ítems entre cortes (EXTRAS vs PACIENTE) ──
            existentes = {
                (i["codigo"], i["cantidad"], i["fecha"], i["folio"])
                for i in cuentas[cuenta]["todos_los_items"]
            }
            items_nuevos = [
                i for i in items
                if (i["codigo"], i["cantidad"], i["fecha"], i["folio"]) not in existentes
            ]
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

            # Actualizar seguro desde servicios
            sc_actual = cuentas[cuenta]["servicios_cirugia"]
            if cuentas[cuenta]["seguro"] is None and sc_actual.get("seguro"):
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
                    f"Regla: no se cobra máquina de anestesia en pacientes particulares."
                ),
            })

    # ══════════════════════════════════════════════════════
    # PUNTO 4: Horas de sala deben coincidir con oxígeno QX
    # ══════════════════════════════════════════════════════
    if sc:
        sala_total_doc = sc.get("sala_hrs_normal", 0) + sc.get("sala_hrs_adicional", 0)
        ox_qx_doc      = sc.get("oxigeno_qx", 0)

        if sala_total_doc > 0 or ox_qx_doc > 0:
            if abs(sala_total_doc - ox_qx_doc) < 0.01:
                status = f"ok — sala {sala_total_doc:.0f} hrs = oxígeno QX {ox_qx_doc:.0f} hrs"
                clase  = "ok"
            else:
                status = (f"sala {sala_total_doc:.0f} hrs ≠ oxígeno QX {ox_qx_doc:.0f} hrs "
                          f"en hoja de servicios")
                clase  = "warn"
            auditorias.append({
                "categoria": "Consistencia de servicios",
                "key":       "sala_vs_oxigeno",
                "label":     "Horas de sala vs oxígeno QX (en hoja de servicios)",
                "tipo":      "informativo",
                "unidad":    "hrs",
                "cobrado":   sala_total_doc,
                "esperado":  ox_qx_doc,
                "status":    status,
                "diff":      round(sala_total_doc - ox_qx_doc, 1),
                "clase":     clase,
                "items_cobrados":  [],
                "items_esperados": [],
                "nota_auditoria": (
                    f"Servicios documenta: sala {sc.get('sala_hrs_normal',0):.0f} + "
                    f"{sc.get('sala_hrs_adicional',0):.0f} adicional = {sala_total_doc:.0f} hrs. "
                    f"Oxígeno QX documentado: {ox_qx_doc:.0f} hrs. Deben coincidir."
                ),
            })

    # ══════════════════════════════════════════════════════
    # 1. OXÍGENO (existente)
    # ══════════════════════════════════════════════════════
    for area_key, area_label, esp_key in [
        ("quirofano",      "Quirófano",     "oxigeno_qx"),
        ("recuperacion",   "Recuperación",  "oxigeno_rec"),
    ]:
        ox_items = por_codigo(CODIGOS_OXIGENO, area_key)
        cobrado  = round(sum(i["cantidad"] for i in ox_items), 3)
        esperado = sc.get(esp_key, 0.0) or None if sc else None
        if not sc:
            esperado = None
        elif sc.get(esp_key, 0.0) == 0 and cobrado == 0:
            continue
        status, diff, clase = evaluar(cobrado, esperado, tolerancia)
        auditorias.append({
            "categoria": "Oxígeno",
            "key":       f"oxigeno_{area_key}",
            "label":     f"Oxígeno — {area_label}",
            "tipo":      "numerico",
            "unidad":    "hrs",
            "cobrado":   cobrado,
            "esperado":  esperado,
            "status":    status,
            "diff":      diff,
            "clase":     clase,
            "items_cobrados":  ox_items,
            "items_esperados": [e for e in sc.get("evidencias_oxigeno",[])
                                if e["area"] == area_key],
            "nota_auditoria": None,
        })

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
    # ══════════════════════════════════════════════════════
    bomba_items_qx = por_codigo({CODIGO_BOMBA})
    equipo_inf = por_codigo({CODIGO_EQUIPO_INFUSOMAT})
    if bomba_items_qx and not equipo_inf:
        auditorias.append({
            "categoria": "Accesorios complementarios",
            "key":       "bomba_infusomat",
            "label":     "Bomba de infusión → equipo infusomat",
            "tipo":      "informativo",
            "unidad":    "",
            "cobrado":   0,
            "esperado":  None,
            "status":    "bomba cobrada sin equipo infusomat (ALM-0000869)",
            "diff":      None,
            "clase":     "err",
            "items_cobrados":  bomba_items_qx,
            "items_esperados": [],
            "nota_auditoria": "Cada uso de bomba de infusión debe ir con equipo infusomat.",
        })
    elif bomba_items_qx and equipo_inf:
        auditorias.append({
            "categoria": "Accesorios complementarios",
            "key":       "bomba_infusomat",
            "label":     "Bomba de infusión → equipo infusomat",
            "tipo":      "informativo",
            "unidad":    "",
            "cobrado":   0,
            "esperado":  None,
            "status":    f"ok — {len(bomba_items_qx)} bomba(s), {len(equipo_inf)} equipo(s)",
            "diff":      None,
            "clase":     "ok",
            "items_cobrados":  bomba_items_qx + equipo_inf,
            "items_esperados": [],
            "nota_auditoria": None,
        })

    # ══════════════════════════════════════════════════════
    # PUNTO 10: Microscopio + funda
    # ══════════════════════════════════════════════════════
    micro_items = por_codigo({CODIGO_MICROSCOPIO}, "quirofano")
    funda_micro = por_codigo({CODIGO_FUNDA_MICROSCOPIO}, "quirofano")
    if micro_items:
        if funda_micro:
            status = "ok — microscopio y funda presentes"
            clase  = "ok"
        else:
            status = "microscopio cobrado sin funda (ALM-0000878)"
            clase  = "err"
        auditorias.append({
            "categoria": "Accesorios complementarios",
            "key":       "microscopio_funda",
            "label":     "Microscopio → funda",
            "tipo":      "informativo",
            "unidad":    "",
            "cobrado":   0,
            "esperado":  None,
            "status":    status,
            "diff":      None,
            "clase":     clase,
            "items_cobrados":  micro_items + funda_micro,
            "items_esperados": [],
            "nota_auditoria": "Uso de microscopio debe ir con funda desechable.",
        })

    # ══════════════════════════════════════════════════════
    # PUNTO 11: Arco en C + funda
    # ══════════════════════════════════════════════════════
    arco_items = por_codigo({CODIGO_ARCO_C}, "quirofano")
    funda_arco = por_codigo({CODIGO_FUNDA_ARCO_C}, "quirofano")
    if arco_items:
        if funda_arco:
            status = "ok — arco en C y funda presentes"
            clase  = "ok"
        else:
            status = "arco en C cobrado sin funda (ALM-0000877)"
            clase  = "err"
        auditorias.append({
            "categoria": "Accesorios complementarios",
            "key":       "arco_funda",
            "label":     "Arco en C → funda",
            "tipo":      "informativo",
            "unidad":    "",
            "cobrado":   0,
            "esperado":  None,
            "status":    status,
            "diff":      None,
            "clase":     clase,
            "items_cobrados":  arco_items + funda_arco,
            "items_esperados": [],
            "nota_auditoria": "Uso de arco en C debe ir con funda estéril desechable.",
        })

    # ══════════════════════════════════════════════════════
    # PUNTO 5: Trío de recuperación (sala + monitor + oxígeno)
    # ══════════════════════════════════════════════════════
    rec_sala    = por_codigo({"REC-0000001"}, "recuperacion")
    rec_monitor = por_codigo({"IBM-0000010"}, "recuperacion")
    rec_oxigeno = por_codigo(CODIGOS_OXIGENO, "recuperacion")

    presentes_rec = {
        "Sala de recuperación":  len(rec_sala) > 0,
        "Monitor SV":           len(rec_monitor) > 0,
        "Oxígeno recuperación": len(rec_oxigeno) > 0,
    }
    n_presentes = sum(presentes_rec.values())

    if n_presentes > 0 and n_presentes < 3:
        faltantes = [k for k, v in presentes_rec.items() if not v]
        auditorias.append({
            "categoria": "Consistencia de servicios",
            "key":       "trio_recuperacion",
            "label":     "Trío de recuperación (sala + monitor + oxígeno)",
            "tipo":      "informativo",
            "unidad":    "",
            "cobrado":   0,
            "esperado":  None,
            "status":    f"incompleto — falta(n): {', '.join(faltantes)}",
            "diff":      None,
            "clase":     "warn",
            "items_cobrados":  rec_sala + rec_monitor + rec_oxigeno,
            "items_esperados": [],
            "nota_auditoria": (
                "Los 3 conceptos de recuperación (sala, monitor y oxígeno) "
                "deben estar todos presentes en el segmento de recuperación."
            ),
        })
    elif n_presentes == 3:
        auditorias.append({
            "categoria": "Consistencia de servicios",
            "key":       "trio_recuperacion",
            "label":     "Trío de recuperación (sala + monitor + oxígeno)",
            "tipo":      "informativo",
            "unidad":    "",
            "cobrado":   0,
            "esperado":  None,
            "status":    "ok — los 3 conceptos presentes en recuperación",
            "diff":      None,
            "clase":     "ok",
            "items_cobrados":  rec_sala + rec_monitor + rec_oxigeno,
            "items_esperados": [],
            "nota_auditoria": None,
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
            status, clase = "nota dice SÍ y hay cargos — verificar concordancia", "warn"
        elif hemotrans is True and not sangre_items:
            status, clase = "nota dice SÍ pero no hay cargos de sangre", "warn"
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
                f"{'SÍ' if hemotrans else 'NO' if hemotrans is False else 'no documentada'}."
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
    # 5. ESTANCIA (existente + Punto 6 RPBI)
    # ══════════════════════════════════════════════════════

    # ── PUNTO 6: RPBI después de 7 días ──────────────────
    rpbi_items = por_codigo({CODIGO_RPBI})
    rpbi_count = len(rpbi_items)
    if rpbi_items or dias:
        if dias and dias > DIAS_RPBI_ADICIONAL:
            rpbi_esperado = 1 + ((dias - 1) // DIAS_RPBI_ADICIONAL)
            if rpbi_count < rpbi_esperado:
                status = (f"estancia {dias} días > {DIAS_RPBI_ADICIONAL}: "
                          f"se esperan {rpbi_esperado} cargo(s), hay {rpbi_count}")
                clase = "err"
            else:
                status = f"ok — {rpbi_count} cargo(s) para {dias} día(s)"
                clase = "ok"
        elif dias:
            status = f"ok — {rpbi_count} cargo(s) para {dias} día(s) (≤{DIAS_RPBI_ADICIONAL})"
            clase = "ok"
        else:
            status = f"{rpbi_count} cargo(s) — sin datos de estancia"
            clase = "gray"

        auditorias.append({
            "categoria": "Estancia",
            "key":       "rpbi",
            "label":     "Disposición de RPBI",
            "tipo":      "numerico",
            "unidad":    "cargo(s)",
            "cobrado":   float(rpbi_count),
            "esperado":  None,
            "status":    status,
            "diff":      None,
            "clase":     clase,
            "items_cobrados":  rpbi_items,
            "items_esperados": [],
            "nota_auditoria": (
                f"Regla: después de {DIAS_RPBI_ADICIONAL} días se debe cargar otro RPBI. "
                f"Estancia: {dias or '?'} día(s)."
            ),
        })

    # Días de habitación
    hab_items = por_codigo({CODIGO_HABITACION})
    hab_cobrado = len(hab_items)
    if hab_items or dias:
        status, diff, clase = evaluar(float(hab_cobrado), float(dias) if dias else None, 0)
        auditorias.append({
            "categoria": "Estancia",
            "key":       "habitacion",
            "label":     "Días de habitación",
            "tipo":      "numerico",
            "unidad":    "días",
            "cobrado":   float(hab_cobrado),
            "esperado":  float(dias) if dias else None,
            "status":    status,
            "diff":      diff,
            "clase":     clase,
            "items_cobrados":  hab_items,
            "items_esperados": [],
            "nota_auditoria": (
                f"Ingreso {data['fecha_ingreso']} → egreso {data['fecha_egreso']} "
                f"= {dias} noche(s)."
            ) if dias else None,
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
            "esperado":  float(dias) if dias else None,
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

    return auditorias

# =========================================================
# FIX 3: REPORTE HTML DESCARGABLE POR CUENTA
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
            celdas += f'<td{align}{mono}>{v}</td>'
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
    h = hashlib.md5()
    for nombre, contenido in archivos_bytes:
        h.update(nombre.encode())
        h.update(contenido[:256])
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
        pass


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
        "- Oxígeno (QX, recuperación, hosp.)\n"
        "- Sala quirúrgica (horas, sevoflurano)\n"
        "- Equipos y servicios (binarios)\n"
        "- Accesorios complementarios (8 validaciones)\n"
        "- Verificaciones negativas (2)\n"
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

c1, c2, c3, c4 = st.columns(4)
c1.metric("Cuentas",          total_cuentas)
c2.metric("Con diferencias",  cuentas_con_diff)
c3.metric("Errores críticos", total_reglas_err)
c4.metric("Advertencias",     total_reglas_warn)

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
            st.markdown(
                f'<div class="finding-box {cls}">'
                f'<b>{a["label"]}:</b> {a["status"]}.'
                + (f' {a["nota_auditoria"]}' if a["nota_auditoria"] else "")
                + '</div>',
                unsafe_allow_html=True,
            )

    # ── Auditorías por categoría ──────────────────────────
    categorias = []
    for a in auds:
        if a["categoria"] not in categorias:
            categorias.append(a["categoria"])

    for cat in categorias:
        items_cat = [a for a in auds if a["categoria"] == cat]
        st.markdown(f'<div class="cat-title">{cat}</div>', unsafe_allow_html=True)
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

for cuenta, data in cuentas.items():
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
