# core/rules/accesorios.py

from core.config_codigos import (
    CODIGO_ELECTROCAUTERIO,
    CODIGO_LAPIZ_ELECTRO,
    CODIGO_PLACA_ELECTRO,
    CODIGO_BOMBA,
    CODIGO_EQUIPO_INFUSOMAT,
    CODIGO_MICROSCOPIO,
    CODIGO_FUNDA_MICROSCOPIO,
    CODIGO_ARCO_C,
    CODIGO_FUNDA_ARCO_C,
)
from core.rules.common import por_codigo


def auditar_accesorios(data: dict, items: list, sc: dict) -> list:
    auditorias = []
    # =========================================================
    # Electrocauterio + lápiz + placa
    # =========================================================
    electro_items = por_codigo(items, {CODIGO_ELECTROCAUTERIO}, "quirofano")

    if electro_items:
        lapiz_items = por_codigo(items, {CODIGO_LAPIZ_ELECTRO}, "quirofano")
        placa_items = por_codigo(items, {CODIGO_PLACA_ELECTRO}, "quirofano")

        faltantes = []

        if not lapiz_items:
            faltantes.append(f"lápiz ({CODIGO_LAPIZ_ELECTRO})")

        if not placa_items:
            faltantes.append(f"placa ({CODIGO_PLACA_ELECTRO})")

        if faltantes:
            status = f"falta(n): {', '.join(faltantes)}"
            clase = "err"

        else:
            status = "ok — electrocauterio, lápiz y placa presentes"
            clase = "ok"

        auditorias.append({
            "categoria": "Accesorios complementarios",
            "key": "electro_accesorios",
            "label": "Electrocauterio → lápiz + placa",
            "tipo": "informativo",
            "unidad": "",
            "cobrado": 0,
            "esperado": None,
            "status": status,
            "diff": None,
            "clase": clase,
            "items_cobrados": electro_items + lapiz_items + placa_items,
            "items_esperados": [],
            "nota_auditoria": (
                "Cuando se cobra electrocauterio, deben existir lápiz y placa."
            ),
        })

    # =========================================================
    # Bomba de infusión + equipo infusomat
    # =========================================================
    bomba_items_qx = por_codigo(items, {CODIGO_BOMBA})
    equipo_infusomat_items = por_codigo(items, {CODIGO_EQUIPO_INFUSOMAT})

    cantidad_bombas = round(
        sum(item.get("cantidad", 0) for item in bomba_items_qx),
        3,
    )

    cantidad_infusomat = round(
        sum(item.get("cantidad", 0) for item in equipo_infusomat_items),
        3,
    )

    if bomba_items_qx:
        if cantidad_infusomat == 0:
            status_bomba = (
                f"bomba cobrada sin equipo infusomat ({CODIGO_EQUIPO_INFUSOMAT})"
            )
            clase_bomba = "err"
            nota_bomba = (
                "Cada uso de bomba de infusión debe ir con equipo infusomat."
            )

        elif cantidad_infusomat < cantidad_bombas:
            status_bomba = (
                f"verificar — {cantidad_bombas:.0f} bomba(s) y "
                f"{cantidad_infusomat:.0f} equipo(s) infusomat"
            )
            clase_bomba = "warn"
            nota_bomba = (
                "La validación se realiza por cantidad. Si un solo equipo infusomat "
                "cubre varios días por continuidad clínica, confirmar con enfermería/almacén."
            )

        else:
            status_bomba = (
                f"ok — {cantidad_bombas:.0f} bomba(s), "
                f"{cantidad_infusomat:.0f} equipo(s)"
            )
            clase_bomba = "ok"
            nota_bomba = None

        auditorias.append({
            "categoria": "Accesorios complementarios",
            "key": "bomba_infusomat",
            "label": "Bomba de infusión → equipo infusomat",
            "tipo": "informativo",
            "unidad": "",
            "cobrado": cantidad_bombas,
            "esperado": cantidad_infusomat,
            "status": status_bomba,
            "diff": None,
            "clase": clase_bomba,
            "items_cobrados": bomba_items_qx + equipo_infusomat_items,
            "items_esperados": [],
            "nota_auditoria": nota_bomba,
        })

    # =========================================================
    # Microscopio + funda
    # =========================================================
    micro_items = por_codigo(items, {CODIGO_MICROSCOPIO}, "quirofano")
    funda_micro_items = por_codigo(items, {CODIGO_FUNDA_MICROSCOPIO}, "quirofano")

    micro_marcado = (
        sc.get("servicios_marcados", {}).get("microscopio", False)
        if sc else False
    )

    if micro_items or funda_micro_items or micro_marcado:
        if micro_items:
            if funda_micro_items:
                status = "ok — microscopio y funda presentes"
                clase = "ok"
            else:
                status = f"microscopio cobrado sin funda ({CODIGO_FUNDA_MICROSCOPIO})"
                clase = "err"

        elif funda_micro_items and not micro_marcado:
            status = (
                "funda de microscopio cobrada sin uso documentado de microscopio — "
                "verificar con el área"
            )
            clase = "warn"

        elif funda_micro_items and micro_marcado:
            status = (
                "funda presente y microscopio marcado en hoja de servicios "
                "pero no cobrado — confirmar con el área"
            )
            clase = "warn"

        else:
            status = (
                "microscopio marcado en hoja de servicios pero no cobrado — "
                "verificar con el área"
            )
            clase = "warn"

        auditorias.append({
            "categoria": "Accesorios complementarios",
            "key": "microscopio_funda",
            "label": "Microscopio ↔ funda",
            "tipo": "informativo",
            "unidad": "",
            "cobrado": 0,
            "esperado": None,
            "status": status,
            "diff": None,
            "clase": clase,
            "items_cobrados": micro_items + funda_micro_items,
            "items_esperados": [],
            "nota_auditoria": (
                "Validación bidireccional: el uso de microscopio debe ir con funda "
                "desechable, y la presencia de funda sin microscopio documentado "
                "se verifica con el área."
            ),
        })

    # =========================================================
    # Arco en C + funda
    # =========================================================
    arco_items = por_codigo(items, {CODIGO_ARCO_C}, "quirofano")
    funda_arco_items = por_codigo(items, {CODIGO_FUNDA_ARCO_C}, "quirofano")

    arco_marcado = (
        sc.get("servicios_marcados", {}).get("arco_c", False)
        if sc else False
    )

    if arco_items or funda_arco_items or arco_marcado:
        if arco_items:
            if funda_arco_items:
                status = "ok — arco en C y funda presentes"
                clase = "ok"
            else:
                status = f"arco en C cobrado sin funda ({CODIGO_FUNDA_ARCO_C})"
                clase = "err"

        elif funda_arco_items and not arco_marcado:
            status = (
                "funda de arco en C cobrada sin uso documentado de arco — "
                "verificar con el área"
            )
            clase = "warn"

        elif funda_arco_items and arco_marcado:
            status = (
                "funda presente y arco marcado en hoja de servicios "
                "pero no cobrado — confirmar con el área"
            )
            clase = "warn"

        else:
            status = (
                "arco en C marcado en hoja de servicios pero no cobrado — "
                "verificar con el área"
            )
            clase = "warn"

        auditorias.append({
            "categoria": "Accesorios complementarios",
            "key": "arco_funda",
            "label": "Arco en C ↔ funda",
            "tipo": "informativo",
            "unidad": "",
            "cobrado": 0,
            "esperado": None,
            "status": status,
            "diff": None,
            "clase": clase,
            "items_cobrados": arco_items + funda_arco_items,
            "items_esperados": [],
            "nota_auditoria": (
                "Validación bidireccional: el uso de arco en C debe ir con funda "
                "estéril desechable, y la presencia de funda sin arco documentado "
                "se verifica con el área."
            ),
        })


    return auditorias
