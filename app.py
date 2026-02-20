import streamlit as st
import pdfplumber
import pandas as pd
import re

# Configuración de la página
st.set_page_config(page_title="Auditor de Cuentas Hospitalarias", layout="wide")

st.title("🏥 Auditor de Estados de Cuenta Hospitalarios")
st.markdown("Sube un estado de cuenta en PDF para identificar conceptos faltantes (ej. Oxígeno, Recuperación).")

# Diccionario de conceptos clave a buscar
# Puedes agregar más variaciones o sinónimos de cómo aparecen en tu sistema
CONCEPTOS_CLAVE = {
    "quirofano": ["quirofano", "sala de cirugia", "cirugía"],
    "oxigeno": ["oxigeno", "oxigeno por hora"],
    "recuperacion": ["recuperacion", "sala de recuperacion"],
    "habitacion": ["habitacion", "habitacion ambulatoria"]
}

def extraer_texto_pdf(archivo_pdf):
    texto_completo = ""
    with pdfplumber.open(archivo_pdf) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text()
            if texto:
                texto_completo += texto + "\n"
    return texto_completo.lower()

def analizar_conceptos(texto):
    resultados = {}
    for concepto, palabras_clave in CONCEPTOS_CLAVE.items():
        encontrado = any(palabra in texto for palabra in palabras_clave)
        resultados[concepto] = encontrado
    return resultados

# Interfaz de carga de archivos
archivo_subido = st.file_uploader("Sube el estado de cuenta (PDF)", type=["pdf"])

if archivo_subido is not None:
    st.info(f"Analizando: {archivo_subido.name}...")
    
    # Extraer texto
    texto_pdf = extraer_texto_pdf(archivo_subido)
    
    # Analizar qué conceptos están presentes
    conceptos_encontrados = analizar_conceptos(texto_pdf)
    
    # Mostrar resultados en columnas
    st.subheader("📊 Resultados del Análisis")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("**Conceptos Cobrados (Detectados):**")
        for concepto, presente in conceptos_encontrados.items():
            if presente:
                st.success(f"✅ {concepto.capitalize()}")
                
    with col2:
        st.write("**Alertas de Posibles Omisiones:**")
        alertas = 0
        
        # Lógica de reglas de negocio:
        # Si hay quirófano, normalmente debería haber oxígeno
        if conceptos_encontrados["quirofano"] and not conceptos_encontrados["oxigeno"]:
            st.error("⚠️ **Falta Oxígeno:** Se detectó cargo de Quirófano/Cirugía, pero NO se cobró Oxígeno.")
            alertas += 1
            
        # Si hay quirófano, normalmente debería haber sala de recuperación
        if conceptos_encontrados["quirofano"] and not conceptos_encontrados["recuperacion"]:
            st.warning("⚠️ **Falta Recuperación:** Se detectó Quirófano, pero NO se cobró Sala de Recuperación.")
            alertas += 1
            
        if alertas == 0:
            st.info("No se detectaron omisiones obvias con las reglas actuales.")

    # Opción para ver el texto crudo para depurar
    with st.expander("Ver texto extraído del PDF"):
        st.text(texto_pdf)
