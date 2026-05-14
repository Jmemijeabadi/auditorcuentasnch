# api.py

import hashlib
from datetime import datetime
from typing import List

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

from core.consolidation import consolidar_por_cuenta_core
from core.rules.engine import construir_auditorias


app = FastAPI(
    title="Auditor Hospitalario API",
    version="0.1.0",
    description="API para auditar cuentas hospitalarias a partir de PDFs.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def hash_archivos(archivos_bytes: list) -> str:
    h = hashlib.sha256()

    for nombre, contenido in archivos_bytes:
        h.update(nombre.encode("utf-8"))
        h.update(str(len(contenido)).encode("utf-8"))
        h.update(contenido)

    return h.hexdigest()


def estado_global(auditorias: list):
    clases = [a["clase"] for a in auditorias]

    if "err" in clases:
        return "Con diferencias", "err"

    if "warn" in clases:
        return "Revisar", "warn"

    if "ok" in clases:
        return "Sin diferencias", "ok"

    return "Sin referencias", "gray"


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "Auditor Hospitalario API",
        "version": "0.1.0",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/audit")
async def audit_files(
    files: List[UploadFile] = File(...),
    tolerancia: float = 0.01,
):
    archivos_bytes = []

    for file in files:
        contenido = await file.read()
        archivos_bytes.append((file.filename, contenido))

    cuentas, avisos = consolidar_por_cuenta_core(archivos_bytes)

    todas_auditorias = {
        cuenta: construir_auditorias(data, tolerancia)
        for cuenta, data in cuentas.items()
    }

    resumen_cuentas = []

    for cuenta, data in cuentas.items():
        auditorias = todas_auditorias[cuenta]
        estado_txt, clase = estado_global(auditorias)

        errores = sum(1 for a in auditorias if a["clase"] == "err")
        advertencias = sum(1 for a in auditorias if a["clase"] == "warn")

        monto_hallazgos = sum(
            a.get("monto_diff") or 0
            for a in auditorias
            if a.get("clase") in ("err", "warn") and a.get("monto_diff")
        )

        resumen_cuentas.append({
            "cuenta": cuenta,
            "paciente": data.get("paciente"),
            "seguro": data.get("seguro"),
            "fecha_ingreso": data.get("fecha_ingreso"),
            "fecha_egreso": data.get("fecha_egreso"),
            "dias_estancia": data.get("dias_estancia"),
            "estado": estado_txt,
            "clase": clase,
            "errores": errores,
            "advertencias": advertencias,
            "monto_hallazgos": monto_hallazgos,
            "archivos": data.get("archivos", []),
        })

    total_cuentas = len(cuentas)

    total_errores = sum(
        sum(1 for a in auds if a["clase"] == "err")
        for auds in todas_auditorias.values()
    )

    total_advertencias = sum(
        sum(1 for a in auds if a["clase"] == "warn")
        for auds in todas_auditorias.values()
    )

    cuentas_con_diferencias = sum(
        1
        for auds in todas_auditorias.values()
        if estado_global(auds)[1] in ("err", "warn")
    )

    monto_global = sum(
        a.get("monto_diff") or 0
        for auds in todas_auditorias.values()
        for a in auds
        if a.get("clase") in ("err", "warn") and a.get("monto_diff")
    )

    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "hash_archivos": hash_archivos(archivos_bytes),
        "tolerancia": tolerancia,
        "avisos": avisos,
        "resumen": {
            "total_cuentas": total_cuentas,
            "cuentas_con_diferencias": cuentas_con_diferencias,
            "total_errores": total_errores,
            "total_advertencias": total_advertencias,
            "monto_global": monto_global,
        },
        "cuentas": resumen_cuentas,
        "auditorias": todas_auditorias,
    }
