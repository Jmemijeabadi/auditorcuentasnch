# core/rules/equipos.py

from core.config_codigos import SERVICIOS_BINARIOS_DEF
from core.rules.common import por_codigo


def auditar_equipos(data: dict, items: list, sc: dict) -> list:
    auditorias = []
    # =========================================================
    # Servicios binarios
    # =========================================================
    for key, label, _, codigos_cuenta, area_cuenta in SERVICIOS_BINARIOS_DEF:
        marcado = sc.get("servicios_marcados", {}).get(key, False) if sc else False
        cobrado_items = por_codigo(items, codigos_cuenta, area_cuenta)
        cobrado_bool = len(cobrado_items) > 0

        if not marcado and not cobrado_bool:
            continue

        if marcado and cobrado_bool:
            status = "ok — documentado y cobrado"
            clase = "ok"

        elif marcado and not cobrado_bool:
            status = "documentado, no cobrado"
            clase = "gray"

        else:
            status = "cobrado sin documentar uso"
            clase = "err"

        auditorias.append({
            "categoria": "Equipos y servicios",
            "key": f"bin_{key}",
            "label": label,
            "tipo": "binario",
            "unidad": "",
            "cobrado": float(cobrado_bool),
            "esperado": float(marcado),
            "marcado": marcado,
            "cobrado_bool": cobrado_bool,
            "status": status,
            "diff": None,
            "clase": clase,
            "items_cobrados": cobrado_items,
            "items_esperados": [],
            "nota_auditoria": None,
        })


    return auditorias
