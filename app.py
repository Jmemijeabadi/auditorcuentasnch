import streamlit as st
import pdfplumber
import pandas as pd
import re
import unicodedata
from collections import defaultdict

st.set_page_config(
    page_title="Auditor de Cuentas Hospitalarias",
    layout="wide",
    page_icon="🏥"
)

st.title("🏥 Auditor de Oxígeno por Cuenta")
st.markdown(
    "Sube varios PDFs. La app agrupa por **cuenta**, consolida cobros de oxígeno "
    "y muestra la **evidencia exacta** encontrada."
)

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
    """
    Extrae texto de todas las páginas de un PDF.
    Hace seek(0) antes de abrir para que el stream sea reutilizable
    aunque Streamlit lo haya consumido parcialmente.
    Advierte si alguna página no tiene texto extraíble.
    """
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
                        f"⚠️ '{getattr(archivo_pdf, 'name', '?')}' "
                        f"— página {i} sin texto extraíble (¿PDF escaneado?)."
                    )
    except Exception as e:
        st.error(f"❌ Error al leer '{getattr(archivo_pdf, 'name', '?')}': {e}")
    return "\n".join(partes)

def extraer_cuenta(texto: str) -> str:
    # Busca patrón NCxxxxx en cualquier parte del texto
    match = re.search(r"\bNC\d{5,}\b", texto, re.IGNORECASE)
    if match:
        return match.group(0).upper()

    match = re.search(r"Cuenta[:\s]+(NC\d+)", texto, re.IGNORECASE)
    if match:
        return match.group(1).upper()

    return "SIN_CUENTA"

def extraer_paciente(texto: str) -> str:
    """
    CORRECCIÓN: después de capturar la línea del nombre, elimina
    todo lo que viene a partir de la fecha de nacimiento (YYYY-MM-DD
    o DD-MM-YYYY) y demás datos demográficos que pdfplumber
    concatena en la misma línea.
    """
    nombre_crudo = None

    # Formato estado de cuenta: línea bajo "Nombre Paciente … Fecha nacimiento:"
    m = re.search(
        r"Nombre Paciente\s+Fecha nacimiento:.*?\n(.+?)\n(?:Medico|Médico)",
        texto,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        nombre_crudo = compactar_espacios(m.group(1))

    # Formato nota / servicios: "Nombre: … Fecha de nacimiento:"
    if not nombre_crudo:
        m = re.search(
            r"Nombre:\s*(.+?)\s*Fecha de nacimiento:",
            texto,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            nombre_crudo = compactar_espacios(m.group(1))

    if not nombre_crudo:
        return "No identificado"

    # CORRECCIÓN Bug 3: recortar a partir de fecha de nacimiento en la cadena
    # cubre YYYY-MM-DD y DD-MM-YYYY que aparecen pegados al nombre
    nombre_limpio = re.split(r"\s+\d{2,4}[-/]\d{2}[-/]\d{2,4}", nombre_crudo)[0]
    # Por si quedó el año suelto al final: "NOMBRE 80 AÑOS Mujer"
    nombre_limpio = re.sub(r"\s+\d+\s+AÑO[S]?.*$", "", nombre_limpio, flags=re.IGNORECASE)
    return compactar_espacios(nombre_limpio)

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

    if "quirofano" in n:
        return "quirofano"
    if "recuperacion" in n:
        return "recuperacion"
    if "hospitalizacion" in n:
        return "hospitalizacion"
    if "caja" in n:
        return "caja"

    return "otro"

# =========================================================
# BLOQUES DEPARTAMENTO
# =========================================================
def extraer_bloques_departamento(texto: str):
    patron = re.compile(r"(?im)^Departamento:\s*(.*)$")
    matches = list(patron.finditer(texto))
    bloques = []

    if not matches:
        return bloques

    for i, match in enumerate(matches):
        encabezado = match.group(1).strip()
        inicio = match.end()
        fin = matches[i + 1].start() if i + 1 < len(matches) else len(texto)
        contenido = texto[inicio:fin]

        bloques.append({
            "encabezado": encabezado,
            "departamento": canonical_departamento(encabezado),
            "contenido": contenido,
        })

    return bloques

# =========================================================
# REGEX PRINCIPAL DE ÍTEMS
#
# CORRECCIÓN Bug 2: el bloque de fecha+folio ahora acepta que
# vengan pegados (23-03-2026SER200735) o separados por espacio.
# Se captura como un solo token "fecha_folio" y luego se separa.
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
    r"(?:\s+(?P<fecha_folio>\S+))?"   # ← captura "23-03-2026SER200735" o "23-03-2026"
    r"(?:\s+(?P<folio2>\S+))?$",      # ← captura folio separado si viene con espacio
    re.IGNORECASE,
)

# Códigos de producto que representan oxígeno por hora.
# Filtrar por código evita que mascarillas, circuitos y
# otros insumos con "oxigeno" en la descripción sean contados.
CODIGOS_OXIGENO = {"APR-0000003"}

def es_linea_oxigeno(descripcion: str, codigo: str = "") -> bool:
    """
    CORRECCIÓN Bug 1: primero valida el código de producto.
    Solo si el código pertenece a CODIGOS_OXIGENO (o si no se
    proporciona código) se evalúa la descripción.
    Esto excluye ítems como MASCARILLA PARA OXIGENO, CIRCUITO
    ANESTESIA, etc., que contienen la palabra pero no son horas.
    """
    if codigo and codigo.upper() not in CODIGOS_OXIGENO:
        return False
    return "oxigeno" in normalizar_texto(descripcion)

def _parsear_fecha_folio(fecha_folio_raw: str | None, folio2_raw: str | None):
    """
    CORRECCIÓN Bug 2: separa fecha y folio que pdfplumber fusiona
    sin espacio (ej. "23-03-2026SER200735").
    Devuelve (fecha_str, folio_str).
    """
    if not fecha_folio_raw:
        return "", ""

    # Si viene con espacio el folio ya está en folio2
    patron_fecha = re.compile(r"^\d{2}-\d{2}-\d{4}$")
    if patron_fecha.match(fecha_folio_raw):
        return fecha_folio_raw, folio2_raw or ""

    # Intenta separar los primeros 10 chars como fecha
    if len(fecha_folio_raw) > 10 and re.match(r"\d{2}-\d{2}-\d{4}", fecha_folio_raw):
        fecha = fecha_folio_raw[:10]
        folio = fecha_folio_raw[10:]
        return fecha, folio

    # No es una fecha: tratar todo como folio
    return "", fecha_folio_raw

# =========================================================
# EXTRACCIÓN FINA DE ÍTEMS DE OXÍGENO EN ESTADOS DE CUENTA
# =========================================================
def extraer_items_oxigeno_estado_cuenta(
    texto: str, nombre_archivo: str, tipo_doc: str, cuenta: str
):
    items = []
    bloques = extraer_bloques_departamento(texto)
    sin_match_oxigeno = []  # para avisos de líneas sospechosas no capturadas

    for bloque in bloques:
        depto = bloque["departamento"]
        if depto == "caja":
            continue

        for linea in bloque["contenido"].splitlines():
            linea_limpia = compactar_espacios(linea)
            if not linea_limpia:
                continue

            m = ITEM_RE.match(linea_limpia)

            # Aviso de depuración: línea con "oxigeno" que no matcheó el regex
            if not m:
                if "oxigeno" in normalizar_texto(linea_limpia):
                    sin_match_oxigeno.append(linea_limpia)
                continue

            codigo = m.group("codigo")
            descripcion = m.group("descripcion")

            if not es_linea_oxigeno(descripcion, codigo):
                continue

            fecha, folio = _parsear_fecha_folio(
                m.group("fecha_folio"), m.group("folio2")
            )

            items.append({
                "cuenta": cuenta,
                "archivo": nombre_archivo,
                "tipo_documento": tipo_doc,
                "area": depto,
                "codigo": codigo,
                "descripcion": descripcion,
                "cantidad": a_float_seguro(m.group("cantidad")),
                "precio_unitario": a_float_seguro(m.group("precio")),
                "subtotal": a_float_seguro(m.group("subtotal")),
                "fecha": fecha,
                "folio": folio,
                "linea_original": linea_limpia,
            })

    if sin_match_oxigeno:
        st.warning(
            f"⚠️ '{nombre_archivo}': {len(sin_match_oxigeno)} línea(s) con "
            f"'oxígeno' no pudieron parsearse con ITEM_RE:\n"
            + "\n".join(f"  • {l}" for l in sin_match_oxigeno)
        )

    return items

# =========================================================
# EXTRACCIÓN FINA DESDE SERVICIOS DE CIRUGÍA
# =========================================================
def extraer_evidencias_servicios_cirugia(
    texto: str, nombre_archivo: str, cuenta: str
):
    evidencias = []
    hora_total_quirofano = None

    # pdfplumber fusiona las 3 columnas en una misma línea de texto;
    # re.search encuentra el patrón donde sea dentro de la línea.
    for linea in texto.splitlines():
        original = compactar_espacios(linea)
        if not original:
            continue

        n = normalizar_texto(original)

        # Hora total de quirófano
        m_total = re.search(
            r"hora total de quirofano:\s*(\d+(?:\.\d+)?)\s*hrs?", n
        )
        if m_total:
            hora_total_quirofano = a_float_seguro(m_total.group(1))

        # Oxígeno en quirófano (columna ANESTESIA)
        m_qx = re.search(r"oxigeno x hr\s+(\d+(?:\.\d+)?)\s*hrs?", n)
        if m_qx:
            evidencias.append({
                "cuenta": cuenta,
                "archivo": nombre_archivo,
                "tipo_documento": "servicios_cirugia",
                "area": "quirofano",
                "cantidad_esperada": a_float_seguro(m_qx.group(1)),
                "linea_original": original,
            })

        # Oxígeno en recuperación (columna RECUPERACIÓN)
        m_rec = re.search(r"oxigeno recuperacion\s+(\d+(?:\.\d+)?)\s*hrs?", n)
        if m_rec:
            evidencias.append({
                "cuenta": cuenta,
                "archivo": nombre_archivo,
                "tipo_documento": "servicios_cirugia",
                "area": "recuperacion",
                "cantidad_esperada": a_float_seguro(m_rec.group(1)),
                "linea_original": original,
            })

    esperado = {
        "quirofano": 0.0,
        "recuperacion": 0.0,
        "hora_total_quirofano_documentada": hora_total_quirofano,
    }
    for ev in evidencias:
        esperado[ev["area"]] += ev["cantidad_esperada"]

    return esperado, evidencias

def extraer_tiempo_postquirurgico(texto: str):
    t = normalizar_texto(texto)
    t = compactar_espacios(t)
    # Acepta "2hrs" sin espacio y "2 hrs" con espacio
    m = re.search(r"tiempo quirurgico:\s*(\d+(?:\.\d+)?)\s*hrs?", t)
    if m:
        return a_float_seguro(m.group(1))
    return None

# =========================================================
# CONSOLIDACIÓN
# =========================================================
def plantilla_cuenta():
    return {
        "paciente": None,
        "archivos": [],
        "cobrado": {
            "quirofano": 0.0,
            "recuperacion": 0.0,
            "hospitalizacion": 0.0,
            "otro": 0.0,
        },
        "esperado": {
            "quirofano": 0.0,
            "recuperacion": 0.0,
            "hora_total_quirofano_documentada": None,
        },
        "evidencias_cobro": [],
        "evidencias_esperado": [],
        "tiempo_postquirurgico": None,
    }

@st.cache_data(show_spinner=False)
def consolidar_por_cuenta(archivos_bytes: list[tuple[str, bytes]]):
    """
    CORRECCIÓN: recibe lista de (nombre, bytes) en vez de file objects,
    lo que permite cachear con @st.cache_data y evita re-procesar
    los PDFs en cada interacción de la UI.
    """
    import io

    cuentas: dict = {}

    for nombre, contenido in archivos_bytes:
        archivo_pdf = io.BytesIO(contenido)
        archivo_pdf.name = nombre

        texto = extraer_texto_pdf(archivo_pdf)
        if not texto:
            st.warning(f"⚠️ '{nombre}' no produjo texto; se omite.")
            continue

        cuenta = extraer_cuenta(texto)
        paciente = extraer_paciente(texto)
        tipo = detectar_tipo_documento(texto)

        # Aviso cuando no se puede identificar la cuenta
        if cuenta == "SIN_CUENTA":
            st.warning(
                f"⚠️ No se encontró número de cuenta (NCxxxxx) en '{nombre}'. "
                f"Los datos se agruparán bajo 'SIN_CUENTA'."
            )

        # Aviso cuando el tipo de documento no se reconoce
        if tipo == "otro":
            st.info(
                f"ℹ️ '{nombre}' no coincide con ningún tipo conocido "
                f"(estado de cuenta / servicios de cirugía / nota post-quirúrgica). "
                f"Se registra pero no aporta datos de oxígeno."
            )

        if cuenta not in cuentas:
            cuentas[cuenta] = plantilla_cuenta()

        if (
            cuentas[cuenta]["paciente"] in (None, "No identificado")
            and paciente != "No identificado"
        ):
            cuentas[cuenta]["paciente"] = paciente

        cuentas[cuenta]["archivos"].append(
            {"archivo": nombre, "tipo_documento": tipo}
        )

        if tipo.startswith("estado_cuenta"):
            items = extraer_items_oxigeno_estado_cuenta(
                texto=texto,
                nombre_archivo=nombre,
                tipo_doc=tipo,
                cuenta=cuenta,
            )
            cuentas[cuenta]["evidencias_cobro"].extend(items)

            for item in items:
                area = item["area"]
                if area not in cuentas[cuenta]["cobrado"]:
                    area = "otro"
                cuentas[cuenta]["cobrado"][area] += item["cantidad"]

        elif tipo == "servicios_cirugia":
            esperado_doc, evidencias_doc = extraer_evidencias_servicios_cirugia(
                texto=texto,
                nombre_archivo=nombre,
                cuenta=cuenta,
            )
            cuentas[cuenta]["esperado"]["quirofano"] += esperado_doc["quirofano"]
            cuentas[cuenta]["esperado"]["recuperacion"] += esperado_doc["recuperacion"]

            if cuentas[cuenta]["esperado"]["hora_total_quirofano_documentada"] is None:
                cuentas[cuenta]["esperado"][
                    "hora_total_quirofano_documentada"
                ] = esperado_doc["hora_total_quirofano_documentada"]

            cuentas[cuenta]["evidencias_esperado"].extend(evidencias_doc)

        elif tipo == "nota_postquirurgica":
            cuentas[cuenta]["tiempo_postquirurgico"] = extraer_tiempo_postquirurgico(
                texto
            )

    return cuentas

# =========================================================
# EVALUACIÓN
# =========================================================
def evaluar_diferencia(cobrado: float, esperado, tolerancia: float = 0.01):
    if esperado is None:
        return "SIN REGLA", None

    diff = round(cobrado - esperado, 2)

    if abs(diff) <= tolerancia:
        return "✅ OK", diff
    if diff < 0:
        return f"⚠️ FALTAN {abs(diff):.2f} HRS", diff
    return f"🔴 SOBRAN {abs(diff):.2f} HRS", diff

def construir_resumen(cuentas: dict) -> pd.DataFrame:
    filas = []

    for cuenta, data in cuentas.items():
        cob_qx   = round(data["cobrado"]["quirofano"], 2)
        cob_rec  = round(data["cobrado"]["recuperacion"], 2)
        cob_hosp = round(data["cobrado"]["hospitalizacion"], 2)

        esp_qx  = round(data["esperado"]["quirofano"], 2)
        esp_rec = round(data["esperado"]["recuperacion"], 2)

        esp_total_qx = round(esp_qx + esp_rec, 2)
        cob_total_qx = round(cob_qx + cob_rec, 2)
        cob_total    = round(cob_qx + cob_rec + cob_hosp, 2)

        status_qx,    diff_qx    = evaluar_diferencia(cob_qx,   esp_qx)
        status_rec,   diff_rec   = evaluar_diferencia(cob_rec,  esp_rec)
        status_total, diff_total = evaluar_diferencia(cob_total_qx, esp_total_qx)

        filas.append({
            "Cuenta":                      cuenta,
            "Paciente":                    data["paciente"],
            "Archivos":                    len(data["archivos"]),
            "Esperado QX":                 esp_qx,
            "Cobrado QX":                  cob_qx,
            "Dif. QX":                     diff_qx,
            "Status QX":                   status_qx,
            "Esperado Recuperación":       esp_rec,
            "Cobrado Recuperación":        cob_rec,
            "Dif. Recuperación":           diff_rec,
            "Status Recuperación":         status_rec,
            "Cobrado Hospitalización":     cob_hosp,
            "Esperado Total Quirúrgico":   esp_total_qx,
            "Cobrado Total Quirúrgico":    cob_total_qx,
            "Dif. Total Quirúrgico":       diff_total,
            "Status Total Quirúrgico":     status_total,
            "Cobrado Total Cuenta":        cob_total,
            "Hora total QX doc.":          data["esperado"]["hora_total_quirofano_documentada"],
            "Tiempo Postquirúrgico":       data["tiempo_postquirurgico"],
        })

    return pd.DataFrame(filas)

def df_evidencias_cobro(cuenta_data: dict) -> pd.DataFrame:
    if not cuenta_data["evidencias_cobro"]:
        return pd.DataFrame(
            columns=[
                "archivo", "tipo_documento", "area", "codigo", "descripcion",
                "cantidad", "fecha", "folio", "linea_original",
            ]
        )
    return pd.DataFrame(cuenta_data["evidencias_cobro"])

def df_evidencias_esperado(cuenta_data: dict) -> pd.DataFrame:
    if not cuenta_data["evidencias_esperado"]:
        return pd.DataFrame(
            columns=[
                "archivo", "tipo_documento", "area",
                "cantidad_esperada", "linea_original",
            ]
        )
    return pd.DataFrame(cuenta_data["evidencias_esperado"])

# =========================================================
# UI
# =========================================================
tolerancia_ui = st.sidebar.slider(
    "Tolerancia (hrs)",
    min_value=0.0,
    max_value=0.5,
    value=0.01,
    step=0.01,
    help="Diferencia máxima entre cobrado y esperado para considerar el cobro como correcto.",
)

archivos_subidos = st.file_uploader(
    "Selecciona los documentos PDF",
    type=["pdf"],
    accept_multiple_files=True,
)

if archivos_subidos:
    # Convertir a lista serializable para que @st.cache_data funcione
    archivos_bytes = [(f.name, f.read()) for f in archivos_subidos]

    with st.spinner(f"Analizando {len(archivos_bytes)} archivo(s)..."):
        cuentas = consolidar_por_cuenta(archivos_bytes)
        df_resumen = construir_resumen(cuentas)

    # Re-evaluar diferencias con la tolerancia elegida en la UI
    for col_status, col_cob, col_esp in [
        ("Status QX",              "Cobrado QX",              "Esperado QX"),
        ("Status Recuperación",    "Cobrado Recuperación",    "Esperado Recuperación"),
        ("Status Total Quirúrgico","Cobrado Total Quirúrgico","Esperado Total Quirúrgico"),
    ]:
        df_resumen[col_status] = df_resumen.apply(
            lambda r: evaluar_diferencia(r[col_cob], r[col_esp], tolerancia_ui)[0],
            axis=1,
        )

    st.subheader("Resumen por cuenta")
    st.dataframe(df_resumen, use_container_width=True, hide_index=True)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Cuentas analizadas",              len(df_resumen))
    col2.metric("Oxígeno QX cobrado",              f"{df_resumen['Cobrado QX'].sum():.2f} hrs")
    col3.metric("Oxígeno recuperación cobrado",    f"{df_resumen['Cobrado Recuperación'].sum():.2f} hrs")
    col4.metric("Oxígeno hospitalización cobrado", f"{df_resumen['Cobrado Hospitalización'].sum():.2f} hrs")

    # Alerta si alguna cuenta no pudo identificarse
    sin_cuenta = df_resumen[df_resumen["Cuenta"] == "SIN_CUENTA"]
    if not sin_cuenta.empty:
        st.error(
            f"🔴 {len(sin_cuenta)} cuenta(s) sin número identificado (SIN_CUENTA). "
            f"Revisa que los PDFs contengan el patrón NCxxxxx."
        )

    st.divider()
    st.subheader("Detalle fino por cuenta")

    for cuenta in df_resumen["Cuenta"].tolist():
        data = cuentas[cuenta]
        row  = df_resumen[df_resumen["Cuenta"] == cuenta].iloc[0]

        with st.expander(f"Cuenta {cuenta} · {data['paciente']}"):
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Status total quirúrgico",  row["Status Total Quirúrgico"])
            col_b.metric("Cobrado total quirúrgico",  f"{row['Cobrado Total Quirúrgico']:.2f} hrs")
            col_c.metric("Cobrado hospitalización",   f"{row['Cobrado Hospitalización']:.2f} hrs")

            if data["tiempo_postquirurgico"] is not None:
                st.caption(
                    f"⏱️ Tiempo quirúrgico (nota post-qx): "
                    f"{data['tiempo_postquirurgico']} hrs"
                )

            st.markdown("**Conciliación por área**")
            conciliacion = pd.DataFrame([
                {
                    "Área": "Quirófano",
                    "Esperado": row["Esperado QX"],
                    "Cobrado":  row["Cobrado QX"],
                    "Diferencia": row["Dif. QX"],
                    "Status":   row["Status QX"],
                },
                {
                    "Área": "Recuperación",
                    "Esperado": row["Esperado Recuperación"],
                    "Cobrado":  row["Cobrado Recuperación"],
                    "Diferencia": row["Dif. Recuperación"],
                    "Status":   row["Status Recuperación"],
                },
                {
                    "Área": "Hospitalización",
                    "Esperado": None,
                    "Cobrado":  row["Cobrado Hospitalización"],
                    "Diferencia": None,
                    "Status":   "SIN REGLA",
                },
                {
                    "Área": "Total Quirúrgico",
                    "Esperado": row["Esperado Total Quirúrgico"],
                    "Cobrado":  row["Cobrado Total Quirúrgico"],
                    "Diferencia": row["Dif. Total Quirúrgico"],
                    "Status":   row["Status Total Quirúrgico"],
                },
            ])
            st.dataframe(conciliacion, use_container_width=True, hide_index=True)

            st.markdown("**Evidencia esperada (Servicios de cirugía)**")
            df_esp = df_evidencias_esperado(data)
            if not df_esp.empty:
                st.dataframe(
                    df_esp[["archivo", "tipo_documento", "area",
                             "cantidad_esperada", "linea_original"]],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No se encontró hoja de servicios de cirugía para esta cuenta.")

            st.markdown("**Evidencia cobrada (Estados de cuenta)**")
            df_cob = df_evidencias_cobro(data)
            if not df_cob.empty:
                st.dataframe(
                    df_cob[[
                        "archivo", "tipo_documento", "area", "codigo",
                        "descripcion", "cantidad", "fecha", "folio",
                        "linea_original",
                    ]],
                    use_container_width=True,
                    hide_index=True,
                )

                st.markdown("**Totales de evidencia cobrada por área**")
                resumen_ev = (
                    df_cob.groupby("area", as_index=False)["cantidad"]
                    .sum()
                    .rename(columns={"cantidad": "horas_detectadas"})
                )
                st.dataframe(resumen_ev, use_container_width=True, hide_index=True)
            else:
                st.info(
                    "No se encontraron líneas cobradas de oxígeno "
                    "en los estados de cuenta."
                )

    st.divider()

    # ── Descargas ──────────────────────────────────────────
    csv_resumen = df_resumen.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Descargar resumen",
        data=csv_resumen,
        file_name="reporte_resumen_oxigeno.csv",
        mime="text/csv",
    )

    todas_cobro    = []
    todas_esperado = []

    for data in cuentas.values():
        todas_cobro.extend(data["evidencias_cobro"])
        todas_esperado.extend(data["evidencias_esperado"])

    if todas_cobro:
        csv_cobro = pd.DataFrame(todas_cobro).to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Descargar evidencia cobrada",
            data=csv_cobro,
            file_name="reporte_evidencia_cobrada_oxigeno.csv",
            mime="text/csv",
        )
    else:
        st.info("No hay evidencia cobrada de oxígeno en los archivos subidos.")

    if todas_esperado:
        csv_esp = pd.DataFrame(todas_esperado).to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Descargar evidencia esperada",
            data=csv_esp,
            file_name="reporte_evidencia_esperada_oxigeno.csv",
            mime="text/csv",
        )
    else:
        st.info("No hay evidencia esperada de oxígeno en los archivos subidos.")
