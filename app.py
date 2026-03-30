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

def extraer_texto_pdf(archivo_pdf):
    partes = []
    with pdfplumber.open(archivo_pdf) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text()
            if texto:
                partes.append(texto)
    return "\n".join(partes)

def extraer_cuenta(texto: str) -> str:
    match = re.search(r"\bNC\d{5,}\b", texto, re.IGNORECASE)
    if match:
        return match.group(0).upper()

    match = re.search(r"Cuenta[:\s]+(NC\d+)", texto, re.IGNORECASE)
    if match:
        return match.group(1).upper()

    return "SIN_CUENTA"

def extraer_paciente(texto: str) -> str:
    match = re.search(
        r"Nombre Paciente\s+Fecha nacimiento:.*?\n(.+?)\nMedico",
        texto,
        re.IGNORECASE | re.DOTALL
    )
    if match:
        return compactar_espacios(match.group(1))

    match = re.search(
        r"Nombre:\s*(.+?)\s*Fecha de nacimiento:",
        texto,
        re.IGNORECASE | re.DOTALL
    )
    if match:
        return compactar_espacios(match.group(1))

    return "No identificado"

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
            "contenido": contenido
        })

    return bloques

# =========================================================
# EXTRACCION FINA DE ITEMS DE OXIGENO EN ESTADOS DE CUENTA
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
    r"(?:\s+(?P<fecha>\d{2}-\d{2}-\d{4}))?"
    r"(?:\s+(?P<folio>\S+))?$",
    re.IGNORECASE
)

def es_linea_oxigeno(descripcion: str) -> bool:
    d = normalizar_texto(descripcion)
    return "oxigeno" in d

def extraer_items_oxigeno_estado_cuenta(texto: str, nombre_archivo: str, tipo_doc: str, cuenta: str):
    items = []
    bloques = extraer_bloques_departamento(texto)

    for bloque in bloques:
        depto = bloque["departamento"]
        if depto == "caja":
            continue

        for linea in bloque["contenido"].splitlines():
            linea_limpia = compactar_espacios(linea)
            if not linea_limpia:
                continue

            m = ITEM_RE.match(linea_limpia)
            if not m:
                continue

            descripcion = m.group("descripcion")
            if not es_linea_oxigeno(descripcion):
                continue

            items.append({
                "cuenta": cuenta,
                "archivo": nombre_archivo,
                "tipo_documento": tipo_doc,
                "area": depto,
                "codigo": m.group("codigo"),
                "descripcion": descripcion,
                "cantidad": a_float_seguro(m.group("cantidad")),
                "precio_unitario": a_float_seguro(m.group("precio")),
                "subtotal": a_float_seguro(m.group("subtotal")),
                "fecha": m.group("fecha") if m.group("fecha") else "",
                "folio": m.group("folio") if m.group("folio") else "",
                "linea_original": linea_limpia
            })

    return items

# =========================================================
# EXTRACCION FINA DESDE SERVICIOS DE CIRUGIA
# =========================================================
def extraer_evidencias_servicios_cirugia(texto: str, nombre_archivo: str, cuenta: str):
    evidencias = []
    hora_total_quirofano = None

    for linea in texto.splitlines():
        original = compactar_espacios(linea)
        if not original:
            continue

        n = normalizar_texto(original)

        # Hora total de quirofano
        m_total = re.search(r"hora total de quirofano:\s*(\d+(?:\.\d+)?)\s*hrs?", n, re.IGNORECASE)
        if m_total:
            hora_total_quirofano = a_float_seguro(m_total.group(1))

        # Oxigeno en quirofano
        m_qx = re.search(r"oxigeno x hr\s+(\d+(?:\.\d+)?)\s*hrs?", n, re.IGNORECASE)
        if m_qx:
            evidencias.append({
                "cuenta": cuenta,
                "archivo": nombre_archivo,
                "tipo_documento": "servicios_cirugia",
                "area": "quirofano",
                "cantidad_esperada": a_float_seguro(m_qx.group(1)),
                "linea_original": original
            })

        # Oxigeno en recuperacion
        m_rec = re.search(r"oxigeno recuperacion\s+(\d+(?:\.\d+)?)\s*hrs?", n, re.IGNORECASE)
        if m_rec:
            evidencias.append({
                "cuenta": cuenta,
                "archivo": nombre_archivo,
                "tipo_documento": "servicios_cirugia",
                "area": "recuperacion",
                "cantidad_esperada": a_float_seguro(m_rec.group(1)),
                "linea_original": original
            })

    esperado = {
        "quirofano": 0.0,
        "recuperacion": 0.0,
        "hora_total_quirofano_documentada": hora_total_quirofano
    }

    for ev in evidencias:
        esperado[ev["area"]] += ev["cantidad_esperada"]

    return esperado, evidencias

def extraer_tiempo_postquirurgico(texto: str):
    t = normalizar_texto(texto)
    t = compactar_espacios(t)

    m = re.search(r"tiempo quirurgico:\s*(\d+(?:\.\d+)?)\s*hrs?", t, re.IGNORECASE)
    if m:
        return a_float_seguro(m.group(1))
    return None

# =========================================================
# CONSOLIDACION
# =========================================================
def plantilla_cuenta():
    return {
        "paciente": None,
        "archivos": [],
        "cobrado": {
            "quirofano": 0.0,
            "recuperacion": 0.0,
            "hospitalizacion": 0.0,
            "otro": 0.0
        },
        "esperado": {
            "quirofano": 0.0,
            "recuperacion": 0.0,
            "hora_total_quirofano_documentada": None
        },
        "evidencias_cobro": [],
        "evidencias_esperado": [],
        "tiempo_postquirurgico": None
    }

def consolidar_por_cuenta(archivos_subidos):
    cuentas = defaultdict(plantilla_cuenta)

    for archivo in archivos_subidos:
        texto = extraer_texto_pdf(archivo)
        cuenta = extraer_cuenta(texto)
        paciente = extraer_paciente(texto)
        tipo = detectar_tipo_documento(texto)

        if cuentas[cuenta]["paciente"] in (None, "No identificado") and paciente != "No identificado":
            cuentas[cuenta]["paciente"] = paciente

        cuentas[cuenta]["archivos"].append({
            "archivo": archivo.name,
            "tipo_documento": tipo
        })

        if tipo.startswith("estado_cuenta"):
            items = extraer_items_oxigeno_estado_cuenta(
                texto=texto,
                nombre_archivo=archivo.name,
                tipo_doc=tipo,
                cuenta=cuenta
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
                nombre_archivo=archivo.name,
                cuenta=cuenta
            )
            cuentas[cuenta]["esperado"]["quirofano"] += esperado_doc["quirofano"]
            cuentas[cuenta]["esperado"]["recuperacion"] += esperado_doc["recuperacion"]

            if cuentas[cuenta]["esperado"]["hora_total_quirofano_documentada"] is None:
                cuentas[cuenta]["esperado"]["hora_total_quirofano_documentada"] = esperado_doc["hora_total_quirofano_documentada"]

            cuentas[cuenta]["evidencias_esperado"].extend(evidencias_doc)

        elif tipo == "nota_postquirurgica":
            cuentas[cuenta]["tiempo_postquirurgico"] = extraer_tiempo_postquirurgico(texto)

    return cuentas

# =========================================================
# EVALUACION
# =========================================================
def evaluar_diferencia(cobrado: float, esperado: float, tolerancia: float = 0.01):
    diff = round(cobrado - esperado, 2)

    if esperado is None:
        return "SIN REGLA", None

    if abs(diff) <= tolerancia:
        return "OK", diff
    if diff < 0:
        return f"FALTAN {abs(diff):.2f} HRS", diff
    return f"SOBRAN {abs(diff):.2f} HRS", diff

def construir_resumen(cuentas):
    filas = []

    for cuenta, data in cuentas.items():
        cob_qx = round(data["cobrado"]["quirofano"], 2)
        cob_rec = round(data["cobrado"]["recuperacion"], 2)
        cob_hosp = round(data["cobrado"]["hospitalizacion"], 2)

        esp_qx = round(data["esperado"]["quirofano"], 2)
        esp_rec = round(data["esperado"]["recuperacion"], 2)
        esp_total_qx = round(esp_qx + esp_rec, 2)
        cob_total_qx = round(cob_qx + cob_rec, 2)
        cob_total_cuenta = round(cob_qx + cob_rec + cob_hosp, 2)

        status_qx, diff_qx = evaluar_diferencia(cob_qx, esp_qx)
        status_rec, diff_rec = evaluar_diferencia(cob_rec, esp_rec)
        status_total_qx, diff_total_qx = evaluar_diferencia(cob_total_qx, esp_total_qx)

        filas.append({
            "Cuenta": cuenta,
            "Paciente": data["paciente"],
            "Archivos": len(data["archivos"]),
            "Esperado QX": esp_qx,
            "Cobrado QX": cob_qx,
            "Dif. QX": diff_qx,
            "Status QX": status_qx,
            "Esperado Recuperación": esp_rec,
            "Cobrado Recuperación": cob_rec,
            "Dif. Recuperación": diff_rec,
            "Status Recuperación": status_rec,
            "Cobrado Hospitalización": cob_hosp,
            "Esperado Total Quirúrgico": esp_total_qx,
            "Cobrado Total Quirúrgico": cob_total_qx,
            "Dif. Total Quirúrgico": diff_total_qx,
            "Status Total Quirúrgico": status_total_qx,
            "Cobrado Total Cuenta": cob_total_cuenta,
            "Hora total QX doc.": data["esperado"]["hora_total_quirofano_documentada"],
            "Tiempo Postquirúrgico": data["tiempo_postquirurgico"]
        })

    return pd.DataFrame(filas)

def df_evidencias_cobro(cuenta_data):
    if not cuenta_data["evidencias_cobro"]:
        return pd.DataFrame(columns=[
            "archivo", "tipo_documento", "area", "codigo", "descripcion",
            "cantidad", "fecha", "folio", "linea_original"
        ])
    return pd.DataFrame(cuenta_data["evidencias_cobro"])

def df_evidencias_esperado(cuenta_data):
    if not cuenta_data["evidencias_esperado"]:
        return pd.DataFrame(columns=[
            "archivo", "tipo_documento", "area", "cantidad_esperada", "linea_original"
        ])
    return pd.DataFrame(cuenta_data["evidencias_esperado"])

# =========================================================
# UI
# =========================================================
archivos_subidos = st.file_uploader(
    "Selecciona los documentos PDF",
    type=["pdf"],
    accept_multiple_files=True
)

if archivos_subidos:
    with st.spinner(f"Analizando {len(archivos_subidos)} archivo(s)..."):
        cuentas = consolidar_por_cuenta(archivos_subidos)
        df_resumen = construir_resumen(cuentas)

    st.subheader("Resumen por cuenta")
    st.dataframe(df_resumen, use_container_width=True, hide_index=True)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Cuentas analizadas", len(df_resumen))
    col2.metric("Oxígeno QX cobrado", f"{df_resumen['Cobrado QX'].sum():.2f} hrs")
    col3.metric("Oxígeno recuperación cobrado", f"{df_resumen['Cobrado Recuperación'].sum():.2f} hrs")
    col4.metric("Oxígeno hospitalización cobrado", f"{df_resumen['Cobrado Hospitalización'].sum():.2f} hrs")

    st.divider()
    st.subheader("Detalle fino por cuenta")

    for cuenta in df_resumen["Cuenta"].tolist():
        data = cuentas[cuenta]
        row = df_resumen[df_resumen["Cuenta"] == cuenta].iloc[0]

        with st.expander(f"Cuenta {cuenta} · {data['paciente']}"):
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Status total quirúrgico", row["Status Total Quirúrgico"])
            col_b.metric("Cobrado total quirúrgico", f"{row['Cobrado Total Quirúrgico']:.2f} hrs")
            col_c.metric("Cobrado hospitalización", f"{row['Cobrado Hospitalización']:.2f} hrs")

            st.markdown("**Conciliación por área**")
            conciliacion = pd.DataFrame([
                {
                    "Área": "Quirófano",
                    "Esperado": row["Esperado QX"],
                    "Cobrado": row["Cobrado QX"],
                    "Diferencia": row["Dif. QX"],
                    "Status": row["Status QX"]
                },
                {
                    "Área": "Recuperación",
                    "Esperado": row["Esperado Recuperación"],
                    "Cobrado": row["Cobrado Recuperación"],
                    "Diferencia": row["Dif. Recuperación"],
                    "Status": row["Status Recuperación"]
                },
                {
                    "Área": "Hospitalización",
                    "Esperado": None,
                    "Cobrado": row["Cobrado Hospitalización"],
                    "Diferencia": None,
                    "Status": "SIN REGLA"
                },
                {
                    "Área": "Total Quirúrgico",
                    "Esperado": row["Esperado Total Quirúrgico"],
                    "Cobrado": row["Cobrado Total Quirúrgico"],
                    "Diferencia": row["Dif. Total Quirúrgico"],
                    "Status": row["Status Total Quirúrgico"]
                }
            ])
            st.dataframe(conciliacion, use_container_width=True, hide_index=True)

            st.markdown("**Evidencia esperada (Servicios de cirugía)**")
            df_esp = df_evidencias_esperado(data)
            st.dataframe(
                df_esp[["archivo", "tipo_documento", "area", "cantidad_esperada", "linea_original"]],
                use_container_width=True,
                hide_index=True
            )

            st.markdown("**Evidencia cobrada (Estados de cuenta)**")
            df_cob = df_evidencias_cobro(data)
            if not df_cob.empty:
                st.dataframe(
                    df_cob[[
                        "archivo", "tipo_documento", "area", "codigo", "descripcion",
                        "cantidad", "fecha", "folio", "linea_original"
                    ]],
                    use_container_width=True,
                    hide_index=True
                )

                st.markdown("**Totales de evidencia cobrada por área**")
                resumen_evidencia = (
                    df_cob.groupby("area", as_index=False)["cantidad"]
                    .sum()
                    .rename(columns={"cantidad": "horas_detectadas"})
                )
                st.dataframe(resumen_evidencia, use_container_width=True, hide_index=True)
            else:
                st.info("No se encontraron líneas cobradas de oxígeno en los estados de cuenta.")

    st.divider()

    csv_resumen = df_resumen.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Descargar resumen",
        data=csv_resumen,
        file_name="reporte_resumen_oxigeno.csv",
        mime="text/csv"
    )

    todas_cobro = []
    todas_esperado = []

    for cuenta, data in cuentas.items():
        todas_cobro.extend(data["evidencias_cobro"])
        todas_esperado.extend(data["evidencias_esperado"])

    df_cobro_all = pd.DataFrame(todas_cobro) if todas_cobro else pd.DataFrame()
    df_esp_all = pd.DataFrame(todas_esperado) if todas_esperado else pd.DataFrame()

    if not df_cobro_all.empty:
        csv_cobro = df_cobro_all.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Descargar evidencia cobrada",
            data=csv_cobro,
            file_name="reporte_evidencia_cobrada_oxigeno.csv",
            mime="text/csv"
        )

    if not df_esp_all.empty:
        csv_esp = df_esp_all.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Descargar evidencia esperada",
            data=csv_esp,
            file_name="reporte_evidencia_esperada_oxigeno.csv",
            mime="text/csv"
        )
