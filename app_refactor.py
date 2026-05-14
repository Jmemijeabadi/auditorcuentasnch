import streamlit as st
import pandas as pd
import smtplib
import hashlib
import logging

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

from core.utils import h
from core.consolidation import consolidar_por_cuenta_core
from core.rules.engine import construir_auditorias

st.set_page_config(page_title="Auditor Hospitalario", layout="wide", page_icon="🏥")

# Versión corregida con base en observaciones de auditoría:
# - Oxígeno QX se valida contra cargos QRF reales en estado de cuenta.
# - Oxígeno recuperación se mantiene separado.
# - Casilla azul de oxígeno queda como aviso documental, no diferencia financiera.
# - Sevoflurano queda como verificación clínica/anestesia, no error automático.
# - Parser de tiempo quirúrgico reconoce “horas”.
# - Habitación ambulatoria espera 1 cargo aunque la estancia calculada sea 0 días.
# - Hemotransfusión con SÍ en nota queda como verificación médica, no diferencia financiera automática.
# - Bomba de infusión vs equipo infusomat se valida por cantidades, no solo por existencia.
# - Mejor redacción para máquina de anestesia en particulares vs convenio/seguro.

# =========================================================
# CSS GLOBAL
# =========================================================
st.markdown("""
<style>
.cuenta-card{display:flex;align-items:center;gap:12px;padding:12px 16px;
  border:0.5px solid var(--color-border-tertiary);border-radius:10px;
  background:var(--color-background-primary);margin-bottom:8px}
.dot{width:11px;height:11px;border-radius:50%;flex-shrink:0}
.dot-ok{background:#639922}.dot-warn{background:#EF9F27}
.dot-err{background:#E24B4A}.dot-gray{background:#888780}
.badge{display:inline-flex;align-items:center;font-size:11px;font-weight:500;
  padding:3px 9px;border-radius:20px;white-space:nowrap}
.badge-ok{background:#EAF3DE;color:#27500A}
.badge-warn{background:#FAEEDA;color:#633806}
.badge-err{background:#FCEBEB;color:#791F1F}
.badge-gray{background:#F1EFE8;color:#444441}
.bar-wrap{background:#e8e8e4;border-radius:4px;height:9px;width:100%;overflow:hidden;margin:3px 0 2px}
.bar-fill{height:100%;border-radius:4px}
.bar-ok{background:#639922}.bar-warn{background:#EF9F27}
.bar-err{background:#E24B4A}.bar-gray{background:#888780}
.cat-title{font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:.07em;
  color:var(--color-text-tertiary);margin:16px 0 6px;padding-bottom:4px;
  border-bottom:0.5px solid var(--color-border-tertiary)}
.audit-row{padding:10px 0;border-bottom:0.5px solid var(--color-border-tertiary)}
.audit-row:last-child{border-bottom:none}
.audit-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:3px}
.audit-label{font-size:13px;font-weight:500}
.audit-sub{font-size:11px;color:var(--color-text-secondary);margin-top:2px;line-height:1.5}
.finding-box{border-left:3px solid;padding:8px 12px;border-radius:0 6px 6px 0;
  font-size:13px;margin-bottom:6px}
.finding-err{border-color:#E24B4A;background:#FCEBEB;color:#791F1F}
.finding-warn{border-color:#EF9F27;background:#FAEEDA;color:#633806}
.finding-ok{border-color:#639922;background:#EAF3DE;color:#27500A}
.finding-gray{border-color:#888780;background:#F1EFE8;color:#444441}
.ev-table{width:100%;border-collapse:collapse;font-size:12px}
.ev-table th{text-align:left;padding:5px 8px;
  background:var(--color-background-tertiary);
  border-bottom:0.5px solid var(--color-border-tertiary);
  font-weight:500;color:var(--color-text-secondary)}
.ev-table td{padding:5px 8px;border-bottom:0.5px solid var(--color-border-tertiary)}
.ev-table tr:last-child td{border-bottom:none}
.mono{font-family:var(--font-mono);font-size:11px}
</style>
""", unsafe_allow_html=True)


# =========================================================
# CONSOLIDACIÓN
# =========================================================
@st.cache_data(show_spinner=False)
def consolidar_por_cuenta(archivos_bytes: list):
    return consolidar_por_cuenta_core(archivos_bytes)

# =========================================================
# Fix 3: REPORTE HTML DESCARGABLE POR CUENTA
# =========================================================
def _construir_html_reporte_cuenta(
    cuenta: str, data: dict, auds: list, file_hash: str,
) -> str:
    """Genera un HTML imprimible para una sola cuenta."""
    ICON  = {"ok": "✅", "err": "❌", "warn": "⚠️", "gray": "ℹ️"}
    COLOR = {"ok": "#27500A", "err": "#791F1F", "warn": "#633806", "gray": "#444441"}
    BG    = {"ok": "#EAF3DE", "err": "#FCEBEB", "warn": "#FAEEDA", "gray": "#F1EFE8"}

    estado_txt, clase = estado_global(auds)
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    archivos_cuenta = ", ".join(af["archivo"] for af in data["archivos"])

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Auditoría {cuenta}</title>
<style>
  body{{font-family:Arial,sans-serif;max-width:900px;margin:20px auto;color:#222;font-size:13px}}
  h1{{color:#185FA5;font-size:20px;border-bottom:2px solid #185FA5;padding-bottom:6px}}
  .meta{{color:#777;font-size:11px;margin-bottom:16px}}
  .finding{{border-left:3px solid;padding:6px 12px;margin:6px 0;border-radius:0 6px 6px 0}}
  .finding-err{{border-color:#E24B4A;background:#FCEBEB;color:#791F1F}}
  .finding-warn{{border-color:#EF9F27;background:#FAEEDA;color:#633806}}
  table{{border-collapse:collapse;width:100%;margin:10px 0}}
  th{{background:#f0f0ec;padding:6px 10px;text-align:left;font-weight:500;font-size:12px;
      border-bottom:1px solid #ddd}}
  td{{padding:6px 10px;border-bottom:1px solid #eee;font-size:12px}}
  .cat{{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.07em;
       color:#555;margin:18px 0 6px;padding-bottom:4px;border-bottom:1px solid #ddd}}
  @media print{{ body{{margin:0}} }}
</style></head><body>

<h1>🏥 Auditoría — {cuenta}</h1>
<p><b>Paciente:</b> {data["paciente"] or "No identificado"}<br>
<b>Seguro:</b> {data.get("seguro","N/A")}<br>
<b>Ingreso:</b> {data.get("fecha_ingreso","?")} → <b>Egreso:</b> {data.get("fecha_egreso","?")}
  ({data.get("dias_estancia","?")} día(s))<br>
<b>Estado:</b> <span style="color:{COLOR[clase]}">{ICON[clase]} {estado_txt}</span></p>
<p class="meta">Generado: {timestamp} · Hash archivos: {file_hash[:12]}…<br>
Archivos: {archivos_cuenta}</p>
"""
    # Hallazgos
    errores = [a for a in auds if a["clase"] in ("err", "warn")]
    if errores:
        html += "<h2>Hallazgos</h2>"
        for a in errores:
            cls = "finding-err" if a["clase"] == "err" else "finding-warn"
            html += (f'<div class="finding {cls}"><b>{a["label"]}:</b> {a["status"]}.'
                     + (f' {a["nota_auditoria"]}' if a.get("nota_auditoria") else "")
                     + '</div>')

    # Tabla de auditorías
    categorias = []
    for a in auds:
        if a["categoria"] not in categorias:
            categorias.append(a["categoria"])

    for cat in categorias:
        html += f'<div class="cat">{cat}</div>'
        html += '<table><tr><th>Auditoría</th><th style="text-align:right">Cobrado</th>'
        html += '<th style="text-align:right">Esperado</th><th>Resultado</th></tr>'
        for a in [x for x in auds if x["categoria"] == cat]:
            u = a.get("unidad", "")
            cob = f"{a['cobrado']:.2f} {u}".strip() if a["cobrado"] is not None else "—"
            esp = f"{a['esperado']:.2f} {u}".strip() if a.get("esperado") is not None else "—"
            icon = ICON.get(a["clase"], "")
            color = COLOR.get(a["clase"], "#222")
            html += (f'<tr><td>{a["label"]}</td>'
                     f'<td style="text-align:right">{cob}</td>'
                     f'<td style="text-align:right">{esp}</td>'
                     f'<td style="color:{color}">{icon} {a["status"]}</td></tr>')
            if a.get("nota_auditoria") and a["clase"] in ("err","warn","gray"):
                html += (f'<tr><td colspan="4" style="padding:2px 10px 6px 24px;'
                         f'font-size:11px;color:#777;font-style:italic">'
                         f'{a["nota_auditoria"]}</td></tr>')
        html += '</table>'

    html += """
<p style="font-size:10px;color:#aaa;margin-top:30px;border-top:1px solid #eee;padding-top:6px">
  Reporte generado automáticamente por Auditor Hospitalario.
</p></body></html>"""
    return html

# =========================================================
# ESTADO GLOBAL DE CUENTA
# =========================================================
def estado_global(auditorias: list):
    clases = [a["clase"] for a in auditorias]
    if "err"  in clases: return "Con diferencias", "err"
    if "warn" in clases: return "Revisar",         "warn"
    if "ok"   in clases: return "Sin diferencias", "ok"
    return "Sin referencias", "gray"

# =========================================================
# COMPONENTES DE UI
# =========================================================
def badge_html(txt, cls):
    return f'<span class="badge badge-{cls}">{txt}</span>'

def dot_html(cls):
    return f'<span class="dot dot-{cls}"></span>'

def barra_html(cobrado, esperado, cls):
    if not esperado or esperado == 0:
        pct = 100
    else:
        pct = min(round(cobrado / esperado * 100), 100)
    return (f'<div class="bar-wrap">'
            f'<div class="bar-fill bar-{cls}" style="width:{pct}%"></div>'
            f'</div>')

def render_tabla_items(items: list, cols: list):
    if not items:
        st.markdown('<p style="font-size:12px;color:var(--color-text-secondary)">Sin ítems.</p>',
                    unsafe_allow_html=True)
        return
    encabezados = "".join(
        f'<th{"" if c[1]!="r" else " style=text-align:right"}>{c[0]}</th>'
        for c in cols
    )
    filas = ""
    for it in items:
        celdas = ""
        for c in cols:
            v = it.get(c[2], "")
            align = ' style="text-align:right"' if c[1] == "r" else ""
            mono  = ' class="mono"' if c[1] == "m" else ""
            if isinstance(v, float):
                v = f"{v:.3f}" if "cantidad" in c[2] else f"{v:.2f}"
            celdas += f'<td{align}{mono}>{h(v)}</td>'
        filas += f"<tr>{celdas}</tr>"
    st.markdown(
        f'<table class="ev-table"><thead><tr>{encabezados}</tr></thead>'
        f'<tbody>{filas}</tbody></table>',
        unsafe_allow_html=True,
    )

COLS_COBRO = [
    ("Área",       "",  "area"),
    ("Código",     "m", "codigo"),
    ("Descripción","",  "descripcion"),
    ("Cant.",      "r", "cantidad"),
    ("Fecha",      "",  "fecha"),
    ("Folio",      "m", "folio"),
]

COLS_ESPERADO = [
    ("Área",          "",  "area"),
    ("Hrs esperadas", "r", "cantidad_esperada"),
    ("Línea original","m", "linea_original"),
]

def render_auditoria(audit: dict):
    tipo  = audit["tipo"]
    clase = audit["clase"]
    label = audit["label"]
    status_txt = audit["status"].upper() if audit["status"] == "ok" else audit["status"]

    st.markdown(
        f'<div class="audit-row">'
        f'<div class="audit-header">'
        f'<span class="audit-label">{label}</span>'
        f'{badge_html(status_txt, clase)}'
        f'</div>',
        unsafe_allow_html=True,
    )

    if tipo == "numerico":
        cobrado  = audit["cobrado"]
        esperado = audit["esperado"]
        unidad   = audit["unidad"]
        if esperado is not None:
            st.markdown(barra_html(cobrado, esperado, clase), unsafe_allow_html=True)
            sub = f"Cobrado {cobrado:.2f} {unidad}  ·  Esperado {esperado:.2f} {unidad}"
        else:
            sub = f"Cobrado {cobrado:.2f} {unidad}"
        # Monto económico de la diferencia (cuando aplica)
        monto = audit.get("monto_diff")
        if monto is not None and monto >= 1:
            diff = audit.get("diff", 0)
            etiqueta = "sobrecobro" if diff > 0 else "faltante"
            sub += (f'  ·  <b style="color:{("#791F1F" if diff < 0 else "#633806")}">'
                    f'≈ ${monto:,.0f} {etiqueta}</b>')
        if audit.get("nota_auditoria"):
            sub += f"<br>{audit['nota_auditoria']}"
        st.markdown(f'<div class="audit-sub">{sub}</div>', unsafe_allow_html=True)

    elif tipo == "binario":
        marcado = audit["marcado"]
        cobrado_b = audit["cobrado_bool"]
        sub = (f"Servicios de cirugía: {'✓ marcado' if marcado else '— no marcado'}  ·  "
               f"Estado de cuenta: {'✓ cobrado' if cobrado_b else '— no cobrado'}")
        st.markdown(f'<div class="audit-sub">{sub}</div>', unsafe_allow_html=True)

    elif tipo == "negativo":
        n = int(audit["cobrado"])
        sub = f"{n} cargo(s) encontrado(s) en el estado de cuenta."
        if audit.get("nota_auditoria"):
            sub = audit["nota_auditoria"] + "  " + sub
        st.markdown(f'<div class="audit-sub">{sub}</div>', unsafe_allow_html=True)

    elif tipo == "informativo":
        sub = audit["status"]
        if audit.get("nota_auditoria"):
            sub += f"<br>{audit['nota_auditoria']}"
        st.markdown(f'<div class="audit-sub">{sub}</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # Evidencia expandible
    items_cob = audit.get("items_cobrados", [])
    items_esp = audit.get("items_esperados", [])
    if items_cob or items_esp:
        with st.expander("Ver evidencia"):
            if items_esp:
                st.markdown("**Esperado (servicios de cirugía)**")
                render_tabla_items(items_esp, COLS_ESPERADO)
            if items_cob:
                st.markdown("**Cobrado (estado de cuenta)**")
                render_tabla_items(items_cob, COLS_COBRO)

# =========================================================
# LOG POR EMAIL  (invisible al usuario)
# =========================================================
def _hash_archivos(archivos_bytes: list) -> str:
    h = hashlib.sha256()
    for nombre, contenido in archivos_bytes:
        h.update(nombre.encode("utf-8"))
        h.update(str(len(contenido)).encode("utf-8"))
        h.update(contenido)
    return h.hexdigest()

def _construir_html_log(
    cuentas: dict,
    todas_auditorias: dict,
    archivos_bytes: list,
    timestamp: str,
) -> str:
    ICON = {"ok": "✅", "err": "❌", "warn": "⚠️", "gray": "ℹ️"}
    COLOR = {"ok": "#27500A", "err": "#791F1F", "warn": "#633806", "gray": "#444441"}
    BG    = {"ok": "#EAF3DE", "err": "#FCEBEB", "warn": "#FAEEDA", "gray": "#F1EFE8"}

    total = len(cuentas)
    con_err  = sum(1 for auds in todas_auditorias.values()
                   if any(a["clase"] == "err"  for a in auds))
    con_warn = sum(1 for auds in todas_auditorias.values()
                   if any(a["clase"] == "warn" for a in auds))
    sin_diff = total - con_err - con_warn

    archivos_lista = "".join(
        f"<li style='font-size:12px;color:#555'>{n}</li>"
        for n, _ in archivos_bytes
    )

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:800px;margin:0 auto;color:#222">
    <h2 style="border-bottom:2px solid #185FA5;padding-bottom:8px;color:#185FA5">
      🏥 Log de auditoría hospitalaria
    </h2>
    <p style="color:#555;font-size:13px">
      <b>Fecha y hora:</b> {timestamp}<br>
      <b>Archivos procesados ({len(archivos_bytes)}):</b>
    </p>
    <ul style="margin:0 0 16px">{archivos_lista}</ul>
    <table style="border-collapse:collapse;width:100%;font-size:13px;margin-bottom:24px">
      <tr style="background:#185FA5;color:#fff">
        <td style="padding:8px 12px">Cuentas analizadas</td>
        <td style="padding:8px 12px">Con errores críticos</td>
        <td style="padding:8px 12px">Con advertencias</td>
        <td style="padding:8px 12px">Sin diferencias</td>
      </tr>
      <tr style="background:#f5f5f5">
        <td style="padding:8px 12px;text-align:center;font-weight:bold">{total}</td>
        <td style="padding:8px 12px;text-align:center;color:#791F1F;font-weight:bold">{con_err}</td>
        <td style="padding:8px 12px;text-align:center;color:#633806;font-weight:bold">{con_warn}</td>
        <td style="padding:8px 12px;text-align:center;color:#27500A;font-weight:bold">{sin_diff}</td>
      </tr>
    </table>
    """

    for cuenta, data in cuentas.items():
        auds       = todas_auditorias[cuenta]
        estado_txt, clase = estado_global(auds)
        archivos_cuenta = ", ".join(af["archivo"] for af in data["archivos"])

        html += f"""
        <div style="border:1px solid #ddd;border-radius:8px;margin-bottom:20px;overflow:hidden">
          <div style="background:{BG[clase]};padding:10px 16px;border-bottom:1px solid #ddd">
            <span style="font-weight:bold;font-size:15px;color:{COLOR[clase]}">
              {ICON[clase]} {cuenta}
            </span>
            <span style="font-size:13px;color:#555;margin-left:12px">
              {data["paciente"] or "No identificado"}
            </span>
            <span style="float:right;font-size:12px;color:#777">
              {data.get("fecha_ingreso","?")} → {data.get("fecha_egreso","?")}
              ({data.get("dias_estancia","?")} día(s))
            </span>
          </div>
          <div style="padding:8px 16px;font-size:12px;color:#555;background:#fafafa;
                      border-bottom:1px solid #eee">
            Archivos: {archivos_cuenta}
          </div>
          <table style="border-collapse:collapse;width:100%;font-size:13px">
            <tr style="background:#f0f0ec">
              <th style="padding:7px 12px;text-align:left;font-weight:500;color:#444">Auditoría</th>
              <th style="padding:7px 12px;text-align:left;font-weight:500;color:#444">Categoría</th>
              <th style="padding:7px 12px;text-align:right;font-weight:500;color:#444">Cobrado</th>
              <th style="padding:7px 12px;text-align:right;font-weight:500;color:#444">Esperado</th>
              <th style="padding:7px 12px;text-align:left;font-weight:500;color:#444">Resultado</th>
            </tr>
        """

        for i, a in enumerate(auds):
            bg_fila = "#fff" if i % 2 == 0 else "#fafafa"
            unidad  = a.get("unidad", "")
            cobrado_txt  = f"{a['cobrado']:.2f} {unidad}".strip() if a["cobrado"] is not None else "—"
            esperado_txt = f"{a['esperado']:.2f} {unidad}".strip() if a.get("esperado") is not None else "—"
            icon_r = ICON.get(a["clase"], "?")
            color_r = COLOR.get(a["clase"], "#222")

            html += f"""
            <tr style="background:{bg_fila}">
              <td style="padding:6px 12px">{a["label"]}</td>
              <td style="padding:6px 12px;color:#777">{a["categoria"]}</td>
              <td style="padding:6px 12px;text-align:right">{cobrado_txt}</td>
              <td style="padding:6px 12px;text-align:right">{esperado_txt}</td>
              <td style="padding:6px 12px;color:{color_r};font-weight:500">
                {icon_r} {a["status"]}
              </td>
            </tr>
            """
            if a.get("nota_auditoria") and a["clase"] in ("err", "warn", "gray"):
                html += f"""
                <tr style="background:{bg_fila}">
                  <td colspan="5" style="padding:2px 12px 8px 24px;
                      font-size:11px;color:#777;font-style:italic">
                    {a["nota_auditoria"]}
                  </td>
                </tr>
                """

        html += "</table></div>"

    html += """
    <p style="font-size:11px;color:#aaa;margin-top:24px;border-top:1px solid #eee;padding-top:8px">
      Este correo es un log automático generado por el Auditor Hospitalario.
      No responder a este mensaje.
    </p>
    </body></html>
    """
    return html

def _enviar_log_email(
    cuentas: dict,
    todas_auditorias: dict,
    archivos_bytes: list,
) -> None:
    try:
        cfg = st.secrets.get("email_log", {})
        if not cfg:
            return

        smtp_host = cfg.get("smtp_host", "")
        smtp_port = int(cfg.get("smtp_port", 587))
        smtp_user = cfg.get("smtp_user", "")
        smtp_pass = cfg.get("smtp_password", "")
        destino   = cfg.get("destino", "")

        if not all([smtp_host, smtp_user, smtp_pass, destino]):
            return

        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        total     = len(cuentas)
        con_diff  = sum(
            1 for auds in todas_auditorias.values()
            if any(a["clase"] in ("err","warn") for a in auds)
        )

        asunto = (
            f"[Auditoría] {total} cuenta(s) analizadas — "
            f"{con_diff} con diferencias — {timestamp}"
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"]    = smtp_user
        msg["To"]      = destino

        cuerpo_html = _construir_html_log(
            cuentas, todas_auditorias, archivos_bytes, timestamp
        )
        msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as servidor:
            servidor.ehlo()
            servidor.starttls()
            servidor.login(smtp_user, smtp_pass)
            servidor.sendmail(smtp_user, destino, msg.as_string())

    except Exception:
        logging.exception("Error enviando log de auditoría")


# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:
    st.markdown("### ⚙️ Configuración")
    tolerancia_ui = st.slider("Tolerancia (hrs / ml / días)",
                              0.0, 1.0, 0.01, 0.01,
                              help="Diferencia mínima para marcar una discrepancia.")
    st.markdown("---")
    st.markdown(
        "**Documentos reconocidos:**\n"
        "- Estado de cuenta (cualquier corte)\n"
        "- Servicios de cirugía\n"
        "- Nota post-quirúrgica"
    )
    st.markdown("---")
    st.markdown(
        "**Categorías auditadas:**\n"
        "- Validación de tiempos (hora total, minuto 21)\n"
        "- Consistencia de servicios (sala vs O₂, trío recuperación)\n"
        "- Oxígeno (QX vs sala, recuperación, hosp.)\n"
        "- Sala quirúrgica (horas, sevoflurano)\n"
        "- Equipos y servicios (binarios)\n"
        "- Accesorios complementarios (bidireccionales)\n"
        "- Verificaciones negativas\n"
        "- Estancia (habitación, bomba, dietas, RPBI)"
    )

# =========================================================
# ENCABEZADO
# =========================================================
st.title("🏥 Auditor Hospitalario")
st.markdown(
    "Sube los PDFs de la cuenta. El sistema cruza automáticamente "
    "el **estado de cuenta** contra los **servicios de cirugía** y la **nota post-quirúrgica**."
)

archivos_subidos = st.file_uploader(
    "Selecciona los documentos PDF",
    type=["pdf"],
    accept_multiple_files=True,
)

if not archivos_subidos:
    st.info("Sube uno o más archivos PDF para comenzar.")
    st.stop()

archivos_bytes = [(f.name, f.read()) for f in archivos_subidos]

with st.spinner("Analizando documentos…"):
    cuentas, avisos_consolidacion = consolidar_por_cuenta(archivos_bytes)

for aviso in avisos_consolidacion:
    if aviso["tipo"] == "warning":
        st.warning(aviso["mensaje"])
    elif aviso["tipo"] == "info":
        st.info(aviso["mensaje"])

# =========================================================
# MÉTRICAS GLOBALES
# =========================================================
todas_auditorias = {
    cta: construir_auditorias(data, tolerancia_ui)
    for cta, data in cuentas.items()
}

# ── Log por email ─────────────────────────────────────────
_hash_actual = _hash_archivos(archivos_bytes)
if st.session_state.get("_ultimo_log_enviado") != _hash_actual:
    _enviar_log_email(cuentas, todas_auditorias, archivos_bytes)
    st.session_state["_ultimo_log_enviado"] = _hash_actual

total_cuentas    = len(cuentas)
cuentas_con_diff = sum(
    1 for auds in todas_auditorias.values()
    if estado_global(auds)[1] in ("err", "warn")
)
total_reglas_err  = sum(
    sum(1 for a in auds if a["clase"] == "err")
    for auds in todas_auditorias.values()
)
total_reglas_warn = sum(
    sum(1 for a in auds if a["clase"] == "warn")
    for auds in todas_auditorias.values()
)
# Suma global de hallazgos económicos (sobrecobros + faltantes estimados)
monto_global = sum(
    a.get("monto_diff") or 0
    for auds in todas_auditorias.values()
    for a in auds
    if a.get("clase") in ("err", "warn") and a.get("monto_diff")
)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Cuentas",          total_cuentas)
c2.metric("Con diferencias",  cuentas_con_diff)
c3.metric("Errores críticos", total_reglas_err)
c4.metric("Advertencias",     total_reglas_warn)
c5.metric("Monto en hallazgos", f"≈ ${monto_global:,.0f}")

# ── Fix 8: Timestamp y trazabilidad ───────────────────────
_ts_auditoria = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
st.caption(
    f"Auditoría generada: {_ts_auditoria} · "
    f"Hash de archivos: `{_hash_actual[:12]}…` · "
    f"{len(archivos_bytes)} archivo(s) procesados"
)

st.divider()

# =========================================================
# DIALOG POPUP PARA DETALLE DE CUENTA
# =========================================================
@st.dialog("Detalle de cuenta", width="large")
def mostrar_detalle(cuenta_key: str):
    """Muestra el detalle completo de una cuenta en un popup modal."""
    data = cuentas[cuenta_key]
    auds = todas_auditorias[cuenta_key]
    estado_txt, clase = estado_global(auds)

    # ── Encabezado del popup ──────────────────────────────
    seguro_label = data.get("seguro", "")
    st.markdown(
        f'**{cuenta_key}** — {data["paciente"] or "No identificado"}'
        + (f' · {seguro_label}' if seguro_label else "")
    )
    if data.get("fecha_ingreso"):
        st.caption(
            f"Ingreso {data['fecha_ingreso']} → Egreso {data['fecha_egreso']} "
            f"({data['dias_estancia']} día(s))"
        )

    # ── Hallazgos destacados ──────────────────────────────
    errores  = [a for a in auds if a["clase"] == "err"]
    avisos   = [a for a in auds if a["clase"] == "warn"]
    if errores or avisos:
        st.markdown("#### Hallazgos que requieren atención")
        for a in errores + avisos:
            cls = "finding-err" if a["clase"] == "err" else "finding-warn"
            monto = a.get("monto_diff")
            monto_txt = ""
            if monto is not None and monto >= 1:
                etiqueta = "sobrecobro" if (a.get("diff") or 0) > 0 else "faltante"
                monto_txt = f' <b>(≈ ${monto:,.0f} {etiqueta})</b>'
            st.markdown(
                f'<div class="finding-box {cls}">'
                f'<b>{a["label"]}:</b> {a["status"]}.{monto_txt}'
                + (f' {a["nota_auditoria"]}' if a["nota_auditoria"] else "")
                + '</div>',
                unsafe_allow_html=True,
            )

    # ── Toggle: mostrar también auditorías OK ─────────────
    n_ok = sum(1 for a in auds if a["clase"] == "ok")
    mostrar_ok = False
    if n_ok > 0:
        mostrar_ok = st.checkbox(
            f"Mostrar también las {n_ok} validaciones que pasaron correctamente",
            value=False,
            key=f"chk_mostrar_ok_{cuenta_key}",
        )

    # ── Auditorías por categoría (filtradas) ──────────────
    categorias = []
    for a in auds:
        if a["categoria"] not in categorias:
            categorias.append(a["categoria"])

    for cat in categorias:
        items_cat_all = [a for a in auds if a["categoria"] == cat]
        if mostrar_ok:
            items_cat = items_cat_all
        else:
            items_cat = [a for a in items_cat_all if a["clase"] != "ok"]

        # Si la categoría no tiene nada que mostrar, saltarla
        if not items_cat:
            continue

        # Header de categoría con nota de OK ocultas
        n_ok_cat = sum(1 for a in items_cat_all if a["clase"] == "ok")
        sufijo = ""
        if not mostrar_ok and n_ok_cat > 0:
            sufijo = (f' <span style="color:var(--color-text-tertiary);'
                      f'font-weight:400;text-transform:none;letter-spacing:0">'
                      f'· {n_ok_cat} OK ocultas</span>')
        st.markdown(f'<div class="cat-title">{cat}{sufijo}</div>',
                    unsafe_allow_html=True)
        for audit in items_cat:
            render_auditoria(audit)

    # ── Archivos procesados ───────────────────────────────
    st.markdown('<div class="cat-title">Archivos procesados</div>', unsafe_allow_html=True)
    for af in data["archivos"]:
        tipo_label = {
            "servicios_cirugia": "Servicios de cirugía",
            "nota_postquirurgica": "Nota post-quirúrgica",
            "otro": "Tipo no reconocido",
        }.get(af["tipo_documento"],
              af["tipo_documento"].replace("estado_cuenta_", "Estado de cuenta — corte "))
        st.markdown(f"- `{af['archivo']}` → {tipo_label}")

    # ── Fix 3: Botón de descarga de reporte ───────────────
    st.divider()
    html_reporte = _construir_html_reporte_cuenta(
        cuenta_key, data, auds, _hash_actual)
    st.download_button(
        "📥 Descargar reporte de esta cuenta (HTML)",
        data=html_reporte.encode("utf-8"),
        file_name=f"auditoria_{cuenta_key}.html",
        mime="text/html",
        key=f"dl_reporte_{cuenta_key}",
    )


# =========================================================
# LISTA DE CUENTAS
# =========================================================
st.subheader("Cuentas analizadas")

# Ordenar por urgencia: más errores arriba, luego más warnings,
# luego limpias al final. Empate: orden alfabético de cuenta.
def _orden_urgencia(item):
    cta, _ = item
    auds = todas_auditorias[cta]
    n_err  = sum(1 for a in auds if a["clase"] == "err")
    n_warn = sum(1 for a in auds if a["clase"] == "warn")
    return (-n_err, -n_warn, cta)

cuentas_ordenadas = sorted(cuentas.items(), key=_orden_urgencia)

for cuenta, data in cuentas_ordenadas:
    auds        = todas_auditorias[cuenta]
    estado_txt, clase = estado_global(auds)
    n_err  = sum(1 for a in auds if a["clase"] == "err")
    n_warn = sum(1 for a in auds if a["clase"] == "warn")

    resumen_badge = ""
    if n_err:
        resumen_badge += f'<span class="badge badge-err" style="margin-right:4px">{n_err} error(es)</span>'
    if n_warn:
        resumen_badge += f'<span class="badge badge-warn" style="margin-right:4px">{n_warn} aviso(s)</span>'
    if not n_err and not n_warn:
        resumen_badge = badge_html("Sin diferencias", "ok")

    # Sumar monto económico de los hallazgos
    monto_total = sum(
        a.get("monto_diff") or 0
        for a in auds
        if a.get("clase") in ("err", "warn") and a.get("monto_diff")
    )
    monto_html = ""
    if monto_total >= 1:
        monto_html = (f'<span style="font-size:11px;color:#791F1F;font-weight:500;'
                      f'margin-right:10px">≈ ${monto_total:,.0f}</span>')

    # Mostrar seguro en la tarjeta
    seguro_label = data.get("seguro", "")
    seguro_html = f' · <span style="font-size:11px">{seguro_label}</span>' if seguro_label else ""

    # ── Tarjeta + botón de detalle en la misma fila ───────
    col_card, col_btn = st.columns([6, 1])
    with col_card:
        st.markdown(
            f'<div class="cuenta-card">'
            f'{dot_html(clase)}'
            f'<div style="flex:1">'
            f'<span style="font-weight:500;font-size:14px">{cuenta}</span>'
            f'<span style="color:var(--color-text-secondary);font-size:13px;margin-left:10px">'
            f'{data["paciente"] or "No identificado"}{seguro_html}</span>'
            f'</div>'
            f'<span style="font-size:11px;color:var(--color-text-tertiary);margin-right:12px">'
            f'{len(data["archivos"])} archivo(s)</span>'
            f'{monto_html}'
            f'{resumen_badge}'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col_btn:
        if st.button("Ver detalle", key=f"btn_detalle_{cuenta}", use_container_width=True):
            mostrar_detalle(cuenta)

st.divider()

# =========================================================
# EXPORTAR
# =========================================================
st.subheader("📥 Exportar")

filas_res = []
for cuenta, auds in todas_auditorias.items():
    fila = {
        "Cuenta": cuenta,
        "Paciente": cuentas[cuenta]["paciente"],
        "Seguro": cuentas[cuenta].get("seguro", ""),
        "Fecha_auditoria": _ts_auditoria,
        "Hash_archivos": _hash_actual[:12],
    }
    for a in auds:
        fila[a["label"]] = a["status"]
    filas_res.append(fila)
df_res = pd.DataFrame(filas_res)

todos_items = [
    {**i, "tipo_auditoria": "cobrado"}
    for data in cuentas.values()
    for i in data["todos_los_items"]
]
df_items = pd.DataFrame(todos_items) if todos_items else pd.DataFrame()

col1, col2 = st.columns(2)
with col1:
    st.download_button(
        "Resumen de auditoría (CSV)",
        data=df_res.to_csv(index=False).encode("utf-8"),
        file_name="auditoria_resumen.csv",
        mime="text/csv",
    )
with col2:
    if not df_items.empty:
        st.download_button(
            "Todos los ítems del estado de cuenta (CSV)",
            data=df_items.to_csv(index=False).encode("utf-8"),
            file_name="auditoria_items.csv",
            mime="text/csv",
        )
