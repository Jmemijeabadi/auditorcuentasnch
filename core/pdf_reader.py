import logging
import pdfplumber


def extraer_texto_pdf(archivo_pdf) -> str:
    """
    Extrae texto de un PDF usando pdfplumber.

    Nota:
    Esta función no depende de Streamlit para que después pueda usarse
    también desde FastAPI, OpenClaw o procesos automáticos.
    """
    archivo_pdf.seek(0)
    partes = []

    try:
        with pdfplumber.open(archivo_pdf) as pdf:
            for i, pagina in enumerate(pdf.pages, 1):
                texto = pagina.extract_text()
                if texto:
                    partes.append(texto)
                else:
                    logging.warning(
                        "PDF sin texto extraíble: %s página %s",
                        getattr(archivo_pdf, "name", "?"),
                        i,
                    )

    except Exception:
        logging.exception(
            "Error leyendo PDF: %s",
            getattr(archivo_pdf, "name", "?"),
        )

    return "\n".join(partes)
