# core/rules/recuperacion.py

from core.config_codigos import CODIGOS_OXIGENO
from core.rules.common import por_codigo


def auditar_recuperacion(data: dict, items: list, sc: dict) -> list:
    auditorias = []
    # =========================================================
    # Trío de recuperación
    # =========================================================
    recuperacion_sala = por_codigo(items, {"REC-0000001"}, "recuperacion")
    recuperacion_monitor = por_codigo(items, {"IBM-0000010"}, "recuperacion")
    recuperacion_oxigeno = por_codigo(items, CODIGOS_OXIGENO, "recuperacion")

    servicios_marcados = sc.get("servicios_marcados", {}) if sc else {}

    marcado_sala = servicios_marcados.get("sala_rec", False)
    marcado_monitor = servicios_marcados.get("monitor_rec", False)
    marcado_oxigeno = sc.get("oxigeno_rec", 0) > 0 if sc else False

    cobrado_dict = {
        "Sala de recuperación": len(recuperacion_sala) > 0,
        "Monitor SV": len(recuperacion_monitor) > 0,
        "Oxígeno recuperación": len(recuperacion_oxigeno) > 0,
    }

    marcado_dict = {
        "Sala de recuperación": marcado_sala,
        "Monitor SV": marcado_monitor,
        "Oxígeno recuperación": marcado_oxigeno,
    }

    hay_actividad = any(cobrado_dict.values()) or any(marcado_dict.values())

    if hay_actividad:
        marcados_no_cobrados = [
            concepto
            for concepto in cobrado_dict
            if marcado_dict[concepto] and not cobrado_dict[concepto]
        ]

        cobrados_no_marcados = [
            concepto
            for concepto in cobrado_dict
            if cobrado_dict[concepto] and not marcado_dict[concepto]
        ]

        if not marcados_no_cobrados and not cobrados_no_marcados:
            presentes = [
                concepto
                for concepto, existe in cobrado_dict.items()
                if existe
            ]

            if len(presentes) == 3:
                status = "ok — los 3 conceptos coinciden entre hoja de servicios y cuenta"
            else:
                status = (
                    "ok — coinciden hoja vs cuenta "
                    f"({', '.join(presentes) or 'sin cargos'})"
                )

            clase = "ok"
            nota_trio = None

        else:
            partes = []

            if marcados_no_cobrados:
                partes.append(
                    "marcado(s) en hoja pero no cobrado(s): "
                    + ", ".join(marcados_no_cobrados)
                )

            if cobrados_no_marcados:
                partes.append(
                    "cobrado(s) sin estar marcado(s) en hoja: "
                    + ", ".join(cobrados_no_marcados)
                )

            status = "discrepancia — " + "; ".join(partes)
            clase = "warn"
            nota_trio = (
                "Comparación entre hoja de servicios y estado de cuenta. "
                "Puede ser que enfermería haya omitido marcarlo o cargarlo. "
                "Confirmar con el área (grupo de WhatsApp)."
            )

        auditorias.append({
            "categoria": "Consistencia de servicios",
            "key": "trio_recuperacion",
            "label": "Trío de recuperación (sala + monitor + oxígeno)",
            "tipo": "informativo",
            "unidad": "",
            "cobrado": 0,
            "esperado": None,
            "status": status,
            "diff": None,
            "clase": clase,
            "items_cobrados": (
                recuperacion_sala
                + recuperacion_monitor
                + recuperacion_oxigeno
            ),
            "items_esperados": [],
            "nota_auditoria": nota_trio,
        })


    return auditorias
