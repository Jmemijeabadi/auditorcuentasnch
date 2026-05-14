# core/rules/tiempos.py

from core.utils import normalizar


def auditar_tiempos(data: dict, items: list, sc: dict, seguro: str, tolerancia: float) -> list:
    auditorias = []
    # =========================================================
    # Múltiples cirugías
    # =========================================================
    num_cirugias = data.get("num_cirugias", 0)

    if num_cirugias > 1:
        detalles = data.get("cirugias_detalle", [])

        detalle_txt = "; ".join(
            f"Cx{detalle['cirugia_num']}: "
            f"{detalle.get('ingreso', '?')}→{detalle.get('egreso', '?')} "
            f"({detalle.get('hora_total', '?')} hrs)"
            for detalle in detalles
        )

        auditorias.append({
            "categoria": "Validación de tiempos",
            "key": "multi_cirugia",
            "label": f"Múltiples cirugías detectadas ({num_cirugias})",
            "tipo": "informativo",
            "unidad": "",
            "cobrado": 0,
            "esperado": None,
            "status": (
                f"{num_cirugias} eventos quirúrgicos — "
                "los totales son acumulados, revisar individualmente"
            ),
            "diff": None,
            "clase": "warn",
            "items_cobrados": [],
            "items_esperados": [],
            "nota_auditoria": (
                f"Se encontraron {num_cirugias} hojas de servicios de cirugía. "
                f"Los datos de oxígeno, sala y equipos se acumularon. "
                f"Detalle: {detalle_txt}"
            ),
        })

    # =========================================================
    # Hora total QX vs ingreso/egreso de sala
    # =========================================================
    if sc:
        ingreso = sc.get("ingreso_sala")
        egreso = sc.get("egreso_sala")
        hora_total = sc.get("hora_total_qx")
        horas_minuto_21 = sc.get("horas_calculadas_m21")
        minutos_totales = sc.get("minutos_totales")

        if ingreso and egreso and hora_total is not None and horas_minuto_21 is not None:
            if abs(hora_total - horas_minuto_21) < 0.01:
                status = (
                    f"ok — {ingreso}→{egreso} = "
                    f"{minutos_totales:.0f} min → "
                    f"{horas_minuto_21:.0f} hrs (regla min 21)"
                )
                clase = "ok"
            else:
                status = (
                    f"HORA TOTAL ({hora_total:.0f}) ≠ calculado "
                    f"({horas_minuto_21:.0f}) desde {ingreso}→{egreso} "
                    f"({minutos_totales:.0f} min)"
                )
                clase = "warn"

            auditorias.append({
                "categoria": "Validación de tiempos",
                "key": "hora_total_vs_tiempos",
                "label": "Hora total QX vs ingreso/egreso de sala (regla minuto 21)",
                "tipo": "informativo",
                "unidad": "hrs",
                "cobrado": hora_total,
                "esperado": horas_minuto_21,
                "status": status,
                "diff": round(hora_total - horas_minuto_21, 1),
                "clase": clase,
                "items_cobrados": [],
                "items_esperados": [],
                "nota_auditoria": (
                    f"Ingreso a sala: {ingreso} · "
                    f"Egreso de sala: {egreso} · "
                    f"Tiempo real: {minutos_totales:.0f} min · "
                    "Regla minuto 21: ≥21 min se cobra hora completa."
                ),
            })

        elif ingreso is None and hora_total is not None:
            auditorias.append({
                "categoria": "Validación de tiempos",
                "key": "hora_total_vs_tiempos",
                "label": "Hora total QX vs ingreso/egreso de sala",
                "tipo": "informativo",
                "unidad": "",
                "cobrado": hora_total,
                "esperado": None,
                "status": "sin datos de ingreso/egreso de sala",
                "diff": None,
                "clase": "gray",
                "items_cobrados": [],
                "items_esperados": [],
                "nota_auditoria": (
                    "No se encontraron tiempos de ingreso/egreso en la hoja de servicios."
                ),
            })

    # =========================================================
    # Máquina de anestesia
    # =========================================================
    if sc:
        maquina_marcada = sc.get("maquina_anestesia", False)
        es_particular = "particular" in (seguro or "")

        palabras_maquina = {
            "maquina de anestesia",
            "maquina anestesia",
            "anesthesia machine",
        }

        maquina_items = [
            item for item in items
            if any(
                palabra in normalizar(item["descripcion"])
                for palabra in palabras_maquina
            )
        ]

        maquina_cobrada = len(maquina_items) > 0

        if maquina_marcada or maquina_cobrada:
            if es_particular and maquina_cobrada:
                status = "ERROR — paciente PARTICULAR con cargo de máquina de anestesia"
                clase = "err"

            elif es_particular and not maquina_cobrada:
                status = "ok — documentada en servicios, no cobrada (particular)"
                clase = "ok"

            elif not es_particular and maquina_cobrada:
                status = "ok — paciente con seguro, máquina cobrada"
                clase = "ok"

            elif not es_particular and maquina_marcada and not maquina_cobrada:
                status = "documentada pero no cobrada — paciente con seguro, verificar"
                clase = "warn"

            else:
                status = (
                    f"documentada: {'sí' if maquina_marcada else 'no'}, "
                    f"cobrada: {'sí' if maquina_cobrada else 'no'}"
                )
                clase = "gray"

            auditorias.append({
                "categoria": "Validación de tiempos",
                "key": "maquina_anestesia",
                "label": "Máquina de anestesia",
                "tipo": "informativo",
                "unidad": "",
                "cobrado": float(maquina_cobrada),
                "esperado": None,
                "status": status,
                "diff": None,
                "clase": clase,
                "items_cobrados": maquina_items,
                "items_esperados": [],
                "nota_auditoria": (
                    f"Seguro: {seguro or 'no identificado'}. "
                    "Regla: no se cobra en particulares; en convenios/seguros, "
                    "si está documentada y no cobrada, verificar."
                ),
            })


    return auditorias
