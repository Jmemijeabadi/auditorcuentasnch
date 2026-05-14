# core/rules/verificaciones.py

from core.config_codigos import PALABRAS_SANGRE, PALABRAS_PATOLOGIA
from core.rules.common import contiene_palabra


def auditar_verificaciones(data: dict, items: list, nota: dict) -> list:
    auditorias = []
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


    return auditorias
