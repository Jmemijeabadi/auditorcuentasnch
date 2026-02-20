import streamlit as st
import pdfplumber
import pandas as pd
import re

# Configuración de la página (más ancha para mejor visualización)
st.set_page_config(page_title="Auditor de Cuentas Hospitalarias", layout="wide", page_icon="🏥")

st.title("🏥 Auditor Masivo de Estados de Cuenta")
st.markdown("Sube **varios** estados de cuenta en PDF. El sistema extraerá los datos y resaltará visualmente las posibles fugas de ingresos.")

# Diccionario de conceptos clave a buscar
CONCEPTOS_CLAVE = {
    "quirofano": ["quirofano", "sala de cirugia", "cirugía"],
    "oxigeno": ["oxigeno", "oxigeno por hora"],
    "recuperacion": ["recuperacion", "sala de recuperacion", "post operatorio"],
    "habitacion": ["habitacion", "habitacion ambulatoria"]
}

def extraer_texto_pdf(archivo_pdf):
    texto_completo = ""
    with pdfplumber.open(archivo_pdf) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text()
            if texto:
                texto_completo += texto + "\n"
    return texto_completo

def analizar_conceptos(texto):
    texto_min = texto.lower()
    resultados = {}
    for concepto, palabras_clave in CONCEPTOS_CLAVE.items():
        encontrado = any(palabra in texto_min for palabra in palabras_clave)
        resultados[concepto] = encontrado
    return resultados

def extraer_datos_paciente(texto):
    # Extraer Nombre del Paciente
    match_nombre = re.search(r"Nombre Paciente\s*\n*([A-ZÑ\s]{10,})", texto)
    paciente = match_nombre.group(1).replace("Medico", "").strip() if match_nombre else "No identificado"
        
    # Extraer Total de la Cuenta (Cargos)
    matches_cargos = re.findall(r"CARGOS:\s*([\d,]+\.\d{2})", texto)
    total_cargos = f"${matches_cargos[-1]}" if matches_cargos else "No encontrado"
        
    return paciente, total_cargos

# Función para colorear las celdas de alerta en la tabla
def colorear_alertas(valor):
    if valor == "🚨 ALERTA":
        return 'background-color: #ffcccc; color: #990000; font-weight: bold;'
    elif valor == "Ok":
        return 'color: #006600;'
    return ''

# Interfaz de carga de archivos
archivos_subidos = st.file_uploader(
    "Selecciona los estados de cuenta (PDF)", 
    type=["pdf"], 
    accept_multiple_files=True
)

st.divider()

if archivos_subidos:
    # Mostramos un mensaje de carga
    with st.spinner(f'Analizando {len(archivos_subidos)} archivo(s)...'):
        datos_reporte = []
        
        for archivo in archivos_subidos:
            texto_pdf = extraer_texto_pdf(archivo)
            paciente, total = extraer_datos_paciente(texto_pdf)
            conceptos = analizar_conceptos(texto_pdf)
            
            # Reglas de negocio
            falta_oxigeno = conceptos["quirofano"] and not conceptos["oxigeno"]
            falta_recuperacion = conceptos["quirofano"] and not conceptos["recuperacion"]
            
            datos_reporte.append({
                "Archivo": archivo.name,
                "Paciente": paciente,
                "Total Cargos": total,
                "Tuvo Quirófano": "✅ Sí" if conceptos["quirofano"] else "❌ No",
                "Falta Cobrar Oxígeno": "🚨 ALERTA" if falta_oxigeno else "Ok",
                "Falta Cobrar Recuperación": "🚨 ALERTA" if falta_recuperacion else "Ok"
            })
        
        df_resultados = pd.DataFrame(datos_reporte)
        
        # --- SECCIÓN VISUAL (MÉTRICAS) ---
        st.subheader("📊 Panel de Control de Auditoría")
        
        # Calculamos los totales para los KPIs
        total_cuentas = len(df_resultados)
        alertas_oxi = sum(df_resultados["Falta Cobrar Oxígeno"] == "🚨 ALERTA")
        alertas_rec = sum(df_resultados["Falta Cobrar Recuperación"] == "🚨 ALERTA")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("📄 Cuentas Analizadas", total_cuentas)
        col2.metric("⚠️ Alertas por Oxígeno Faltante", alertas_oxi)
        col3.metric("⚠️ Alertas por Recuperación Faltante", alertas_rec)
        
        st.divider()
        
        # --- SECCIÓN VISUAL (GRÁFICOS Y TABLA) ---
        col_tabla, col_grafico = st.columns([2, 1]) # La tabla ocupará más espacio que el gráfico
        
        with col_tabla:
            st.markdown("**Detalle por Paciente**")
            # Aplicamos el estilo de colores a la tabla
            df_estilizado = df_resultados.style.map(colorear_alertas, subset=["Falta Cobrar Oxígeno", "Falta Cobrar Recuperación"])
            st.dataframe(df_estilizado, use_container_width=True, hide_index=True)
            
        with col_grafico:
            st.markdown("**Resumen de Omisiones**")
            # Creamos un mini DataFrame para el gráfico
            datos_grafico = pd.DataFrame({
                "Concepto": ["Oxígeno", "Recuperación"],
                "Alertas (Falta Cobrar)": [alertas_oxi, alertas_rec]
            })
            # Mostramos un gráfico de barras simple
            st.bar_chart(data=datos_grafico.set_index("Concepto"), color="#ff4b4b")

        # Botón de descarga
        st.divider()
        csv = df_resultados.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Descargar Reporte Completo en CSV",
            data=csv,
            file_name='reporte_auditoria_visual.csv',
            mime='text/csv',
            type="primary"
        )
