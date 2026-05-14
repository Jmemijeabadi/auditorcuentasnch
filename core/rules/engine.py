from core.config_codigos import *
from core.utils import normalizar


def evaluar(cobrado, esperado, tolerancia: float = 0.01):
    if esperado is None:
        return "sin regla", None, "gray"

    diff = round(cobrado - esperado, 3)

    if abs(diff) <= tolerancia:
        return "ok", diff, "ok"

    if diff < 0:
        return f"faltan {abs(diff):.2f}", diff, "err"

    return f"sobran {abs(diff):.2f}", diff, "warn"


def _precio_neto_promedio(items: list):
    """
    Precio neto promedio post-descuento por unidad.
    Retorna None si no es calculable.
    """
    if not items:
        return None

    total_cantidad = sum(item.get("cantidad", 0) for item in items)
    total_subtotal = sum(item.get("subtotal", 0) for item in items)

    if total_cantidad <= 0:
        return None

    return total_subtotal / total_cantidad


def _calcular_monto_diff(diff, items_cobrados):
    """
    Estima el monto económico de una diferencia numérica.

    - diff > 0: posible sobrecobro.
    - diff < 0: posible faltante.
    - Si no hay precio de referencia, retorna None.
    """
    if diff is None or abs(diff) < 0.001:
        return None

    precio = _precio_neto_promedio(items_cobrados)

    if precio is None:
        return None

    return abs(diff) * precio


def construir_auditorias(data: dict, tolerancia: float) -> list:
    items = data["todos_los_items"]
    sc = data["servicios_cirugia"] or {}
    nota = data["nota_postqx"] or {}
    dias = data["dias_estancia"]
    seguro = data.get("seguro", "desconocido")

    def por_codigo(codigos: set, area: str = None):
        resultado = [item for item in items if item["codigo"] in codigos]

        if area:
            resultado = [item for item in resultado if item["area"] == area]

        return resultado

    def contiene_palabra(descripcion: str, palabras: set) -> bool:
        descripcion_norm = normalizar(descripcion)
        return any(palabra in descripcion_norm for palabra in palabras)

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

    # =========================================================
    # Oxígeno QX
    # =========================================================
    oxigeno_qx_items = por_codigo(CODIGOS_OXIGENO, "quirofano")
    cobrado_qx = round(sum(item["cantidad"] for item in oxigeno_qx_items), 3)

    sala_items_qx = por_codigo(
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
    oxigeno_rec_items = por_codigo(CODIGOS_OXIGENO, "recuperacion")
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
    oxigeno_hosp_items = por_codigo(CODIGOS_OXIGENO, "hospitalizacion")

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

    # =========================================================
    # Sala quirúrgica
    # =========================================================
    sala_items = por_codigo(
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

    # =========================================================
    # Servicios binarios
    # =========================================================
    for key, label, _, codigos_cuenta, area_cuenta in SERVICIOS_BINARIOS_DEF:
        marcado = sc.get("servicios_marcados", {}).get(key, False) if sc else False
        cobrado_items = por_codigo(codigos_cuenta, area_cuenta)
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

    # =========================================================
    # Electrocauterio + lápiz + placa
    # =========================================================
    electro_items = por_codigo({CODIGO_ELECTROCAUTERIO}, "quirofano")

    if electro_items:
        lapiz_items = por_codigo({CODIGO_LAPIZ_ELECTRO}, "quirofano")
        placa_items = por_codigo({CODIGO_PLACA_ELECTRO}, "quirofano")

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
    bomba_items_qx = por_codigo({CODIGO_BOMBA})
    equipo_infusomat_items = por_codigo({CODIGO_EQUIPO_INFUSOMAT})

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
    micro_items = por_codigo({CODIGO_MICROSCOPIO}, "quirofano")
    funda_micro_items = por_codigo({CODIGO_FUNDA_MICROSCOPIO}, "quirofano")

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
    arco_items = por_codigo({CODIGO_ARCO_C}, "quirofano")
    funda_arco_items = por_codigo({CODIGO_FUNDA_ARCO_C}, "quirofano")

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

    # =========================================================
    # Trío de recuperación
    # =========================================================
    recuperacion_sala = por_codigo({"REC-0000001"}, "recuperacion")
    recuperacion_monitor = por_codigo({"IBM-0000010"}, "recuperacion")
    recuperacion_oxigeno = por_codigo(CODIGOS_OXIGENO, "recuperacion")

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

    # =========================================================
    # Hemotransfusión
    # =========================================================
    hemotransfusion = nota.get("hemotransfusion")

    sangre_items = [
        item for item in items
        if contiene_palabra(item["descripcion"], PALABRAS_SANGRE)
    ]

    if hemotransfusion is not None or sangre_items:
        if hemotransfusion is False and not sangre_items:
            status = "ok — nota dice NO y no hay cargos"
            clase = "ok"

        elif hemotransfusion is False and sangre_items:
            status = "nota dice NO pero hay cargos — verificar"
            clase = "err"

        elif hemotransfusion is True and sangre_items:
            status = "verificar con equipo médico — nota dice SÍ y hay cargos de sangre"
            clase = "gray"

        elif hemotransfusion is True and not sangre_items:
            status = "verificar con equipo médico — nota dice SÍ pero no hay cargos de sangre"
            clase = "gray"

        else:
            status = "sin información en nota post-qx"
            clase = "gray"

        auditorias.append({
            "categoria": "Verificaciones negativas",
            "key": "hemotransfusion",
            "label": "Hemotransfusión",
            "tipo": "negativo",
            "unidad": "",
            "cobrado": float(len(sangre_items)),
            "esperado": None,
            "status": status,
            "diff": None,
            "clase": clase,
            "items_cobrados": sangre_items,
            "items_esperados": [],
            "nota_auditoria": (
                "Nota post-quirúrgica: hemotransfusión = "
                f"{'SÍ' if hemotransfusion else 'NO' if hemotransfusion is False else 'no documentada'}. "
                "Este punto se deja como verificación médica cuando la nota indica SÍ; "
                "no se considera diferencia financiera automática."
            ),
        })

    # =========================================================
    # Histopatológico
    # =========================================================
    histopatologico = nota.get("histopatologico")

    patologia_items = [
        item for item in items
        if contiene_palabra(item["descripcion"], PALABRAS_PATOLOGIA)
    ]

    if histopatologico is not None or patologia_items:
        if histopatologico is False and not patologia_items:
            status = "ok — nota dice NO y no hay cargos"
            clase = "ok"

        elif histopatologico is False and patologia_items:
            status = "nota dice NO pero hay cargos de patología — verificar"
            clase = "err"

        elif histopatologico is True:
            status = "nota dice SÍ — verificar cargos concordantes"
            clase = "warn"

        else:
            status = "sin información en nota post-qx"
            clase = "gray"

        auditorias.append({
            "categoria": "Verificaciones negativas",
            "key": "histopatologico",
            "label": "Histopatológico",
            "tipo": "negativo",
            "unidad": "",
            "cobrado": float(len(patologia_items)),
            "esperado": None,
            "status": status,
            "diff": None,
            "clase": clase,
            "items_cobrados": patologia_items,
            "items_esperados": [],
            "nota_auditoria": (
                "Nota post-quirúrgica: histopatológico = "
                f"{'SÍ' if histopatologico else 'NO' if histopatologico is False else 'no documentado'}."
            ),
        })

    # =========================================================
    # RPBI
    # =========================================================
    rpbi_items = por_codigo({CODIGO_RPBI})
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
    habitacion_items = por_codigo(CODIGOS_HABITACION)
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
    bomba_items = por_codigo({CODIGO_BOMBA})
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

    # =========================================================
    # Post-proceso: monto económico estimado
    # =========================================================
    for auditoria in auditorias:
        auditoria["monto_diff"] = None

        if auditoria.get("tipo") != "numerico":
            continue

        if auditoria.get("clase") not in ("err", "warn"):
            continue

        diff = auditoria.get("diff")

        if diff is None:
            continue

        items_ref = auditoria.get("items_cobrados") or []

        auditoria["monto_diff"] = _calcular_monto_diff(diff, items_ref)

    return auditorias
