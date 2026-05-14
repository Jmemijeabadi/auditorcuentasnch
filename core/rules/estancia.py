# core/rules/estancia.py

from core.config_codigos import (
    CODIGO_RPBI,
    DIAS_RPBI_ADICIONAL,
    CODIGOS_HABITACION,
    CODIGO_BOMBA,
)
from core.rules.common import evaluar, por_codigo


def auditar_estancia(data: dict, items: list, dias, tolerancia: float) -> list:
    auditorias = []
    # =========================================================
    # RPBI
    # =========================================================
    rpbi_items = por_codigo(items, {CODIGO_RPBI})
    rpbi_count = len(rpbi_items)

    if dias is not None and dias > 0:
        rpbi_esperado = 1 + (max(dias - 1, 0) // DIAS_RPBI_ADICIONAL)

    elif dias == 0:
        rpbi_esperado = 1

    else:
        rpbi_esperado = 1

    if rpbi_count == 0:
        status = (
            "FALTA cargo de RPBI — toda cuenta debe tener mínimo 1 "
            f"({CODIGO_RPBI})"
        )
        clase = "err"

    elif rpbi_count < rpbi_esperado:
        status = (
            f"insuficiente — {rpbi_count} cargo(s) para "
            f"{dias if dias is not None else '?'} día(s); "
            f"se esperan {rpbi_esperado}"
        )
        clase = "err"

    elif rpbi_count == rpbi_esperado:
        status = (
            f"ok — {rpbi_count} cargo(s) para "
            f"{dias if dias is not None else '?'} día(s)"
        )
        clase = "ok"

    else:
        status = (
            f"{rpbi_count} cargo(s) para "
            f"{dias if dias is not None else '?'} día(s); "
            f"se esperaban {rpbi_esperado}"
        )
        clase = "warn"

    auditorias.append({
        "categoria": "Estancia",
        "key": "rpbi",
        "label": "Disposición de RPBI",
        "tipo": "numerico",
        "unidad": "cargo(s)",
        "cobrado": float(rpbi_count),
        "esperado": float(rpbi_esperado),
        "status": status,
        "diff": None,
        "clase": clase,
        "items_cobrados": rpbi_items,
        "items_esperados": [],
        "nota_auditoria": (
            "Regla: toda cuenta (particular, convenio o seguro) debe tener mínimo "
            "1 cargo de RPBI al ingreso a habitación; un cargo adicional por cada "
            f"{DIAS_RPBI_ADICIONAL} días completos posteriores. "
            f"Estancia: {dias if dias is not None else '?'} día(s)."
        ),
    })

    # =========================================================
    # Días de habitación
    # =========================================================
    habitacion_items = por_codigo(items, CODIGOS_HABITACION)
    habitacion_cobrado = len(habitacion_items)

    hay_habitacion_ambulatoria = any(
        item["codigo"] == "HOS-0000003"
        for item in habitacion_items
    )

    if hay_habitacion_ambulatoria:
        habitacion_esperada = 1.0
        nota_habitacion = (
            "Cuenta con habitación ambulatoria (HOS-0000003): se espera 1 cargo "
            "aunque la estancia calculada sea 0 noches."
        )

    elif dias is not None:
        habitacion_esperada = float(dias)
        nota_habitacion = (
            f"Ingreso {data['fecha_ingreso']} → egreso {data['fecha_egreso']} "
            f"= {dias} noche(s). Confirmar política de cobro en paquetes/convenios "
            "si existe diferencia."
        )

    else:
        habitacion_esperada = None
        nota_habitacion = (
            "Sin fechas de estancia suficientes para calcular días esperados."
        )

    if habitacion_items or dias is not None:
        status, diff, clase = evaluar(
            float(habitacion_cobrado),
            habitacion_esperada,
            0,
        )

        if clase == "err":
            clase = "warn"
            status = "verificar — " + status

        auditorias.append({
            "categoria": "Estancia",
            "key": "habitacion",
            "label": "Días de habitación",
            "tipo": "numerico",
            "unidad": "días",
            "cobrado": float(habitacion_cobrado),
            "esperado": habitacion_esperada,
            "status": status,
            "diff": diff,
            "clase": clase,
            "items_cobrados": habitacion_items,
            "items_esperados": [],
            "nota_auditoria": nota_habitacion,
        })

    # =========================================================
    # Bomba de infusión por estancia
    # =========================================================
    bomba_items = por_codigo(items, {CODIGO_BOMBA})
    bomba_cobrado = len(bomba_items)

    if bomba_items:
        limite = dias if dias else None

        if limite and bomba_cobrado > limite:
            status = f"cobradas {bomba_cobrado} de {limite} días — revisar"
            clase = "warn"

        elif limite:
            status = f"ok — {bomba_cobrado} de {limite} días"
            clase = "ok"

        else:
            status = f"{bomba_cobrado} cargo(s)"
            clase = "gray"

        auditorias.append({
            "categoria": "Estancia",
            "key": "bomba",
            "label": "Bomba de infusión",
            "tipo": "numerico",
            "unidad": "días",
            "cobrado": float(bomba_cobrado),
            "esperado": float(dias) if dias is not None else None,
            "status": status,
            "diff": None,
            "clase": clase,
            "items_cobrados": bomba_items,
            "items_esperados": [],
            "nota_auditoria": f"Cargos de {CODIGO_BOMBA} vs días de estancia.",
        })

    # =========================================================
    # Dietas
    # =========================================================
    dieta_items = [
        item for item in items
        if item["codigo"].startswith("NUT-")
    ]

    dieta_cobrado = sum(item["cantidad"] for item in dieta_items)

    if dieta_items and dias:
        max_esperado = dias * 4

        if dieta_cobrado > max_esperado:
            status = f"{dieta_cobrado:.0f} dietas para {dias} día(s) — revisar"
            clase = "warn"

        else:
            status = f"{dieta_cobrado:.0f} dietas en {dias} día(s) — normal"
            clase = "ok"

        auditorias.append({
            "categoria": "Estancia",
            "key": "dietas",
            "label": "Dietas",
            "tipo": "numerico",
            "unidad": "servicios",
            "cobrado": dieta_cobrado,
            "esperado": None,
            "status": status,
            "diff": None,
            "clase": clase,
            "items_cobrados": dieta_items,
            "items_esperados": [],
            "nota_auditoria": (
                f"Máximo razonable: {dias} día(s) × 4 = {dias * 4} servicios. "
                f"Se cobraron {dieta_cobrado:.0f}."
            ),
        })


    return auditorias
