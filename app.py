import streamlit as st
import pdfplumber
import pandas as pd
import re
import unicodedata
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

# Bomba de infusión
CODIGO_BOMBA = "IBM-0000001"

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
    """Extrae fechas de ingreso y egreso del encabezado del estado de cuenta."""
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
    """Extrae TODOS los ítems del estado de cuenta (no solo oxígeno)."""
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
# EXTRACCIÓN DE SERVICIOS DE CIRUGÍA
# =========================================================
def extraer_servicios_cirugia(texto: str) -> dict:
    """Extrae todos los datos auditables de la hoja de servicios de cirugía."""
    t_norm  = normalizar(compact(texto))
    t_multi = normalizar(texto)  # conserva saltos de línea para búsquedas

    resultado = {
        "hora_total_qx":      None,
        "sala_hrs_normal":    0.0,
        "sala_hrs_adicional": 0.0,
        "oxigeno_qx":         0.0,
        "oxigeno_rec":        0.0,
        "sevoflurano_ml":     None,
        "servicios_marcados": {},
        "evidencias_oxigeno": [],
    }

    # Hora total quirófano
    m = re.search(r"hora total de quirofano:\s*(\d+(?:\.\d+)?)\s*hrs?", t_norm)
    if m:
        resultado["hora_total_qx"] = a_float(m.group(1))

    # Sala de cirugía — primera hora y adicionales
    m = re.search(r"x\s+sala de cirugia x hr\s+(\d+(?:\.\d+)?)\s*hrs?", t_norm)
    if m:
        resultado["sala_hrs_normal"] = a_float(m.group(1))

    m = re.search(r"x\s+sala de cirugia adicional\s+(\d+(?:\.\d+)?)\s*hrs?", t_norm)
    if m:
        resultado["sala_hrs_adicional"] = a_float(m.group(1))

    # Oxígeno QX y recuperación (con evidencias)
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

    # Sevoflurano
    m = re.search(r"x\s+sevoflorane?\s+([\d,.]+)\s*ml", t_norm)
    if m:
        resultado["sevoflurano_ml"] = a_float(m.group(1))

    # Servicios binarios
    for key, label, patron, _, _ in SERVICIOS_BINARIOS_DEF:
        resultado["servicios_marcados"][key] = bool(re.search(patron, t_norm))

    return resultado

# =========================================================
# EXTRACCIÓN DE NOTA POST-QUIRÚRGICA
# =========================================================
def extraer_nota_postqx(texto: str) -> dict:
    t = normalizar(compact(texto))
    resultado = {
        "tiempo_quirurgico": None,
        "hemotransfusion":   None,   # True = SÍ hubo, False = NO, None = no encontrado
        "histopatologico":   None,
    }
    m = re.search(r"tiempo quirurgico:\s*(\d+(?:\.\d+)?)\s*hrs?", t)
    if m:
        resultado["tiempo_quirurgico"] = a_float(m.group(1))

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
        "todos_los_items":    [],          # todos los ítems del estado de cuenta
        "servicios_cirugia":  None,        # dict de extraer_servicios_cirugia
        "nota_postqx":        None,        # dict de extraer_nota_postqx
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
            cuentas[cuenta]["todos_los_items"].extend(items)
            # Fechas de estancia (solo si aún no las tenemos)
            if cuentas[cuenta]["fecha_ingreso"] is None:
                fi, fe, ds = extraer_fechas_estancia(texto)
                if fi:
                    cuentas[cuenta]["fecha_ingreso"] = fi
                    cuentas[cuenta]["fecha_egreso"]  = fe
                    cuentas[cuenta]["dias_estancia"] = ds

        elif tipo == "servicios_cirugia":
            if cuentas[cuenta]["servicios_cirugia"] is None:
                cuentas[cuenta]["servicios_cirugia"] = extraer_servicios_cirugia(texto)
            else:
                # Acumular si hay múltiples hojas
                sc_nuevo = extraer_servicios_cirugia(texto)
                sc = cuentas[cuenta]["servicios_cirugia"]
                for k in ("oxigeno_qx", "oxigeno_rec", "sala_hrs_normal", "sala_hrs_adicional"):
                    sc[k] += sc_nuevo[k]
                sc["evidencias_oxigeno"].extend(sc_nuevo["evidencias_oxigeno"])
                if sc["hora_total_qx"] is None:
                    sc["hora_total_qx"] = sc_nuevo["hora_total_qx"]
                if sc["sevoflurano_ml"] is None:
                    sc["sevoflurano_ml"] = sc_nuevo["sevoflurano_ml"]

        elif tipo == "nota_postquirurgica":
            if cuentas[cuenta]["nota_postqx"] is None:
                cuentas[cuenta]["nota_postqx"] = extraer_nota_postqx(texto)

    return cuentas

# =========================================================
# CONSTRUCCIÓN DE AUDITORÍAS
# =========================================================
def evaluar(cobrado, esperado, tolerancia: float = 0.01):
    """Devuelve (status_txt, diff, clase_css)."""
    if esperado is None:
        return "sin regla", None, "gray"
    diff = round(cobrado - esperado, 3)
    if abs(diff) <= tolerancia:
        return "ok", diff, "ok"
    if diff < 0:
        return f"faltan {abs(diff):.2f}", diff, "err"
    return f"sobran {abs(diff):.2f}", diff, "warn"

def construir_auditorias(data: dict, tolerancia: float) -> list:
    """
    Genera la lista completa de auditorías a partir de los datos
    consolidados de una cuenta.
    """
    items     = data["todos_los_items"]
    sc        = data["servicios_cirugia"] or {}
    nota      = data["nota_postqx"] or {}
    dias      = data["dias_estancia"]

    def por_codigo(codigos: set, area: str = None):
        r = [i for i in items if i["codigo"] in codigos]
        if area:
            r = [i for i in r if i["area"] == area]
        return r

    def contiene_palabra(desc: str, palabras: set) -> bool:
        d = normalizar(desc)
        return any(p in d for p in palabras)

    auditorias = []

    # ── 1. OXÍGENO ────────────────────────────────────────
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

    # ── 2. SALA QUIRÚRGICA ────────────────────────────────
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

    # ── 3. SEVOFLURANO ────────────────────────────────────
    sevo_items = [i for i in items if i["codigo"] == CODIGO_SEVOFLURANO]
    sevo_cobrado = round(sum(i["cantidad"] for i in sevo_items), 2)
    sevo_esp = sc.get("sevoflurano_ml") if sc else None

    if sevo_items or sevo_esp:
        status, diff, clase = evaluar(sevo_cobrado, sevo_esp, tolerancia=1.0)
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
            "nota_auditoria": "Tolerancia de ±1.0 ml por redondeo.",
        })

    # ── 4. SERVICIOS BINARIOS ─────────────────────────────
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
        else:  # not marcado and cobrado_bool
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

    # ── 5. VERIFICACIONES NEGATIVAS ───────────────────────
    # Hemotransfusión
    hemotrans = nota.get("hemotransfusion")  # False = nota dice NO
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

    # Histopatológico
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

    # ── 6. ESTANCIA ───────────────────────────────────────
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

    # Bomba de infusión
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
        max_esperado = dias * 4  # máximo razonable: 4 por día
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
        "- Oxígeno (QX, recuperación, hosp.)\n"
        "- Sala quirúrgica (horas, sevoflurano)\n"
        "- Equipos y servicios (5 binarios)\n"
        "- Verificaciones negativas (2)\n"
        "- Estancia (habitación, bomba, dietas)"
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

st.divider()

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

    st.markdown(
        f'<div class="cuenta-card">'
        f'{dot_html(clase)}'
        f'<div style="flex:1">'
        f'<span style="font-weight:500;font-size:14px">{cuenta}</span>'
        f'<span style="color:var(--color-text-secondary);font-size:13px;margin-left:10px">'
        f'{data["paciente"] or "No identificado"}</span>'
        f'</div>'
        f'<span style="font-size:11px;color:var(--color-text-tertiary);margin-right:12px">'
        f'{len(data["archivos"])} archivo(s)</span>'
        f'{resumen_badge}'
        f'</div>',
        unsafe_allow_html=True,
    )

    with st.expander(f"Ver detalle → {cuenta}"):

        # ── Hallazgos destacados ──────────────────────────
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

        # ── Auditorías por categoría ──────────────────────
        categorias = []
        for a in auds:
            if a["categoria"] not in categorias:
                categorias.append(a["categoria"])

        for cat in categorias:
            items_cat = [a for a in auds if a["categoria"] == cat]
            st.markdown(f'<div class="cat-title">{cat}</div>', unsafe_allow_html=True)
            for audit in items_cat:
                render_auditoria(audit)

        # ── Archivos procesados ───────────────────────────
        with st.expander("📄 Archivos procesados"):
            for af in data["archivos"]:
                tipo_label = {
                    "servicios_cirugia": "Servicios de cirugía",
                    "nota_postquirurgica": "Nota post-quirúrgica",
                    "otro": "Tipo no reconocido",
                }.get(af["tipo_documento"],
                      af["tipo_documento"].replace("estado_cuenta_", "Estado de cuenta — corte "))
                st.markdown(f"- `{af['archivo']}` → {tipo_label}")

st.divider()

# =========================================================
# EXPORTAR
# =========================================================
st.subheader("📥 Exportar")

# Resumen tabular
filas_res = []
for cuenta, auds in todas_auditorias.items():
    fila = {"Cuenta": cuenta, "Paciente": cuentas[cuenta]["paciente"]}
    for a in auds:
        fila[a["label"]] = a["status"]
    filas_res.append(fila)
df_res = pd.DataFrame(filas_res)

# Detalle de ítems
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
