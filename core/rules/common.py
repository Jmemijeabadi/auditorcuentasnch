# core/rules/common.py

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


def precio_neto_promedio(items: list):
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


def calcular_monto_diff(diff, items_cobrados):
    """
    Estima el monto económico de una diferencia numérica.

    - diff > 0: posible sobrecobro.
    - diff < 0: posible faltante.
    - Si no hay precio de referencia, retorna None.
    """
    if diff is None or abs(diff) < 0.001:
        return None

    precio = precio_neto_promedio(items_cobrados)

    if precio is None:
        return None

    return abs(diff) * precio


def por_codigo(items: list, codigos: set, area: str = None):
    resultado = [item for item in items if item["codigo"] in codigos]

    if area:
        resultado = [item for item in resultado if item["area"] == area]

    return resultado


def contiene_palabra(descripcion: str, palabras: set) -> bool:
    descripcion_norm = normalizar(descripcion)
    return any(palabra in descripcion_norm for palabra in palabras)


def agregar_montos_estimados(auditorias: list) -> list:
    """
    Agrega monto_diff a auditorías numéricas con diferencia y evidencia cobrable.
    """
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
        auditoria["monto_diff"] = calcular_monto_diff(diff, items_ref)

    return auditorias
