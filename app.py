import streamlit as st
import pdfplumber
import pandas as pd
import re
import unicodedata
from collections import defaultdict

st.set_page_config(
    page_title="Auditor de Oxígeno",
    layout="wide",
    page_icon="🏥",
)

# =========================================================
# CSS GLOBAL
# =========================================================
st.markdown("""
<style>
/* ── Tarjeta de cuenta ── */
.cuenta-card {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    border: 0.5px solid var(--color-border-tertiary, #e0e0e0);
    border-radius: 10px;
    background: var(--color-background-primary, #fff);
    margin-bottom: 8px;
    cursor: default;
}
.dot {
    width: 11px; height: 11px;
    border-radius: 50%;
    flex-shrink: 0;
}
.dot-ok   { background: #639922; }
.dot-warn { background: #EF9F27; }
.dot-err  { background: #E24B4A; }
.dot-gray { background: #888780; }

/* ── Badges de estado ── */
.badge {
    display: inline-flex; align-items: center;
    font-size: 11px; font-weight: 500;
    padding: 3px 9px; border-radius: 20px;
    white-space: nowrap;
}
.badge-ok   { background:#EAF3DE; color:#27500A; }
.badge-warn { background:#FAEEDA; color:#633806; }
.badge-err  { background:#FCEBEB; color:#791F1F; }
.badge-gray { background:#F1EFE8; color:#444441; }

/* ── Barra de progreso ── */
.bar-wrap {
    background: #e8e8e4;
    border-radius: 4px; height: 9px;
    width: 100%; overflow: hidden; margin: 3px 0 2px;
}
.bar-fill { height: 100%; border-radius: 4px; }
.bar-ok   { background: #639922; }
.bar-warn { background: #EF9F27; }
.bar-err  { background: #E24B4A; }
.bar-gray { background: #888780; }

/* ── Tarjeta métrica ── */
.metric-card {
    background: var(--color-background-secondary, #f5f5f0);
    border-radius: 8px;
    padding: 10px 14px;
}
.metric-card .mc-label {
    font-size: 11px;
    color: var(--color-text-secondary, #666);
    margin-bottom: 2px;
}
.metric-card .mc-value {
    font-size: 22px;
    font-weight: 500;
    line-height: 1.2;
}
.metric-card-danger { background: #FCEBEB; }
.metric-card-danger .mc-label { color: #A32D2D; }
.metric-card-danger .mc-value { color: #A32D2D; }

/* ── Hallazgo / issue box ── */
.finding-box {
    border-left: 3px solid;
    padding: 8px 12px;
    border-radius: 0 6px 6px 0;
    font-size: 13px;
    margin-bottom: 6px;
}
.finding-err  { border-color:#E24B4A; background:#FCEBEB; color:#791F1F; }
.finding-warn { border-color:#EF9F27; background:#FAEEDA; color:#633806; }
.finding-ok   { border-color:#639922; background:#EAF3DE; color:#27500A; }
.finding-gray { border-color:#888780; background:#F1EFE8; color:#444441; }

/* ── Tabla de evidencia ── */
.ev-table { width:100%; border-collapse:collapse; font-size:12px; }
.ev-table th {
    text-align:left; padding:5px 8px;
    background:var(--color-background-tertiary,#f0f0ec);
    border-bottom:0.5px solid var(--color-border-tertiary,#e0e0e0);
    font-weight:500; color:var(--color-text-secondary,#666);
}
.ev-table td {
    padding:5px 8px;
    border-bottom:0.5px solid var(--color-border-tertiary,#e0e0e0);
    color:var(--color-text-primary,#222);
}
.ev-table tr:last-child td { border-bottom:none; }
.mono { font-family: var(--font-mono, monospace); font-size:11px; }
</style>
""", unsafe_allow_html=True)

# =========================================================
# UTILIDADES
# =========================================================
def normalizar_texto(texto: str) -> str:
    texto = texto.lower()
    texto = "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\r", "\n", texto)
    return texto

def compactar_espacios(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()

def a_float_seguro(valor) -> float:
    try:
        return float(str(valor).replace(",", "").strip())
    except Exception:
        return 0.0

def extraer_texto_pdf(archivo_pdf) -> str:
    archivo_pdf.seek(0)
    partes = []
    try:
        with pdfplumber.open(archivo_pdf) as pdf:
            for i, pagina in enumerate(pdf.pages, start=1):
                texto = pagina.extract_text()
                if texto:
                    partes.append(texto)
                else:
                    st.warning(
                        f"⚠️ '{getattr(archivo_pdf,'name','?')}' "
                        f"— página {i} sin texto extraíble."
                    )
    except Exception as e:
        st.error(f"❌ Error al leer '{getattr(archivo_pdf,'name','?')}': {e}")
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
        texto, re.IGNORECASE | re.DOTALL,
    )
    if m:
        nombre_crudo = compactar_espacios(m.group(1))
    if not nombre_crudo:
        m = re.search(
            r"Nombre:\s*(.+?)\s*Fecha de nacimiento:",
            texto, re.IGNORECASE | re.DOTALL,
        )
        if m:
            nombre_crudo = compactar_espacios(m.group(1))
    if not nombre_crudo:
        return "No identificado"
    nombre_limpio = re.split(r"\s+\d{2,4}[-/]\d{2}[-/]\d{2,4}", nombre_crudo)[0]
    nombre_limpio = re.sub(r"\s+\d+\s+AÑO[S]?.*$", "", nombre_limpio, flags=re.IGNORECASE)
    return compactar_espacios(nombre_limpio).title()

def detectar_tipo_documento(texto: str) -> str:
    t = normalizar_texto(texto)
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

def canonical_departamento(nombre: str) -> str:
    n = normalizar_texto(nombre)
    if "quirofano" in n:   return "quirofano"
    if "recuperacion" in n: return "recuperacion"
    if "hospitalizacion" in n: return "hospitalizacion"
    if "caja" in n:         return "caja"
    return "otro"

# =========================================================
# BLOQUES DEPARTAMENTO
# =========================================================
def extraer_bloques_departamento(texto: str):
    patron = re.compile(r"(?im)^Departamento:\s*(.*)$")
    matches = list(patron.finditer(texto))
    bloques = []
    for i, match in enumerate(matches):
        encabezado = match.group(1).strip()
        inicio = match.end()
        fin = matches[i + 1].start() if i + 1 < len(matches) else len(texto)
        bloques.append({
            "encabezado": encabezado,
            "departamento": canonical_departamento(encabezado),
            "contenido": texto[inicio:fin],
        })
    return bloques

# =========================================================
# REGEX PRINCIPAL
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

CODIGOS_OXIGENO = {"APR-0000003"}

def es_linea_oxigeno(descripcion: str, codigo: str = "") -> bool:
    if codigo and codigo.upper() not in CODIGOS_OXIGENO:
        return False
    return "oxigeno" in normalizar_texto(descripcion)

def _parsear_fecha_folio(fecha_folio_raw, folio2_raw):
    if not fecha_folio_raw:
        return "", ""
    if re.match(r"^\d{2}-\d{2}-\d{4}$", fecha_folio_raw):
        return fecha_folio_raw, folio2_raw or ""
    if len(fecha_folio_raw) > 10 and re.match(r"\d{2}-\d{2}-\d{4}", fecha_folio_raw):
        return fecha_folio_raw[:10], fecha_folio_raw[10:]
    return "", fecha_folio_raw

# =========================================================
# EXTRACCIÓN DE ÍTEMS DE OXÍGENO
# =========================================================
def extraer_items_oxigeno_estado_cuenta(texto, nombre_archivo, tipo_doc, cuenta):
    items = []
    sin_match = []
    for bloque in extraer_bloques_departamento(texto):
        depto = bloque["departamento"]
        if depto == "caja":
            continue
        for linea in bloque["contenido"].splitlines():
            lc = compactar_espacios(linea)
            if not lc:
                continue
            m = ITEM_RE.match(lc)
            if not m:
                if "oxigeno" in normalizar_texto(lc):
                    sin_match.append(lc)
                continue
            codigo = m.group("codigo")
            desc   = m.group("descripcion")
            if not es_linea_oxigeno(desc, codigo):
                continue
            fecha, folio = _parsear_fecha_folio(
                m.group("fecha_folio"), m.group("folio2")
            )
            items.append({
                "cuenta": cuenta, "archivo": nombre_archivo,
                "tipo_documento": tipo_doc, "area": depto,
                "codigo": codigo, "descripcion": desc,
                "cantidad": a_float_seguro(m.group("cantidad")),
                "precio_unitario": a_float_seguro(m.group("precio")),
                "subtotal": a_float_seguro(m.group("subtotal")),
                "fecha": fecha, "folio": folio, "linea_original": lc,
            })
    if sin_match:
        st.warning(
            f"⚠️ '{nombre_archivo}': {len(sin_match)} línea(s) con 'oxígeno' "
            f"no pudieron parsearse."
        )
    return items

# =========================================================
# EXTRACCIÓN SERVICIOS DE CIRUGÍA
# =========================================================
def extraer_evidencias_servicios_cirugia(texto, nombre_archivo, cuenta):
    evidencias = []
    hora_total = None
    for linea in texto.splitlines():
        original = compactar_espacios(linea)
        if not original:
            continue
        n = normalizar_texto(original)
        m = re.search(r"hora total de quirofano:\s*(\d+(?:\.\d+)?)\s*hrs?", n)
        if m:
            hora_total = a_float_seguro(m.group(1))
        m = re.search(r"oxigeno x hr\s+(\d+(?:\.\d+)?)\s*hrs?", n)
        if m:
            evidencias.append({
                "cuenta": cuenta, "archivo": nombre_archivo,
                "tipo_documento": "servicios_cirugia", "area": "quirofano",
                "cantidad_esperada": a_float_seguro(m.group(1)),
                "linea_original": original,
            })
        m = re.search(r"oxigeno recuperacion\s+(\d+(?:\.\d+)?)\s*hrs?", n)
        if m:
            evidencias.append({
                "cuenta": cuenta, "archivo": nombre_archivo,
                "tipo_documento": "servicios_cirugia", "area": "recuperacion",
                "cantidad_esperada": a_float_seguro(m.group(1)),
                "linea_original": original,
            })
    esperado = {"quirofano": 0.0, "recuperacion": 0.0,
                "hora_total_quirofano_documentada": hora_total}
    for ev in evidencias:
        esperado[ev["area"]] += ev["cantidad_esperada"]
    return esperado, evidencias

def extraer_tiempo_postquirurgico(texto: str):
    t = compactar_espacios(normalizar_texto(texto))
    m = re.search(r"tiempo quirurgico:\s*(\d+(?:\.\d+)?)\s*hrs?", t)
    return a_float_seguro(m.group(1)) if m else None

# =========================================================
# CONSOLIDACIÓN
# =========================================================
def plantilla_cuenta():
    return {
        "paciente": None, "archivos": [],
        "cobrado": {"quirofano":0.0,"recuperacion":0.0,"hospitalizacion":0.0,"otro":0.0},
        "esperado": {"quirofano":0.0,"recuperacion":0.0,"hora_total_quirofano_documentada":None},
        "evidencias_cobro": [], "evidencias_esperado": [],
        "tiempo_postquirurgico": None,
    }

@st.cache_data(show_spinner=False)
def consolidar_por_cuenta(archivos_bytes: list):
    import io
    cuentas = {}
    for nombre, contenido in archivos_bytes:
        af = io.BytesIO(contenido)
        af.name = nombre
        texto = extraer_texto_pdf(af)
        if not texto:
            st.warning(f"⚠️ '{nombre}' no produjo texto; se omite.")
            continue
        cuenta  = extraer_cuenta(texto)
        paciente = extraer_paciente(texto)
        tipo    = detectar_tipo_documento(texto)
        if cuenta == "SIN_CUENTA":
            st.warning(f"⚠️ Sin número de cuenta (NCxxxxx) en '{nombre}'.")
        if tipo == "otro":
            st.info(f"ℹ️ '{nombre}' no coincide con ningún tipo conocido.")
        if cuenta not in cuentas:
            cuentas[cuenta] = plantilla_cuenta()
        if cuentas[cuenta]["paciente"] in (None,"No identificado") and paciente != "No identificado":
            cuentas[cuenta]["paciente"] = paciente
        cuentas[cuenta]["archivos"].append({"archivo":nombre,"tipo_documento":tipo})

        if tipo.startswith("estado_cuenta"):
            items = extraer_items_oxigeno_estado_cuenta(texto,nombre,tipo,cuenta)
            cuentas[cuenta]["evidencias_cobro"].extend(items)
            for item in items:
                area = item["area"] if item["area"] in cuentas[cuenta]["cobrado"] else "otro"
                cuentas[cuenta]["cobrado"][area] += item["cantidad"]
        elif tipo == "servicios_cirugia":
            esp, evs = extraer_evidencias_servicios_cirugia(texto,nombre,cuenta)
            cuentas[cuenta]["esperado"]["quirofano"]    += esp["quirofano"]
            cuentas[cuenta]["esperado"]["recuperacion"] += esp["recuperacion"]
            if cuentas[cuenta]["esperado"]["hora_total_quirofano_documentada"] is None:
                cuentas[cuenta]["esperado"]["hora_total_quirofano_documentada"] = esp["hora_total_quirofano_documentada"]
            cuentas[cuenta]["evidencias_esperado"].extend(evs)
        elif tipo == "nota_postquirurgica":
            cuentas[cuenta]["tiempo_postquirurgico"] = extraer_tiempo_postquirurgico(texto)
    return cuentas

# =========================================================
# EVALUACIÓN
# =========================================================
def evaluar(cobrado: float, esperado, tolerancia: float = 0.01):
    """Devuelve (estado, diff, clase_css)"""
    if esperado is None:
        return "sin regla", None, "gray"
    diff = round(cobrado - esperado, 2)
    if abs(diff) <= tolerancia:
        return "ok", diff, "ok"
    if diff < 0:
        return f"faltan {abs(diff):.2f} hrs", diff, "warn"
    return f"sobran {abs(diff):.2f} hrs", diff, "err"

# =========================================================
# COMPONENTES DE UI REUTILIZABLES
# =========================================================
def badge_html(texto: str, clase: str) -> str:
    return f'<span class="badge badge-{clase}">{texto}</span>'

def dot_html(clase: str) -> str:
    return f'<span class="dot dot-{clase}"></span>'

def barra_html(cobrado: float, esperado, clase: str) -> str:
    if not esperado or esperado == 0:
        pct = 100
    else:
        pct = min(round(cobrado / esperado * 100), 100)
    return (
        f'<div class="bar-wrap">'
        f'<div class="bar-fill bar-{clase}" style="width:{pct}%"></div>'
        f'</div>'
    )

def render_area(label: str, cobrado: float, esperado, tolerancia: float,
                nota: str = ""):
    estado, diff, clase = evaluar(cobrado, esperado, tolerancia)
    if esperado is not None:
        subtitulo = f"Cobrado {cobrado:.2f} de {esperado:.2f} esperadas"
    elif nota:
        subtitulo = nota
    else:
        subtitulo = f"Cobrado {cobrado:.2f} hrs — sin documento de referencia"

    st.markdown(
        f'<div style="display:flex;justify-content:space-between;'
        f'align-items:center;margin-top:10px;margin-bottom:2px">'
        f'<span style="font-size:13px;font-weight:500">{label}</span>'
        f'{badge_html(estado.upper() if estado=="ok" else estado, clase)}'
        f'</div>'
        f'{barra_html(cobrado, esperado, clase)}'
        f'<div style="font-size:11px;color:var(--color-text-secondary);'
        f'margin-bottom:6px">{subtitulo}</div>',
        unsafe_allow_html=True,
    )

def render_evidencia_cobro(items: list):
    if not items:
        st.markdown(
            '<p style="font-size:12px;color:var(--color-text-secondary)">'
            'No se encontraron líneas de oxígeno cobradas.</p>',
            unsafe_allow_html=True,
        )
        return
    filas = ""
    for it in items:
        filas += (
            f"<tr>"
            f"<td>{it['area'].capitalize()}</td>"
            f"<td class='mono'>{it['codigo']}</td>"
            f"<td>{it['descripcion']}</td>"
            f"<td style='text-align:right;font-weight:500'>{it['cantidad']:.3f}</td>"
            f"<td>{it['fecha']}</td>"
            f"<td class='mono'>{it['folio']}</td>"
            f"</tr>"
        )
    st.markdown(
        f'<table class="ev-table">'
        f'<thead><tr>'
        f'<th>Área</th><th>Código</th><th>Descripción</th>'
        f'<th style="text-align:right">Cant.</th><th>Fecha</th><th>Folio</th>'
        f'</tr></thead><tbody>{filas}</tbody></table>',
        unsafe_allow_html=True,
    )

def render_evidencia_esperada(items: list):
    if not items:
        st.markdown(
            '<p style="font-size:12px;color:var(--color-text-secondary)">'
            'No se encontró hoja de servicios de cirugía.</p>',
            unsafe_allow_html=True,
        )
        return
    filas = ""
    for it in items:
        filas += (
            f"<tr>"
            f"<td>{it['area'].capitalize()}</td>"
            f"<td style='text-align:right;font-weight:500'>{it['cantidad_esperada']:.2f}</td>"
            f"<td class='mono'>{it['linea_original']}</td>"
            f"</tr>"
        )
    st.markdown(
        f'<table class="ev-table">'
        f'<thead><tr>'
        f'<th>Área</th><th style="text-align:right">Hrs esperadas</th>'
        f'<th>Línea original</th>'
        f'</tr></thead><tbody>{filas}</tbody></table>',
        unsafe_allow_html=True,
    )

def estado_global_cuenta(data: dict, tolerancia: float):
    """Devuelve (estado_texto, clase_css) para la tarjeta de la cuenta."""
    _, _, clase_qx  = evaluar(data["cobrado"]["quirofano"],   data["esperado"]["quirofano"],   tolerancia)
    _, _, clase_rec = evaluar(data["cobrado"]["recuperacion"], data["esperado"]["recuperacion"], tolerancia)
    for clase in ("err", "warn"):
        if clase_qx == clase or clase_rec == clase:
            if clase == "err":
                return "Con diferencias", "err"
            return "Revisar", "warn"
    if data["esperado"]["quirofano"] == 0 and data["esperado"]["recuperacion"] == 0:
        return "Sin referencia", "gray"
    return "Sin diferencias", "ok"

ETIQUETAS_AREA = {
    "quirofano": "Quirófano",
    "recuperacion": "Recuperación",
    "hospitalizacion": "Hospitalización",
}

# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:
    st.markdown("### ⚙️ Configuración")
    tolerancia_ui = st.slider(
        "Tolerancia (hrs)",
        min_value=0.0, max_value=0.5, value=0.01, step=0.01,
        help="Diferencia máxima entre cobrado y esperado para marcar como OK.",
    )
    st.markdown("---")
    st.markdown(
        "**Tipos de documento reconocidos:**\n"
        "- Estado de cuenta (corte)\n"
        "- Servicios de cirugía\n"
        "- Nota post-quirúrgica"
    )

# =========================================================
# ENCABEZADO
# =========================================================
st.title("🏥 Auditor de Oxígeno por Cuenta")
st.markdown(
    "Sube los PDFs de una o varias cuentas. "
    "La app detecta diferencias entre el oxígeno **cobrado** "
    "(estados de cuenta) y el **esperado** (servicios de cirugía)."
)

# =========================================================
# UPLOAD
# =========================================================
archivos_subidos = st.file_uploader(
    "Selecciona los documentos PDF",
    type=["pdf"],
    accept_multiple_files=True,
)

if not archivos_subidos:
    st.info("Sube uno o más archivos PDF para comenzar el análisis.")
    st.stop()

archivos_bytes = [(f.name, f.read()) for f in archivos_subidos]

with st.spinner(f"Analizando {len(archivos_bytes)} archivo(s)…"):
    cuentas = consolidar_por_cuenta(archivos_bytes)

# =========================================================
# MÉTRICAS GLOBALES
# =========================================================
total_cuentas    = len(cuentas)
cuentas_con_diff = sum(
    1 for d in cuentas.values()
    if estado_global_cuenta(d, tolerancia_ui)[1] in ("err","warn")
)
total_hrs_qx   = sum(d["cobrado"]["quirofano"]    for d in cuentas.values())
total_hrs_rec  = sum(d["cobrado"]["recuperacion"] for d in cuentas.values())
total_hrs_hosp = sum(d["cobrado"]["hospitalizacion"] for d in cuentas.values())

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Cuentas analizadas",    total_cuentas)
col2.metric("Con diferencias",       cuentas_con_diff,
            delta=None if cuentas_con_diff == 0 else f"{cuentas_con_diff} cuenta(s)",
            delta_color="inverse")
col3.metric("Hrs QX cobradas",       f"{total_hrs_qx:.2f}")
col4.metric("Hrs recuperación",      f"{total_hrs_rec:.2f}")
col5.metric("Hrs hospitalización",   f"{total_hrs_hosp:.2f}")

st.divider()

# =========================================================
# LISTA DE CUENTAS CON SEMÁFORO
# =========================================================
st.subheader("Resumen por cuenta")

for cuenta, data in cuentas.items():
    estado_txt, clase = estado_global_cuenta(data, tolerancia_ui)
    paciente = data["paciente"] or "No identificado"
    n_archivos = len(data["archivos"])

    # ── Tarjeta de cuenta (siempre visible) ─────────────
    st.markdown(
        f'<div class="cuenta-card">'
        f'{dot_html(clase)}'
        f'<div style="flex:1">'
        f'<span style="font-weight:500;font-size:14px">{cuenta}</span>'
        f'<span style="color:var(--color-text-secondary);font-size:13px;'
        f'margin-left:10px">{paciente}</span>'
        f'</div>'
        f'<span style="font-size:11px;color:var(--color-text-tertiary);'
        f'margin-right:12px">{n_archivos} archivo(s)</span>'
        f'{badge_html(estado_txt, clase)}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Detalle expandible ───────────────────────────────
    with st.expander(f"Ver detalle → {cuenta}"):

        # 1. HALLAZGOS (lo primero que ve el auditor)
        st.markdown("#### Hallazgos")
        areas_auditadas = [
            ("quirofano",    "Quirófano"),
            ("recuperacion", "Recuperación"),
        ]
        hay_hallazgos = False
        for area_key, area_label in areas_auditadas:
            cob = round(data["cobrado"][area_key], 2)
            esp = data["esperado"][area_key]
            estado, diff, clase_area = evaluar(cob, esp, tolerancia_ui)
            if clase_area == "ok":
                msg = f"<b>{area_label}:</b> {cob:.2f} hrs cobradas = {esp:.2f} esperadas — sin diferencia."
                st.markdown(f'<div class="finding-box finding-ok">{msg}</div>', unsafe_allow_html=True)
            elif clase_area in ("warn", "err"):
                hay_hallazgos = True
                signo = "faltan" if diff < 0 else "sobran"
                msg = (
                    f"<b>{area_label}:</b> cobrado {cob:.2f} hrs, "
                    f"esperado {esp:.2f} hrs — "
                    f"<b>{signo} {abs(diff):.2f} hrs.</b>"
                )
                st.markdown(f'<div class="finding-box finding-{clase_area}">{msg}</div>', unsafe_allow_html=True)
            else:
                msg = f"<b>{area_label}:</b> sin documento de servicios de cirugía — no se puede comparar."
                st.markdown(f'<div class="finding-box finding-gray">{msg}</div>', unsafe_allow_html=True)

        hosp = round(data["cobrado"]["hospitalizacion"], 2)
        if hosp > 0:
            # Recopilar detalles de cada línea cobrada en hospitalización
            items_hosp = [
                it for it in data["evidencias_cobro"]
                if it["area"] == "hospitalizacion"
            ]
            detalle_lineas = ""
            for it in items_hosp:
                fecha_txt = it["fecha"] if it["fecha"] else "—"
                folio_txt = it["folio"] if it["folio"] else "—"
                detalle_lineas += (
                    f"<li style='margin:2px 0'>"
                    f"{it['cantidad']:.2f} hr — {fecha_txt} — folio {folio_txt}"
                    f"</li>"
                )
            detalle_html = f"<ul style='margin:6px 0 0 16px;padding:0'>{detalle_lineas}</ul>" if detalle_lineas else ""
            st.markdown(
                f'<div class="finding-box finding-gray">'
                f'<b>Hospitalización: {hosp:.2f} hr(s) cobradas</b> — no existe documento clínico '
                f'de referencia entre los archivos cargados (la hoja de servicios de cirugía '
                f'solo cubre quirófano y recuperación).<br>'
                f'<span style="font-size:12px">Requiere verificación manual: '
                f'confirmar con nota de enfermería u orden médica que justifique '
                f'el uso de oxígeno en cuarto.</span>'
                f'{detalle_html}'
                f'</div>',
                unsafe_allow_html=True,
            )

        if data["tiempo_postquirurgico"] is not None:
            st.markdown(
                f'<div class="finding-box finding-gray">'
                f'<b>Tiempo quirúrgico (nota post-qx):</b> '
                f'{data["tiempo_postquirurgico"]} hrs documentadas.</div>',
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)

        # 2. BARRAS COBRADO VS ESPERADO
        st.markdown("#### Cobrado vs esperado por área")
        render_area("Quirófano",   data["cobrado"]["quirofano"],    data["esperado"]["quirofano"],    tolerancia_ui)
        render_area("Recuperación",data["cobrado"]["recuperacion"], data["esperado"]["recuperacion"], tolerancia_ui)
        if hosp > 0:
            render_area(
                "Hospitalización", hosp, None, tolerancia_ui,
                nota="Verificar con nota de enfermería u orden médica",
            )

        st.markdown("<br>", unsafe_allow_html=True)

        # 3. EVIDENCIA EN DOS COLUMNAS
        col_esp, col_cob = st.columns(2)

        with col_esp:
            st.markdown("**Horas esperadas** *(servicios de cirugía)*")
            render_evidencia_esperada(data["evidencias_esperado"])

        with col_cob:
            st.markdown("**Horas cobradas** *(estados de cuenta)*")
            render_evidencia_cobro(data["evidencias_cobro"])

        # 4. ARCHIVOS PROCESADOS
        with st.expander("📄 Archivos procesados en esta cuenta"):
            for af in data["archivos"]:
                tipo_label = {
                    "servicios_cirugia": "Servicios de cirugía",
                    "nota_postquirurgica": "Nota post-quirúrgica",
                    "otro": "Tipo no reconocido",
                }.get(af["tipo_documento"],
                      af["tipo_documento"].replace("estado_cuenta_","Estado de cuenta — corte "))
                st.markdown(f"- `{af['archivo']}` → {tipo_label}")

st.divider()

# =========================================================
# DESCARGAS
# =========================================================
st.subheader("📥 Exportar datos")

# Construir DataFrame de resumen
filas = []
for cuenta, data in cuentas.items():
    cob_qx   = round(data["cobrado"]["quirofano"], 2)
    cob_rec  = round(data["cobrado"]["recuperacion"], 2)
    cob_hosp = round(data["cobrado"]["hospitalizacion"], 2)
    esp_qx   = round(data["esperado"]["quirofano"], 2)
    esp_rec  = round(data["esperado"]["recuperacion"], 2)
    estado_qx,  diff_qx,  _ = evaluar(cob_qx,  esp_qx,  tolerancia_ui)
    estado_rec, diff_rec, _ = evaluar(cob_rec, esp_rec, tolerancia_ui)
    estado_tot, diff_tot, _ = evaluar(cob_qx+cob_rec, esp_qx+esp_rec, tolerancia_ui)
    filas.append({
        "Cuenta": cuenta,
        "Paciente": data["paciente"],
        "Cobrado QX": cob_qx, "Esperado QX": esp_qx,
        "Diferencia QX": diff_qx, "Status QX": estado_qx,
        "Cobrado Recuperación": cob_rec, "Esperado Recuperación": esp_rec,
        "Diferencia Recuperación": diff_rec, "Status Recuperación": estado_rec,
        "Cobrado Hospitalización": cob_hosp,
        "Diferencia Total Quirúrgico": diff_tot,
        "Status Total Quirúrgico": estado_tot,
        "Hora total QX doc.": data["esperado"]["hora_total_quirofano_documentada"],
        "Tiempo Postquirúrgico": data["tiempo_postquirurgico"],
    })
df_resumen = pd.DataFrame(filas)

col_d1, col_d2, col_d3 = st.columns(3)

with col_d1:
    st.download_button(
        label="Resumen por cuenta (CSV)",
        data=df_resumen.to_csv(index=False).encode("utf-8"),
        file_name="resumen_oxigeno.csv", mime="text/csv",
    )

todas_cobro = [it for d in cuentas.values() for it in d["evidencias_cobro"]]
todas_esp   = [it for d in cuentas.values() for it in d["evidencias_esperado"]]

with col_d2:
    if todas_cobro:
        st.download_button(
            label="Evidencia cobrada (CSV)",
            data=pd.DataFrame(todas_cobro).to_csv(index=False).encode("utf-8"),
            file_name="evidencia_cobrada_oxigeno.csv", mime="text/csv",
        )
    else:
        st.caption("Sin evidencia cobrada para exportar.")

with col_d3:
    if todas_esp:
        st.download_button(
            label="Evidencia esperada (CSV)",
            data=pd.DataFrame(todas_esp).to_csv(index=False).encode("utf-8"),
            file_name="evidencia_esperada_oxigeno.csv", mime="text/csv",
        )
    else:
        st.caption("Sin evidencia esperada para exportar.")
