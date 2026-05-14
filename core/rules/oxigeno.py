# core/rules/oxigeno.py

from core.config_codigos import (
    CODIGOS_OXIGENO,
    CODIGO_SALA_NORMAL,
    CODIGO_SALA_ADICIONAL,
)
from core.rules.common import evaluar, por_codigo


def auditar_oxigeno(data: dict, items: list, sc: dict, tolerancia: float) -> list:
    auditorias = []
    # =========================================================
    # Oxígeno QX
    # =========================================================
    oxigeno_qx_items = por_codigo(items, CODIGOS_OXIGENO, "quirofano")
    cobrado_qx = round(sum(item["cantidad"] for item in oxigeno_qx_items), 3)

    sala_items_qx = por_codigo(items, 
        {CODIGO_SALA_NORMAL, CODIGO_SALA_ADICIONAL},
        "quirofano",
    )

    sala_total_cobrada = round(
        sum(item["cantidad"] for item in sala_items_qx),
        3,
    )

    if sala_total_cobrada > 0:
        esperado_qx = sala_total_cobrada

    elif sc:
        sala_total_doc = (
            sc.get("sala_hrs_normal", 0.0)
            + sc.get("sala_hrs_adicional", 0.0)
        )

        if sala_total_doc == 0 and sc.get("hora_total_qx"):
            sala_total_doc = sc["hora_total_qx"]

        esperado_qx = sala_total_doc if sala_total_doc > 0 else None

    else:
        esperado_qx = None

    if oxigeno_qx_items or (esperado_qx is not None and esperado_qx > 0):
        status, diff, clase = evaluar(cobrado_qx, esperado_qx, tolerancia)

        nota_partes = []

        if sala_total_cobrada > 0:
            normal_cobrado = sum(
                item["cantidad"]
                for item in sala_items_qx
                if item["codigo"] == CODIGO_SALA_NORMAL
            )

            adicional_cobrado = sum(
                item["cantidad"]
                for item in sala_items_qx
                if item["codigo"] == CODIGO_SALA_ADICIONAL
            )

            nota_partes.append(
                "Esperado calculado desde cargos QRF en estado de cuenta: "
                f"{normal_cobrado:.0f} hr normal + "
                f"{adicional_cobrado:.0f} hr adicional = "
                f"{sala_total_cobrada:.0f} hrs."
            )

        elif sc:
            nota_partes.append(
                "Sin cargos QRF parseables; esperado calculado como respaldo "
                "desde hoja de servicios: "
                f"{sc.get('sala_hrs_normal', 0):.0f} hr normal + "
                f"{sc.get('sala_hrs_adicional', 0):.0f} hr adicional."
            )

        if sc:
            oxigeno_doc = sc.get("oxigeno_qx", 0)

            if oxigeno_doc and abs(oxigeno_doc - (esperado_qx or 0)) > 0.01:
                nota_partes.append(
                    f"Hoja de servicios marca {oxigeno_doc:.0f} hrs en el campo "
                    "'Oxígeno x hr' (dato informativo; no define el cobro de oxígeno QX)."
                )

        auditorias.append({
            "categoria": "Oxígeno",
            "key": "oxigeno_quirofano",
            "label": "Oxígeno — Quirófano",
            "tipo": "numerico",
            "unidad": "hrs",
            "cobrado": cobrado_qx,
            "esperado": esperado_qx,
            "status": status,
            "diff": diff,
            "clase": clase,
            "items_cobrados": oxigeno_qx_items,
            "items_esperados": [
                evidencia
                for evidencia in sc.get("evidencias_oxigeno", [])
                if evidencia["area"] == "quirofano"
            ],
            "nota_auditoria": " ".join(nota_partes) if nota_partes else None,
        })

        # Aviso documental de casilla azul
        sala_total_doc = (
            sc.get("sala_hrs_normal", 0)
            + sc.get("sala_hrs_adicional", 0)
        )

        oxigeno_qx_doc = sc.get("oxigeno_qx", 0)

        if sala_total_doc > 0 or oxigeno_qx_doc > 0:
            casilla_ok = abs(sala_total_doc - oxigeno_qx_doc) < 0.01

            if casilla_ok:
                status_aviso = (
                    "ok — casilla azul correctamente llenada "
                    f"({oxigeno_qx_doc:.0f} hrs = sala {sala_total_doc:.0f} hrs)"
                )
                clase_aviso = "ok"

            else:
                status_aviso = (
                    f"casilla azul marca {oxigeno_qx_doc:.0f} hrs cuando "
                    f"la sala fue de {sala_total_doc:.0f} hrs — "
                    "verificar con enfermería"
                )
                clase_aviso = "gray"

            auditorias.append({
                "categoria": "Avisos de documentación",
                "key": "aviso_casilla_azul",
                "label": "Aviso a enfermería: casilla azul de oxígeno",
                "tipo": "informativo",
                "unidad": "hrs",
                "cobrado": oxigeno_qx_doc,
                "esperado": sala_total_doc,
                "status": status_aviso,
                "diff": round(oxigeno_qx_doc - sala_total_doc, 1),
                "clase": clase_aviso,
                "items_cobrados": [],
                "items_esperados": [],
                "nota_auditoria": (
                    "Este dato NO se usa para validar el cobro. Es un aviso de "
                    "proceso: la casilla azul 'Oxígeno x hr' de la hoja de "
                    "servicios debe coincidir con las horas de sala. Si no "
                    "coincide, enfermería llenó mal la hoja."
                ),
            })

    # =========================================================
    # Oxígeno recuperación
    # =========================================================
    oxigeno_rec_items = por_codigo(items, CODIGOS_OXIGENO, "recuperacion")
    cobrado_rec = round(sum(item["cantidad"] for item in oxigeno_rec_items), 3)

    esperado_rec = sc.get("oxigeno_rec", 0.0) if sc else None

    if not sc:
        esperado_rec = None

    elif sc.get("oxigeno_rec", 0.0) == 0 and cobrado_rec == 0:
        esperado_rec = None

    if esperado_rec is not None or oxigeno_rec_items:
        status, diff, clase = evaluar(cobrado_rec, esperado_rec, tolerancia)

        auditorias.append({
            "categoria": "Oxígeno",
            "key": "oxigeno_recuperacion",
            "label": "Oxígeno — Recuperación",
            "tipo": "numerico",
            "unidad": "hrs",
            "cobrado": cobrado_rec,
            "esperado": esperado_rec,
            "status": status,
            "diff": diff,
            "clase": clase,
            "items_cobrados": oxigeno_rec_items,
            "items_esperados": [
                evidencia
                for evidencia in sc.get("evidencias_oxigeno", [])
                if evidencia["area"] == "recuperacion"
            ],
            "nota_auditoria": None,
        })

    # =========================================================
    # Oxígeno hospitalización
    # =========================================================
    oxigeno_hosp_items = por_codigo(items, CODIGOS_OXIGENO, "hospitalizacion")

    if oxigeno_hosp_items:
        cobrado_hosp = round(
            sum(item["cantidad"] for item in oxigeno_hosp_items),
            3,
        )

        detalle = "; ".join(
            f"{item['cantidad']:.2f} hr {item['fecha']} folio {item['folio']}"
            for item in oxigeno_hosp_items
        )

        auditorias.append({
            "categoria": "Oxígeno",
            "key": "oxigeno_hosp",
            "label": "Oxígeno — Hospitalización",
            "tipo": "numerico",
            "unidad": "hrs",
            "cobrado": cobrado_hosp,
            "esperado": None,
            "status": "sin regla",
            "diff": None,
            "clase": "gray",
            "items_cobrados": oxigeno_hosp_items,
            "items_esperados": [],
            "nota_auditoria": (
                f"Sin documento clínico de referencia ({detalle}). "
                "Verificar con nota de enfermería u orden médica."
            ),
        })


    return auditorias
