# core/rules/engine.py

from core.rules.common import agregar_montos_estimados
from core.rules.tiempos import auditar_tiempos
from core.rules.oxigeno import auditar_oxigeno
from core.rules.sala_quirofano import auditar_sala_quirofano
from core.rules.equipos import auditar_equipos
from core.rules.accesorios import auditar_accesorios
from core.rules.recuperacion import auditar_recuperacion
from core.rules.verificaciones import auditar_verificaciones
from core.rules.estancia import auditar_estancia


def construir_auditorias(data: dict, tolerancia: float) -> list:
    items = data["todos_los_items"]
    sc = data["servicios_cirugia"] or {}
    nota = data["nota_postqx"] or {}
    dias = data["dias_estancia"]
    seguro = data.get("seguro", "desconocido")

    auditorias = []
    auditorias.extend(auditar_tiempos(data, items, sc, seguro, tolerancia))
    auditorias.extend(auditar_oxigeno(data, items, sc, tolerancia))
    auditorias.extend(auditar_sala_quirofano(data, items, sc, tolerancia))
    auditorias.extend(auditar_equipos(data, items, sc))
    auditorias.extend(auditar_accesorios(data, items, sc))
    auditorias.extend(auditar_recuperacion(data, items, sc))
    auditorias.extend(auditar_verificaciones(data, items, nota))
    auditorias.extend(auditar_estancia(data, items, dias, tolerancia))

    return agregar_montos_estimados(auditorias)
