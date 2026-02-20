import streamlit as st
import pdfplumber
import pandas as pd
import re

# Configuración de la página
st.set_page_config(page_title="Auditor de Cuentas Hospitalarias", layout="wide")

st.title("🏥 Auditor Masivo de Estados de Cuenta")
st.markdown("Sube **varios** estados de cuenta en PDF para identificar pacientes, totales y conceptos faltantes.")

# Diccionario de conceptos clave a buscar
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
    return texto_completo

def analizar_conceptos(texto):
    # Convertimos a minúsculas solo para buscar los conceptos más fácilmente
    texto_min = texto.lower()
    resultados = {}
    for concepto, palabras_clave in CONCEPTOS_CLAVE.items():
        encontrado = any(palabra in texto_min for palabra in palabras_clave)
        resultados[concepto] = encontrado
    return resultados

def extraer_datos_paciente(texto):
    """
    Usa Expresiones Regulares (Regex) para encontrar el nombre y el total de cargos.
    """
    # 1. Extraer Nombre del Paciente
    # Busca "Nombre Paciente", posibles espacios/saltos de línea, y captura todo lo que sea letras mayúsculas
    match_nombre = re.search(r"Nombre Paciente\s*\n*([A-ZÑ\s]{10,})", texto)
    
    if match_nombre:
        # Limpiamos espacios extra y quitamos palabras como "Medico" si se colaron
        paciente = match_nombre.group(1).replace("Medico", "").strip()
    else:
        paciente = "No identificado"
        
    # 2. Extraer Total de la Cuenta (Cargos)
    # Busca la palabra "CARGOS:" seguida de números, comas y dos decimales
    matches_cargos = re.findall(r"CARGOS:\s*([\d,]+\.\d{2})", texto)
    
    if matches_cargos:
        # Tomamos el último que aparezca en el documento, ya que suele ser el Gran Total
        total_cargos = f"${matches_cargos[-1]}"
    else:
        total_cargos = "No encontrado"
        
    return paciente, total_cargos

# Interfaz de carga de archivos
archivos_subidos = st.file_uploader(
    "Selecciona uno o más estados de cuenta (PDF)", 
    type=["pdf"], 
    accept_multiple_files=True
)

if archivos_subidos:
    st.info(f"Analizando {len(archivos_subidos)} archivo(s)...")
    
    datos_reporte = []
    
    for archivo in archivos_subidos:
        # 1. Extraer todo el texto
        texto_pdf = extraer_texto_pdf(archivo)
        
        # 2. Extraer Paciente y Total
        paciente, total = extraer_datos_paciente(texto_pdf)
        
        # 3. Analizar conceptos médicos
        conceptos = analizar_conceptos(texto_pdf)
        
        # 4. Lógica de reglas de negocio
        falta_oxigeno = conceptos["quirofano"] and not conceptos["oxigeno"]
        falta_recuperacion = conceptos["quirofano"] and not conceptos["recuperacion"]
        
        # 5. Agregar fila al reporte
        datos_reporte.append({
            "Archivo": archivo.name,
            "Paciente": paciente,
            "Total Cargos": total,
            "Tuvo Quirófano": "✅ Sí" if conceptos["quirofano"] else "❌ No",
            "Falta Cobrar Oxígeno": "🚨 ALERTA" if falta_oxigeno else "Ok",
            "Falta Cobrar Recuperación": "🚨 ALERTA" if falta_recuperacion else "Ok"
        })
    
    # Mostrar tabla
    df_resultados = pd.DataFrame(datos_reporte)
    
    st.subheader("📊 Resumen de Auditoría")
    st.dataframe(df_resultados, use_container_width=True)
    
    # Botón de descarga
    csv = df_resultados.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Descargar Reporte en Excel (CSV)",
        data=csv,
        file_name='reporte_auditoria_hospital.csv',
        mime='text/csv',
    )
