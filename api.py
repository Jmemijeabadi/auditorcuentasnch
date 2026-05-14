# api.py

import hashlib
from datetime import datetime
from typing import Annotated

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

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


def ejecutar_auditoria(archivos_bytes: list, tolerancia: float = 0.01):
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

    total_errores = sum(
        sum(1 for a in auditorias if a["clase"] == "err")
        for auditorias in todas_auditorias.values()
    )

    total_advertencias = sum(
        sum(1 for a in auditorias if a["clase"] == "warn")
        for auditorias in todas_auditorias.values()
    )

    cuentas_con_diferencias = sum(
        1
        for auditorias in todas_auditorias.values()
        if estado_global(auditorias)[1] in ("err", "warn")
    )

    monto_global = sum(
        a.get("monto_diff") or 0
        for auditorias in todas_auditorias.values()
        for a in auditorias
        if a.get("clase") in ("err", "warn") and a.get("monto_diff")
    )

    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "hash_archivos": hash_archivos(archivos_bytes),
        "tolerancia": tolerancia,
        "avisos": avisos,
        "resumen": {
            "total_cuentas": len(cuentas),
            "cuentas_con_diferencias": cuentas_con_diferencias,
            "total_errores": total_errores,
            "total_advertencias": total_advertencias,
            "monto_global": monto_global,
        },
        "cuentas": resumen_cuentas,
        "auditorias": todas_auditorias,
    }


def _resumir_items(items: list, limite: int = 5):
    """
    Resume evidencia para no mandar JSON enorme al agente.
    """
    resumen = []

    for item in (items or [])[:limite]:
        resumen.append({
            "area": item.get("area"),
            "codigo": item.get("codigo"),
            "descripcion": item.get("descripcion"),
            "cantidad": item.get("cantidad"),
            "subtotal": item.get("subtotal"),
            "fecha": item.get("fecha"),
            "folio": item.get("folio"),
            "archivo": item.get("archivo"),
        })

    return resumen


def _hallazgo_simple(cuenta: str, auditoria: dict):
    """
    Convierte una auditoría completa en un hallazgo simple para agente.
    """
    return {
        "cuenta": cuenta,
        "categoria": auditoria.get("categoria"),
        "key": auditoria.get("key"),
        "label": auditoria.get("label"),
        "severidad": auditoria.get("clase"),
        "resultado": auditoria.get("status"),
        "tipo": auditoria.get("tipo"),
        "unidad": auditoria.get("unidad"),
        "cobrado": auditoria.get("cobrado"),
        "esperado": auditoria.get("esperado"),
        "diferencia": auditoria.get("diff"),
        "monto_estimado": auditoria.get("monto_diff"),
        "nota_auditoria": auditoria.get("nota_auditoria"),
        "evidencia_cobrada": _resumir_items(auditoria.get("items_cobrados", [])),
        "evidencia_esperada": auditoria.get("items_esperados", [])[:5],
    }


def _generar_recomendacion_operativa(errores: list, advertencias: list):
    """
    Genera una recomendación simple para el flujo operativo.
    """
    if errores:
        return {
            "accion": "revisar_y_corregir_antes_de_cerrar_cuenta",
            "prioridad": "alta",
            "mensaje": (
                f"Se detectaron {len(errores)} error(es) crítico(s). "
                "La cuenta requiere revisión/corrección antes de cierre."
            ),
        }

    if advertencias:
        return {
            "accion": "revision_dirigida",
            "prioridad": "media",
            "mensaje": (
                f"Se detectaron {len(advertencias)} advertencia(s). "
                "No necesariamente son errores financieros, pero requieren validación del área."
            ),
        }

    return {
        "accion": "sin_diferencias_detectadas",
        "prioridad": "baja",
        "mensaje": "No se detectaron errores críticos ni advertencias.",
    }


def _construir_respuesta_simple(resultado_full: dict):
    """
    Construye una respuesta compacta para OpenClaw/agentes.
    """
    hallazgos = []

    for cuenta, auditorias in resultado_full.get("auditorias", {}).items():
        for auditoria in auditorias:
            if auditoria.get("clase") in ("err", "warn"):
                hallazgos.append(_hallazgo_simple(cuenta, auditoria))

    errores = [
        hallazgo for hallazgo in hallazgos
        if hallazgo["severidad"] == "err"
    ]

    advertencias = [
        hallazgo for hallazgo in hallazgos
        if hallazgo["severidad"] == "warn"
    ]

    return {
        "status": resultado_full.get("status"),
        "timestamp": resultado_full.get("timestamp"),
        "hash_archivos": resultado_full.get("hash_archivos"),
        "tolerancia": resultado_full.get("tolerancia"),
        "resumen": resultado_full.get("resumen"),
        "cuentas": resultado_full.get("cuentas"),
        "avisos": resultado_full.get("avisos"),
        "hallazgos": {
            "total": len(hallazgos),
            "errores_criticos": errores,
            "advertencias": advertencias,
        },
        "recomendacion_operativa": _generar_recomendacion_operativa(
            errores,
            advertencias,
        ),
    }


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


@app.get("/test-upload", response_class=HTMLResponse)
def test_upload_form():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Test Auditor Hospitalario API</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 760px;
                margin: 40px auto;
                color: #222;
            }
            .box {
                border: 1px solid #ddd;
                border-radius: 12px;
                padding: 24px;
                background: #fafafa;
            }
            input, button {
                font-size: 15px;
                margin-top: 10px;
            }
            button {
                padding: 10px 18px;
                border-radius: 8px;
                border: 0;
                background: #185FA5;
                color: white;
                cursor: pointer;
            }
        </style>
    </head>
    <body>
        <h1>🏥 Auditor Hospitalario API</h1>
        <p>Este formulario devuelve la auditoría completa en JSON.</p>
        <div class="box">
            <form action="/audit" enctype="multipart/form-data" method="post">
                <label><b>Tolerancia:</b></label><br>
                <input name="tolerancia" type="number" step="0.01" value="0.01"><br><br>

                <label><b>Selecciona PDFs:</b></label><br>
                <input name="files" type="file" accept="application/pdf" multiple><br><br>

                <button type="submit">Auditar completo</button>
            </form>
        </div>
    </body>
    </html>
    """


@app.get("/test-upload-simple", response_class=HTMLResponse)
def test_upload_simple_form():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Test Auditor Hospitalario API Simple</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 760px;
                margin: 40px auto;
                color: #222;
            }
            .box {
                border: 1px solid #ddd;
                border-radius: 12px;
                padding: 24px;
                background: #fafafa;
            }
            input, button {
                font-size: 15px;
                margin-top: 10px;
            }
            button {
                padding: 10px 18px;
                border-radius: 8px;
                border: 0;
                background: #185FA5;
                color: white;
                cursor: pointer;
            }
        </style>
    </head>
    <body>
        <h1>🏥 Auditor Hospitalario API — Simple</h1>
        <p>Este formulario devuelve una respuesta compacta para agente/OpenClaw.</p>
        <div class="box">
            <form action="/audit-simple" enctype="multipart/form-data" method="post">
                <label><b>Tolerancia:</b></label><br>
                <input name="tolerancia" type="number" step="0.01" value="0.01"><br><br>

                <label><b>Selecciona PDFs:</b></label><br>
                <input name="files" type="file" accept="application/pdf" multiple><br><br>

                <button type="submit">Auditar versión simple</button>
            </form>
        </div>
    </body>
    </html>
    """


@app.post("/audit")
async def audit_files(
    files: Annotated[
        list[UploadFile],
        File(description="PDFs de la cuenta hospitalaria"),
    ],
    tolerancia: float = Form(0.01),
):
    archivos_bytes = []

    for file in files:
        contenido = await file.read()
        archivos_bytes.append((file.filename, contenido))

    return ejecutar_auditoria(archivos_bytes, tolerancia)


@app.post("/audit-simple")
async def audit_files_simple(
    files: Annotated[
        list[UploadFile],
        File(description="PDFs de la cuenta hospitalaria"),
    ],
    tolerancia: float = Form(0.01),
):
    archivos_bytes = []

    for file in files:
        contenido = await file.read()
        archivos_bytes.append((file.filename, contenido))

    resultado_full = ejecutar_auditoria(archivos_bytes, tolerancia)

    return _construir_respuesta_simple(resultado_full)