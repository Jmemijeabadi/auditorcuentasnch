import io

from core.utils import normalizar
from core.pdf_reader import extraer_texto_pdf
from core.document_classifier import (
    extraer_cuenta,
    extraer_paciente,
    extraer_fechas_estancia,
    extraer_tipo_seguro,
    detectar_tipo_documento,
)
from core.parsers.estado_cuenta import extraer_todos_items
from core.parsers.servicios_cirugia import extraer_servicios_cirugia
from core.parsers.nota_postqx import extraer_nota_postqx


def plantilla_cuenta():
    return {
        "paciente": None,
        "archivos": [],
        "fecha_ingreso": None,
        "fecha_egreso": None,
        "dias_estancia": None,
        "seguro": None,
        "todos_los_items": [],
        "servicios_cirugia": None,
        "nota_postqx": None,
        "num_cirugias": 0,
        "cirugias_detalle": [],
    }


def _item_key(item):
    return (
        item.get("area", ""),
        item.get("codigo", ""),
        normalizar(item.get("descripcion", "")),
        round(item.get("cantidad", 0), 3),
        round(item.get("precio_unitario", 0), 2),
        round(item.get("subtotal", 0), 2),
        item.get("fecha", ""),
        item.get("folio", ""),
    )


def _fusionar_servicios_cirugia(sc_actual: dict, sc_nuevo: dict) -> dict:
    for key in ("oxigeno_qx", "oxigeno_rec", "sala_hrs_normal", "sala_hrs_adicional"):
        sc_actual[key] += sc_nuevo[key]

    sc_actual["evidencias_oxigeno"].extend(sc_nuevo["evidencias_oxigeno"])

    if sc_actual["hora_total_qx"] is None:
        sc_actual["hora_total_qx"] = sc_nuevo["hora_total_qx"]

    if sc_actual["sevoflurano_ml"] is None:
        sc_actual["sevoflurano_ml"] = sc_nuevo["sevoflurano_ml"]

    if sc_actual["ingreso_sala"] is None:
        sc_actual["ingreso_sala"] = sc_nuevo["ingreso_sala"]
        sc_actual["egreso_sala"] = sc_nuevo["egreso_sala"]
        sc_actual["horas_calculadas_m21"] = sc_nuevo["horas_calculadas_m21"]
        sc_actual["minutos_totales"] = sc_nuevo["minutos_totales"]

    if sc_actual["seguro"] is None:
        sc_actual["seguro"] = sc_nuevo["seguro"]

    if not sc_actual["maquina_anestesia"]:
        sc_actual["maquina_anestesia"] = sc_nuevo["maquina_anestesia"]

    if sc_actual["arco_c_hrs"] is None:
        sc_actual["arco_c_hrs"] = sc_nuevo["arco_c_hrs"]

    if not sc_actual["microscopio"]:
        sc_actual["microscopio"] = sc_nuevo["microscopio"]

    if "servicios_marcados" in sc_actual and "servicios_marcados" in sc_nuevo:
        for key in sc_nuevo["servicios_marcados"]:
            if sc_nuevo["servicios_marcados"][key]:
                sc_actual["servicios_marcados"][key] = True

    return sc_actual


def consolidar_por_cuenta_core(archivos_bytes: list):
    """
    Consolida PDFs por cuenta.

    Retorna:
    - cuentas
    - avisos
    """
    cuentas = {}
    avisos = []

    for nombre, contenido in archivos_bytes:
        archivo_pdf = io.BytesIO(contenido)
        archivo_pdf.name = nombre

        texto = extraer_texto_pdf(archivo_pdf)

        if not texto:
            avisos.append({
                "tipo": "warning",
                "mensaje": f"⚠️ '{nombre}' sin texto; se omite.",
            })
            continue

        cuenta = extraer_cuenta(texto)
        paciente = extraer_paciente(texto)
        tipo_doc = detectar_tipo_documento(texto)

        if cuenta == "SIN_CUENTA":
            avisos.append({
                "tipo": "warning",
                "mensaje": f"⚠️ Sin NCxxxxx en '{nombre}'.",
            })

        if tipo_doc == "otro":
            avisos.append({
                "tipo": "info",
                "mensaje": f"ℹ️ '{nombre}' tipo no reconocido.",
            })

        if cuenta not in cuentas:
            cuentas[cuenta] = plantilla_cuenta()

        if cuentas[cuenta]["paciente"] in (None, "No identificado") and paciente != "No identificado":
            cuentas[cuenta]["paciente"] = paciente

        cuentas[cuenta]["archivos"].append({
            "archivo": nombre,
            "tipo_documento": tipo_doc,
        })

        if tipo_doc.startswith("estado_cuenta"):
            items = extraer_todos_items(texto, nombre, tipo_doc, cuenta)

            existentes = {
                _item_key(item)
                for item in cuentas[cuenta]["todos_los_items"]
            }

            items_nuevos = [
                item for item in items
                if _item_key(item) not in existentes
            ]

            cuentas[cuenta]["todos_los_items"].extend(items_nuevos)

            if cuentas[cuenta]["fecha_ingreso"] is None:
                fecha_ingreso, fecha_egreso, dias_estancia = extraer_fechas_estancia(texto)

                if fecha_ingreso:
                    cuentas[cuenta]["fecha_ingreso"] = fecha_ingreso
                    cuentas[cuenta]["fecha_egreso"] = fecha_egreso
                    cuentas[cuenta]["dias_estancia"] = dias_estancia

            if cuentas[cuenta]["seguro"] is None:
                seguro = extraer_tipo_seguro(texto)

                if seguro != "desconocido":
                    cuentas[cuenta]["seguro"] = seguro

        elif tipo_doc == "servicios_cirugia":
            sc_nuevo = extraer_servicios_cirugia(texto)

            cuentas[cuenta]["num_cirugias"] += 1

            cuentas[cuenta]["cirugias_detalle"].append({
                "archivo": nombre,
                "hora_total": sc_nuevo.get("hora_total_qx"),
                "ingreso": sc_nuevo.get("ingreso_sala"),
                "egreso": sc_nuevo.get("egreso_sala"),
                "cirugia_num": cuentas[cuenta]["num_cirugias"],
            })

            if cuentas[cuenta]["servicios_cirugia"] is None:
                cuentas[cuenta]["servicios_cirugia"] = sc_nuevo
            else:
                cuentas[cuenta]["servicios_cirugia"] = _fusionar_servicios_cirugia(
                    cuentas[cuenta]["servicios_cirugia"],
                    sc_nuevo,
                )

            sc_actual = cuentas[cuenta]["servicios_cirugia"]

            if sc_actual.get("seguro"):
                cuentas[cuenta]["seguro"] = sc_actual["seguro"]

        elif tipo_doc == "nota_postquirurgica":
            if cuentas[cuenta]["nota_postqx"] is None:
                cuentas[cuenta]["nota_postqx"] = extraer_nota_postqx(texto)

    return cuentas, avisos
