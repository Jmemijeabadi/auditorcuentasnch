import streamlit as st
import pdfplumber
import pandas as pd
import re
import unicodedata
from collections import defaultdict

st.set_page_config(page_title="Auditor de Cuentas Hospitalarias", layout="wide", page_icon="🏥")
st.title("🏥 Auditor de Cuentas por Cuenta Consolidada")
st.markdown("Sube varios PDFs. La app agrupa documentos por cuenta y consolida el cobro de oxígeno.")

# =========================
# UTILIDADES GENERALES
# =========================
def extraer_texto_pdf(archivo_pdf):
    texto_completo = []
    with pdfplumber.open(archivo_pdf) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text()
            if texto:
                texto_completo.append(texto)
    return "\n".join(texto_completo)

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

def a_float_seguro(valor: str) -> float:
    """
    Para cantidades como 1.000, 2.000, 3.5
    """
    try:
        return float(valor.replace(",", ""))
    except Exception:
        return 0.0

# =========================
# IDENTIFICACION DE DOCUMENTOS
# =========================
def extraer_cuenta(texto: str) -> str:
    match = re.search(r"\bNC\d{5,}\b", texto, re.IGNORECASE)
    if match:
        return match.group(0).upper()

    match = re.search(r"Cuenta[:\s]+(NC\d+)", texto, re.IGNORECASE)
    if match:
        return match.group(1).upper()

    return "SIN_CUENTA"

def extraer_paciente(texto: str) -> str:
    # Estados de cuenta
    match = re.search(
        r"Nombre Paciente\s+Fecha nacimiento:.*?\n(.+?)\nMedico",
        texto,
        re.IGNORECASE | re.DOTALL
    )
    if match:
        return compactar_espacios(match.group(1))

    # Documentos clínicos
    match = re.search(r"Nombre:\s*(.+?)\s*Fecha de nacimiento:", texto, re.IGNORECASE | re.DOTALL)
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

# =========================
# DEPARTAMENTOS Y OXIGENO
# =========================
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

def extraer_bloques_departamento(texto: str):
    """
    Extrae bloques completos tipo:
    Departamento: 102 HOSPITALIZACION
    ...lineas...
    Departamento: 240 QUIROFANO
    ...lineas...

    Más robusto que depender de una línea exacta.
    """
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

def sumar_oxigeno_en_bloque(contenido_bloque: str) -> float:
    """
    Busca TODAS las ocurrencias de oxígeno por hora dentro del bloque.
    Funciona aunque haya saltos de línea o espacios raros.
    """
    t = normalizar_texto(contenido_bloque)
    t = compactar_espacios(t)

    patrones = [
        r"(?:apr-\d+\s+)?oxigeno por hora\s+(\d+(?:\.\d+)?)",
        r"(?:apr-\d+\s+)?oxigeno\s+por\s+hora\s+(\d+(?:\.\d+)?)",
        r"(?:apr-\d+\s+)?oxigeno x hr\s+(\d+(?:\.\d+)?)",
    ]

    total = 0.0
    for patron in patrones:
        for m in re.finditer(patron, t, re.IGNORECASE):
            total += a_float_seguro(m.group(1))

    return total

def extraer_oxigeno_estado_cuenta(texto: str) -> dict:
    """
    Devuelve oxígeno cobrado por departamento.
    """
    resultado = {
        "quirofano": 0.0,
        "recuperacion": 0.0,
        "hospitalizacion": 0.0,
        "otro": 0.0
    }

    bloques = extraer_bloques_departamento(texto)

    for bloque in bloques:
        depto = bloque["departamento"]
        if depto == "caja":
            continue

        oxigeno = sumar_oxigeno_en_bloque(bloque["contenido"])
        resultado[depto] += oxigeno

    return resultado

# =========================
# FUENTE ESPERADA DESDE SERVICIOS DE CIRUGIA
# =========================
def extraer_esperado_servicios_cirugia(texto: str) -> dict:
    t = normalizar_texto(texto)
    t = compactar_espacios(t)

    esperado_qx = 0.0
    esperado_rec = 0.0
    hora_total_qx = None

    patrones_qx = [
        r"oxigeno x hr\s+(\d+(?:\.\d+)?)\s*hrs",
        r"oxigeno por hora\s+(\d+(?:\.\d+)?)\s*hrs",
    ]
    for patron in patrones_qx:
        m = re.search(patron, t, re.IGNORECASE)
        if m:
            esperado_qx = a_float_seguro(m.group(1))
            break

    patrones_rec = [
        r"oxigeno recuperacion\s+(\d+(?:\.\d+)?)\s*hrs",
        r"oxigeno de recuperacion\s+(\d+(?:\.\d+)?)\s*hrs",
    ]
    for patron in patrones_rec:
        m = re.search(patron, t, re.IGNORECASE)
        if m:
            esperado_rec = a_float_seguro(m.group(1))
            break

    m_total = re.search(r"hora total de quirofano:\s*(\d+(?:\.\d+)?)\s*hrs", t, re.IGNORECASE)
    if m_total:
        hora_total_qx = a_float_seguro(m_total.group(1))

    return {
        "esperado_quirofano": esperado_qx,
        "esperado_recuperacion": esperado_rec,
        "esperado_total_quirurgico": esperado_qx + esperado_rec,
        "hora_total_quirofano_documentada": hora_total_qx
    }

def extraer_tiempo_postquirurgico(texto: str):
    t = normalizar_texto(texto)
    t = compactar_espacios(t)

    m = re.search(r"tiempo quirurgico:\s*(\d+(?:\.\d+)?)\s*hrs", t, re.IGNORECASE)
    if m:
        return a_float_seguro(m.group(1))
    return None

# =========================
# CONSOLIDACION
# =========================
def consolidar_por_cuenta(archivos_subidos):
    cuentas = defaultdict(lambda: {
        "paciente": None,
        "archivos": [],
        "esperado": {
            "esperado_quirofano": 0.0,
            "esperado_recuperacion": 0.0,
            "esperado_total_quirurgico": 0.0,
            "hora_total_quirofano_documentada": None
        },
        "cobrado": {
            "quirofano": 0.0,
            "recuperacion": 0.0,
            "hospitalizacion": 0.0,
            "otro": 0.0
        },
        "tiempo_postquirurgico": None
    })

    for archivo in archivos_subidos:
        texto = extraer_texto_pdf(archivo)
        cuenta = extraer_cuenta(texto)
        paciente = extraer_paciente(texto)
        tipo = detectar_tipo_documento(texto)

        if cuentas[cuenta]["paciente"] in (None, "No identificado") and paciente != "No identificado":
            cuentas[cuenta]["paciente"] = paciente

        cuentas[cuenta]["archivos"].append({
            "archivo": archivo.name,
            "tipo": tipo
        })

        if tipo.startswith("estado_cuenta"):
            ox = extraer_oxigeno_estado_cuenta(texto)
            for k, v in ox.items():
                cuentas[cuenta]["cobrado"][k] += v

        elif tipo == "servicios_cirugia":
            cuentas[cuenta]["esperado"] = extraer_esperado_servicios_cirugia(texto)

        elif tipo == "nota_postquirurgica":
            cuentas[cuenta]["tiempo_postquirurgico"] = extraer_tiempo_postquirurgico(texto)

    return cuentas

def evaluar_diferencia(cobrado: float, esperado: float, tolerancia: float = 0.01):
    diff = round(cobrado - esperado, 2)

    if esperado is None:
        return "NO EVALUABLE", None

    if abs(diff) <= tolerancia:
        return "OK", diff
    elif diff < 0:
        return "FALTA CARGAR", diff
    else:
        return "COBRADO DE MÁS", diff

# =========================
# UI
# =========================
archivos_subidos = st.file_uploader(
    "Selecciona los documentos PDF",
    type=["pdf"],
    accept_multiple_files=True
)

if archivos_subidos:
    with st.spinner(f"Analizando {len(archivos_subidos)} archivo(s)..."):
        cuentas = consolidar_por_cuenta(archivos_subidos)

    filas = []
    for cuenta, data in cuentas.items():
        esp_qx = data["esperado"]["esperado_quirofano"]
        esp_rec = data["esperado"]["esperado_recuperacion"]

        cob_qx = data["cobrado"]["quirofano"]
        cob_rec = data["cobrado"]["recuperacion"]
        cob_hosp = data["cobrado"]["hospitalizacion"]
        cob_total_todas_areas = cob_qx + cob_rec + cob_hosp

        status_qx, diff_qx = evaluar_diferencia(cob_qx, esp_qx)
        status_rec, diff_rec = evaluar_diferencia(cob_rec, esp_rec)

        status_total_quir, diff_total_quir = evaluar_diferencia(
            cob_qx + cob_rec,
            data["esperado"]["esperado_total_quirurgico"]
        )

        filas.append({
            "Cuenta": cuenta,
            "Paciente": data["paciente"],
            "Archivos asociados": len(data["archivos"]),
            "Tipos detectados": ", ".join(x["tipo"] for x in data["archivos"]),
            "Esperado QX": esp_qx,
            "Cobrado QX": cob_qx,
            "Dif. QX": diff_qx,
            "Status QX": status_qx,
            "Esperado Recuperación": esp_rec,
            "Cobrado Recuperación": cob_rec,
            "Dif. Recuperación": diff_rec,
            "Status Recuperación": status_rec,
            "Cobrado Hospitalización": cob_hosp,
            "Esperado Total Quirúrgico": data["esperado"]["esperado_total_quirurgico"],
            "Cobrado Total Quirúrgico": cob_qx + cob_rec,
            "Dif. Total Quirúrgico": diff_total_quir,
            "Status Total Quirúrgico": status_total_quir,
            "Cobrado Total Oxígeno (todas áreas)": cob_total_todas_areas,
            "Hora total de quirófano doc.": data["esperado"]["hora_total_quirofano_documentada"],
            "Tiempo Postquirúrgico (auxiliar)": data["tiempo_postquirurgico"]
        })

    df = pd.DataFrame(filas)

    st.subheader("Resultado consolidado por cuenta")
    st.dataframe(df, use_container_width=True, hide_index=True)

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Cuentas analizadas", len(df))
    col2.metric("Oxígeno QX cobrado", df["Cobrado QX"].sum())
    col3.metric("Oxígeno recuperación cobrado", df["Cobrado Recuperación"].sum())
    col4.metric("Oxígeno hospitalización cobrado", df["Cobrado Hospitalización"].sum())

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Descargar reporte consolidado",
        data=csv,
        file_name="reporte_oxigeno_consolidado.csv",
        mime="text/csv"
    )
