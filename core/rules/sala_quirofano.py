# core/rules/sala_quirofano.py

from core.config_codigos import (
    CODIGO_SALA_NORMAL,
    CODIGO_SALA_ADICIONAL,
    CODIGO_SEVOFLURANO,
)
from core.rules.common import evaluar, por_codigo


def auditar_sala_quirofano(data: dict, items: list, sc: dict, tolerancia: float) -> list:
    auditorias = []
    # =========================================================
    # Sala quirúrgica
    # =========================================================
    sala_items = por_codigo(items, 
        {CODIGO_SALA_NORMAL, CODIGO_SALA_ADICIONAL},
        "quirofano",
    )

    sala_cobrado = round(sum(item["cantidad"] for item in sala_items), 3)
    sala_esperado = sc.get("hora_total_qx") if sc else None

    if sala_items or sala_esperado:
        status, diff, clase = evaluar(sala_cobrado, sala_esperado, tolerancia)

        auditorias.append({
            "categoria": "Sala quirúrgica",
            "key": "sala_hrs",
            "label": "Horas de sala quirúrgica",
            "tipo": "numerico",
            "unidad": "hrs",
            "cobrado": sala_cobrado,
            "esperado": sala_esperado,
            "status": status,
            "diff": diff,
            "clase": clase,
            "items_cobrados": sala_items,
            "items_esperados": [],
            "nota_auditoria": (
                f"Servicios documenta: {sc.get('sala_hrs_normal', 0):.0f} hr normal + "
                f"{sc.get('sala_hrs_adicional', 0):.0f} hr(s) adicional = "
                f"{sala_esperado:.0f} hrs total."
            ) if sala_esperado else None,
        })

    # Desglose sala normal vs adicional
    if sala_items and sala_esperado and sala_esperado >= 1:
        items_normal = [
            item for item in sala_items
            if item["codigo"] == CODIGO_SALA_NORMAL
        ]

        items_adicional = [
            item for item in sala_items
            if item["codigo"] == CODIGO_SALA_ADICIONAL
        ]

        cantidad_normal = round(
            sum(item["cantidad"] for item in items_normal),
            3,
        )

        cantidad_adicional = round(
            sum(item["cantidad"] for item in items_adicional),
            3,
        )

        esperado_normal = 1.0
        esperado_adicional = max(sala_esperado - 1, 0)

        problemas = []

        if abs(cantidad_normal - esperado_normal) > tolerancia:
            problemas.append(
                f"primera hora: cobrado {cantidad_normal:.0f}, "
                f"esperado {esperado_normal:.0f}"
            )

        if abs(cantidad_adicional - esperado_adicional) > tolerancia:
            problemas.append(
                f"adicionales: cobrado {cantidad_adicional:.0f}, "
                f"esperado {esperado_adicional:.0f}"
            )

        if problemas:
            status_desglose = "desglose incorrecto — " + "; ".join(problemas)
            clase_desglose = "err"

        else:
            status_desglose = (
                f"ok — 1 hr normal + {esperado_adicional:.0f} hr(s) adicional"
            )
            clase_desglose = "ok"

        auditorias.append({
            "categoria": "Sala quirúrgica",
            "key": "sala_desglose",
            "label": "Desglose sala (normal vs adicional)",
            "tipo": "informativo",
            "unidad": "",
            "cobrado": 0,
            "esperado": None,
            "status": status_desglose,
            "diff": None,
            "clase": clase_desglose,
            "items_cobrados": sala_items,
            "items_esperados": [],
            "nota_auditoria": (
                "Debe haber exactamente 1 cargo de primera hora "
                f"({CODIGO_SALA_NORMAL}) y "
                f"{esperado_adicional:.0f} cargo(s) de hora adicional "
                f"({CODIGO_SALA_ADICIONAL})."
            ),
        })

    # =========================================================
    # Sevoflurano
    # =========================================================
    sevo_items = [
        item for item in items
        if item["codigo"] == CODIGO_SEVOFLURANO
    ]

    sevo_cobrado = round(sum(item["cantidad"] for item in sevo_items), 2)
    sevo_esperado = sc.get("sevoflurano_ml") if sc else None

    if sevo_items or sevo_esperado:
        status, diff, clase = evaluar(
            sevo_cobrado,
            sevo_esperado,
            tolerancia=1.0,
        )

        if clase in ("err", "warn"):
            status = (
                "verificar con anestesia — "
                f"documentado {sevo_esperado or 0:.2f} ml; "
                f"cobrado {sevo_cobrado:.2f} ml"
            )
            clase = "gray"

        desglose = " + ".join(
            f"{item['cantidad']:.0f} ml ({item['folio']})"
            for item in sevo_items
        ) if len(sevo_items) > 1 else ""

        nota_sevo = "Tolerancia de ±1.0 ml por redondeo."

        if desglose:
            nota_sevo += f" Desglose: {desglose} = {sevo_cobrado:.0f} ml total."

        auditorias.append({
            "categoria": "Sala quirúrgica",
            "key": "sevoflurano",
            "label": "Sevoflurano",
            "tipo": "numerico",
            "unidad": "ml",
            "cobrado": sevo_cobrado,
            "esperado": sevo_esperado,
            "status": status,
            "diff": diff,
            "clase": clase,
            "items_cobrados": sevo_items,
            "items_esperados": [],
            "nota_auditoria": nota_sevo,
        })


    return auditorias
