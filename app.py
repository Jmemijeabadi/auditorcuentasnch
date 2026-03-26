import os
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pdfplumber
import streamlit as st

# =========================
# CONFIGURACIÓN
# =========================
st.set_page_config(
    page_title="Auditor de Estados de Cuenta Hospitalarios",
    page_icon="🏥",
    layout="wide",
)

st.title("🏥 Auditor de Estados de Cuenta Hospitalarios")
st.caption(
    "Versión robusta para estados de cuenta de NewCity Hospital: separa PACIENTE/EXTRAS, "
    "lee resúmenes oficiales por corte y valida quirófano, recuperación y oxígeno facturable."
)

with st.expander("Ver criterios de auditoría"):
    st.markdown(
        """
        **Cómo decide esta versión:**

        - **Quirófano**: se valida por departamento `QUIROFANO`.
        - **Recuperación**: se valida por departamento `RECUPERACION (POST OPERATORIO)` o por cargo válido dentro de ese departamento.
        - **Oxígeno válido**: esta versión es **conservadora** y solo cuenta cargos tipo servicio facturable, como `OXIGENO POR HORA`.
        - **No** toma como válido cualquier palabra relacionada con oxígeno, para evitar falsos positivos con conceptos como `AGUA OXIGENADA` o `MASCARILLA PARA OXIGENO`.

        Si después quieres ampliar la lógica para otros conceptos válidos de oxígeno, solo hay que agregar patrones en `VALID_OXYGEN_REGEXES`.
        """
    )


# =========================
# PATRONES Y HELPERS
# =========================
SUMMARY_DEPT_ROW_RE = re.compile(
    r"^([A-ZÁÉÍÓÚÜÑ() /-]+?)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})$"
)
SECTION_CUT_RE = re.compile(r"Estado de cuenta corte a:\s*(PACIENTE|EXTRAS)", re.IGNORECASE)
SUMMARY_BLOCK_RE = re.compile(
    r"ESTADO DE CUENTA CORTE\s+(PACIENTE|EXTRAS)(.*?)(?=NEWCITY HOSPITAL SAPI DE CV|$)",
    re.DOTALL | re.IGNORECASE,
)
DEPARTMENT_HEADER_RE = re.compile(r"^Departamento:\s*(\d+)\s+(.+?)\s*$")

# Conservador: cuenta solo conceptos de oxígeno facturable / de servicio.
VALID_OXYGEN_REGEXES = [
    re.compile(r"\boxigeno\s+(por|x)\s+hora\b"),
    re.compile(r"\boxigenoterapia\b"),
    re.compile(r"\boxigeno\s+medicinal\b"),
]

VALID_RECOVERY_REGEXES = [
    re.compile(r"\bsala\s+de\s+recuperacion\b"),
    re.compile(r"\brecuperacion\s*\(post\s*operatorio\)\b"),
]


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_amount(text: Optional[str]) -> Optional[float]:
    if text is None:
        return None
    cleaned = text.replace(",", "").replace("$", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def format_money(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"${value:,.2f}"


def status_yes_no(value: bool) -> str:
    return "✅ Sí" if value else "❌ No"


def style_status(value: str) -> str:
    if value == "🚨 ALERTA":
        return "background-color: #ffe0e0; color: #8b0000; font-weight: bold;"
    if value.startswith("✅"):
        return "color: #0b6e4f; font-weight: 600;"
    if value.startswith("❌"):
        return "color: #8a6d00; font-weight: 600;"
    if value == "Error":
        return "background-color: #f5d0d0; color: #7f1d1d; font-weight: bold;"
    return ""


# =========================
# EXTRACCIÓN DEL PDF
# =========================
def extract_pdf_text(uploaded_file) -> Tuple[str, List[str]]:
    uploaded_file.seek(0)
    pages_text: List[str] = []
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            pages_text.append(page.extract_text() or "")
    full_text = "\n".join(pages_text)
    return full_text, pages_text


def extract_header_info(full_text: str) -> Dict[str, Optional[str]]:
    account = None
    room = None
    patient = None
    doctor = None

    account_match = re.search(r"\b(NC\d{5})\b", full_text)
    if account_match:
        account = account_match.group(1)

    room_match = re.search(
        r"Cuenta\s+Cuarto\s+Fecha Ingreso\s+Fecha egreso\s*\n\s*(NC\d{5})\s+(.+?)\s+(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2})\s+(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2})",
        full_text,
        re.IGNORECASE,
    )
    if room_match:
        room = room_match.group(2).strip()

    patient_match = re.search(
        r"Nombre Paciente\s+Fecha nacimiento:\s+Edad:\s+Sexo:\s*\n\s*(.+?)\s+\d{4}-\d{2}-\d{2}\s+\d+\s+\w+\s+\w+",
        full_text,
        re.IGNORECASE,
    )
    if patient_match:
        patient = patient_match.group(1).strip()

    doctor_match = re.search(r"Medico\s+Cia\.\s+Cliente\s*\n\s*([^\n]+)", full_text, re.IGNORECASE)
    if doctor_match:
        line = doctor_match.group(1).strip()
        doctor = re.sub(
            r"\s+(PARTICULAR|ASEGURADORA.*|CLIENTE.*)$",
            "",
            line,
            flags=re.IGNORECASE,
        ).strip()

    return {
        "cuenta": account,
        "cuarto": room,
        "paciente": patient,
        "medico": doctor,
    }


def split_detail_sections(full_text: str) -> Dict[str, str]:
    matches = list(SECTION_CUT_RE.finditer(full_text))
    sections: Dict[str, str] = {}

    for i, match in enumerate(matches):
        cut = match.group(1).upper()
        start = match.end()
        next_cut_start = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)

        summary_match = re.search(
            rf"ESTADO DE CUENTA CORTE\s+{cut}\b",
            full_text[start:next_cut_start],
            re.IGNORECASE,
        )
        end = start + summary_match.start() if summary_match else next_cut_start
        sections[cut] = full_text[start:end]

    return sections


def parse_summary_blocks(full_text: str) -> Dict[str, Dict]:
    summaries: Dict[str, Dict] = {}

    for match in SUMMARY_BLOCK_RE.finditer(full_text):
        cut = match.group(1).upper()
        block = match.group(2)
        data = {
            "departamentos": {},
            "cargos": None,
            "abonos": None,
            "saldo": None,
            "raw": block,
        }

        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            dept_match = SUMMARY_DEPT_ROW_RE.match(line)
            if dept_match:
                dept_name = dept_match.group(1).strip()
                data["departamentos"][dept_name] = {
                    "importe": parse_amount(dept_match.group(2)),
                    "descuento": parse_amount(dept_match.group(3)),
                    "subtotal": parse_amount(dept_match.group(4)),
                    "impuesto": parse_amount(dept_match.group(5)),
                    "total": parse_amount(dept_match.group(6)),
                }
                continue

            charges_match = re.match(r"CARGOS:\s*([\d,]+\.\d{2})", line, re.IGNORECASE)
            if charges_match:
                data["cargos"] = parse_amount(charges_match.group(1))
                continue

            abonos_match = re.match(r"ABONOS:\s*(-?[\d,]+\.\d{2})", line, re.IGNORECASE)
            if abonos_match:
                data["abonos"] = parse_amount(abonos_match.group(1))
                continue

            saldo_match = re.match(r"SALDO:\s*(-?[\d,]+\.\d{2})", line, re.IGNORECASE)
            if saldo_match:
                data["saldo"] = parse_amount(saldo_match.group(1))
                continue

        summaries[cut] = data

    return summaries


def parse_department_blocks(section_text: str) -> Dict[str, Dict]:
    departments: Dict[str, Dict] = {}
    current_key: Optional[str] = None

    for raw_line in section_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        dept_match = DEPARTMENT_HEADER_RE.match(line)
        if dept_match:
            dept_code = dept_match.group(1)
            dept_name = dept_match.group(2).strip()
            current_key = dept_name
            departments[current_key] = {
                "code": dept_code,
                "name": dept_name,
                "lines": [],
            }
            continue

        # Ignorar headers/pies repetidos por cambio de página.
        if any(
            line.startswith(prefix)
            for prefix in [
                "NEWCITY HOSPITAL",
                "BLVD.",
                "ESTADO DE CUENTA",
                "Cuenta Cuarto",
                "Nombre Paciente",
                "Medico Cia.",
                "Codigo. Descripcion",
                "Estado de cuenta corte a:",
                "YOSES DEL CARMEN",
            ]
        ):
            continue

        if line.startswith("Total por departamento"):
            continue
        if line.startswith("DEPARTAMENTO IMPORTE"):
            continue
        if re.match(r"^\d{2}-\d{2}-\d{4} .*Pagina \d+ de \d+$", line):
            continue

        if current_key:
            departments[current_key]["lines"].append(line)

    return departments


def find_evidence_lines(lines: List[str], patterns: List[re.Pattern]) -> List[str]:
    found: List[str] = []
    for line in lines:
        normalized = normalize_text(line)
        if any(pattern.search(normalized) for pattern in patterns):
            found.append(line)
    return found


def detect_from_summary_departments(summary_departments: Dict[str, Dict], normalized_target: str) -> bool:
    for dept_name in summary_departments:
        if normalized_target in normalize_text(dept_name):
            return True
    return False


# =========================
# ANÁLISIS DEL ARCHIVO
# =========================
def analyze_statement(uploaded_file) -> Dict:
    result_base = {
        "Archivo": uploaded_file.name,
        "Cuenta": "",
        "Paciente": "",
        "Cuarto": "",
        "Cargos Paciente": "-",
        "Cargos Extras": "-",
        "Cargos Totales": "-",
        "Tuvo Extras": "❌ No",
        "Tuvo Quirófano": "❌ No",
        "Tuvo Recuperación": "❌ No",
        "Oxígeno válido detectado": "❌ No",
        "Falta Cobrar Oxígeno": "Ok",
        "Falta Cobrar Recuperación": "Ok",
        "Evidencia Quirófano": "",
        "Evidencia Recuperación": "",
        "Evidencia Oxígeno": "",
        "Estado": "Procesado",
        "Error": "",
        "_cargos_paciente_num": None,
        "_cargos_extras_num": None,
        "_cargos_totales_num": None,
        "_alerta_oxigeno_num": 0,
        "_alerta_recuperacion_num": 0,
        "_tuvo_quirofano_num": 0,
    }

    try:
        full_text, _ = extract_pdf_text(uploaded_file)

        if not full_text.strip():
            result_base.update(
                {
                    "Estado": "Error",
                    "Error": "El PDF no contiene texto legible. Puede ser un escaneo o estar protegido.",
                }
            )
            return result_base

        header = extract_header_info(full_text)
        sections = split_detail_sections(full_text)
        summaries = parse_summary_blocks(full_text)
        dept_by_cut = {cut: parse_department_blocks(text) for cut, text in sections.items()}

        has_or = False
        has_recovery = False
        evidence_or: List[str] = []
        evidence_recovery: List[str] = []
        evidence_oxygen: List[str] = []

        for cut, departments in dept_by_cut.items():
            for dept_name, dept_data in departments.items():
                dept_norm = normalize_text(dept_name)
                lines = dept_data["lines"]

                if "quirofano" in dept_norm:
                    has_or = True
                    evidence_or.append(f"{cut}: Departamento {dept_data['code']} {dept_name}")
                    for hit in find_evidence_lines(lines, VALID_OXYGEN_REGEXES):
                        evidence_oxygen.append(f"{cut} / {dept_name}: {hit}")

                if "recuperacion" in dept_norm:
                    has_recovery = True
                    evidence_recovery.append(f"{cut}: Departamento {dept_data['code']} {dept_name}")
                    for hit in find_evidence_lines(lines, VALID_RECOVERY_REGEXES):
                        evidence_recovery.append(f"{cut} / {dept_name}: {hit}")
                    for hit in find_evidence_lines(lines, VALID_OXYGEN_REGEXES):
                        evidence_oxygen.append(f"{cut} / {dept_name}: {hit}")

        # Respaldo por resumen oficial si el layout detallado no permitió capturar el header del departamento.
        summary_depts: Dict[str, Dict] = {}
        for cut_summary in summaries.values():
            summary_depts.update(cut_summary.get("departamentos", {}))

        if not has_or and detect_from_summary_departments(summary_depts, "quirofano"):
            has_or = True
            evidence_or.append("Resumen oficial: QUIROFANO")

        if not has_recovery and detect_from_summary_departments(summary_depts, "recuperacion"):
            has_recovery = True
            evidence_recovery.append("Resumen oficial: RECUPERACION (POST OPERATORIO)")

        valid_oxygen = len(evidence_oxygen) > 0
        alert_missing_oxygen = has_or and not valid_oxygen
        alert_missing_recovery = has_or and not has_recovery

        patient_charges = summaries.get("PACIENTE", {}).get("cargos")
        extras_charges = summaries.get("EXTRAS", {}).get("cargos")
        total_charges = None
        if patient_charges is not None or extras_charges is not None:
            total_charges = (patient_charges or 0.0) + (extras_charges or 0.0)

        result_base.update(
            {
                "Cuenta": header.get("cuenta") or "",
                "Paciente": header.get("paciente") or "No identificado",
                "Cuarto": header.get("cuarto") or "",
                "Cargos Paciente": format_money(patient_charges),
                "Cargos Extras": format_money(extras_charges),
                "Cargos Totales": format_money(total_charges),
                "Tuvo Extras": status_yes_no(extras_charges is not None and extras_charges > 0),
                "Tuvo Quirófano": status_yes_no(has_or),
                "Tuvo Recuperación": status_yes_no(has_recovery),
                "Oxígeno válido detectado": status_yes_no(valid_oxygen),
                "Falta Cobrar Oxígeno": "🚨 ALERTA" if alert_missing_oxygen else "Ok",
                "Falta Cobrar Recuperación": "🚨 ALERTA" if alert_missing_recovery else "Ok",
                "Evidencia Quirófano": " | ".join(dict.fromkeys(evidence_or))[:800],
                "Evidencia Recuperación": " | ".join(dict.fromkeys(evidence_recovery))[:800],
                "Evidencia Oxígeno": " | ".join(dict.fromkeys(evidence_oxygen))[:800],
                "_cargos_paciente_num": patient_charges,
                "_cargos_extras_num": extras_charges,
                "_cargos_totales_num": total_charges,
                "_alerta_oxigeno_num": int(alert_missing_oxygen),
                "_alerta_recuperacion_num": int(alert_missing_recovery),
                "_tuvo_quirofano_num": int(has_or),
            }
        )
        return result_base

    except Exception as exc:
        result_base.update(
            {
                "Estado": "Error",
                "Error": str(exc),
            }
        )
        return result_base


# =========================
# INTERFAZ
# =========================
uploaded_files = st.file_uploader(
    "Selecciona uno o varios estados de cuenta en PDF",
    type=["pdf"],
    accept_multiple_files=True,
)

if uploaded_files:
    with st.spinner(f"Analizando {len(uploaded_files)} archivo(s)..."):
        rows = [analyze_statement(file) for file in uploaded_files]

    df = pd.DataFrame(rows)

    total_files = len(df)
    total_processed = int((df["Estado"] == "Procesado").sum())
    total_errors = int((df["Estado"] == "Error").sum())
    total_or = int(df["_tuvo_quirofano_num"].fillna(0).sum())
    total_alert_oxygen = int(df["_alerta_oxigeno_num"].fillna(0).sum())
    total_alert_recovery = int(df["_alerta_recuperacion_num"].fillna(0).sum())
    total_patient_charges = float(df["_cargos_paciente_num"].fillna(0).sum())
    total_extras_charges = float(df["_cargos_extras_num"].fillna(0).sum())
    total_all_charges = float(df["_cargos_totales_num"].fillna(0).sum())

    st.subheader("📊 Resumen")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Archivos", total_files)
    c2.metric("Procesados", total_processed)
    c3.metric("Con quirófano", total_or)
    c4.metric("Alertas oxígeno", total_alert_oxygen)
    c5.metric("Alertas recuperación", total_alert_recovery)

    c6, c7, c8 = st.columns(3)
    c6.metric("Cargos paciente", format_money(total_patient_charges))
    c7.metric("Cargos extras", format_money(total_extras_charges))
    c8.metric("Cargos totales", format_money(total_all_charges))

    st.divider()

    col_table, col_chart = st.columns([2.3, 1])

    display_columns = [
        "Archivo",
        "Cuenta",
        "Paciente",
        "Cuarto",
        "Cargos Paciente",
        "Cargos Extras",
        "Cargos Totales",
        "Tuvo Extras",
        "Tuvo Quirófano",
        "Tuvo Recuperación",
        "Oxígeno válido detectado",
        "Falta Cobrar Oxígeno",
        "Falta Cobrar Recuperación",
        "Evidencia Quirófano",
        "Evidencia Recuperación",
        "Evidencia Oxígeno",
        "Estado",
        "Error",
    ]

    with col_table:
        st.markdown("**Detalle por cuenta**")
        styled = df[display_columns].style.applymap(
            style_status,
            subset=[
                "Tuvo Extras",
                "Tuvo Quirófano",
                "Tuvo Recuperación",
                "Oxígeno válido detectado",
                "Falta Cobrar Oxígeno",
                "Falta Cobrar Recuperación",
                "Estado",
            ],
        )
        st.dataframe(styled, use_container_width=True, hide_index=True)

    with col_chart:
        st.markdown("**Resumen de alertas**")
        chart_df = pd.DataFrame(
            {
                "Concepto": ["Oxígeno", "Recuperación", "Errores lectura"],
                "Casos": [total_alert_oxygen, total_alert_recovery, total_errors],
            }
        ).set_index("Concepto")
        st.bar_chart(chart_df)

    st.divider()

    csv_export = df[display_columns].to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="📥 Descargar reporte CSV",
        data=csv_export,
        file_name="reporte_auditoria_hospitalaria.csv",
        mime="text/csv",
        type="primary",
    )

else:
    st.info("Carga tus PDFs para comenzar el análisis.")
