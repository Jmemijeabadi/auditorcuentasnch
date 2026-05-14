CODIGOS_OXIGENO = {"APR-0000003"}

CODIGO_SALA_NORMAL = "QRF-0000002"
CODIGO_SALA_ADICIONAL = "QRF-0000001"

CODIGO_SEVOFLURANO = "FAR-0000069"

CODIGO_ELECTROCAUTERIO = "IBM-0000032"
CODIGO_LAPIZ_ELECTRO = "ALM-0001320"
CODIGO_PLACA_ELECTRO = "ALM-0000753"

CODIGO_BOMBA = "IBM-0000001"
CODIGO_EQUIPO_INFUSOMAT = "ALM-0000869"

CODIGO_MICROSCOPIO = "IBM-0000034"
CODIGO_FUNDA_MICROSCOPIO = "ALM-0000878"

CODIGO_ARCO_C = "IBM-0000023"
CODIGO_FUNDA_ARCO_C = "ALM-0000877"

CODIGO_RPBI = "ENF-0000003"
DIAS_RPBI_ADICIONAL = 7

PALABRAS_SANGRE = {
    "paquete globular",
    "plasma fresco",
    "plaquetas",
    "sangre total",
    "concentrado eritrocitario",
    "hemoderivado",
    "eritrocito",
    "globulos rojos",
    "crioprecipitado",
}

PALABRAS_PATOLOGIA = {
    "patologia",
    "histopatolog",
    "biopsia",
    "estudio histol",
}

CODIGOS_HABITACION = {"HOS-0000001", "HOS-0000003"}

SERVICIOS_BINARIOS_DEF = [
    (
        "electrocauterio",
        "Electrocauterio",
        r"\bx\s+electrocauterio",
        {"IBM-0000032"},
        "quirofano",
    ),
    (
        "aspirador",
        "Torre de aspiración",
        r"\bx\s+torre de aspiracion",
        {"IBM-0000008"},
        "quirofano",
    ),
    (
        "monitor_qx",
        "Monitor QX",
        r"\bx\s+monitor sv\s*qx",
        {"IBM-0000035"},
        "quirofano",
    ),
    (
        "sala_rec",
        "Sala de recuperación",
        r"\bx\s+sala de recuperacion\b",
        {"REC-0000001"},
        "recuperacion",
    ),
    (
        "monitor_rec",
        "Monitor SV recuperación",
        r"\bx\s+monitor sv recuperacion",
        {"IBM-0000010"},
        "recuperacion",
    ),
    (
        "microscopio",
        "Microscopio-TIVATO",
        r"\bx\s+microscopio",
        {"IBM-0000034"},
        "quirofano",
    ),
    (
        "arco_c",
        "Arco en C",
        r"\bx\s+arco en c",
        {"IBM-0000023"},
        "quirofano",
    ),
]
