"""Excel and CDR exports generated inside Python, without a reporting service."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill

from blaster.analytics import ACTOR_LABELS, AMD_LABELS, LEG_FIELDS, STATUS_LABELS

CDR_COLUMNS = [
    ("id", "ID llamada"),
    ("campaign_name", "Campaña"),
    ("campaign_id", "ID campaña"),
    ("mode", "Modo"),
    ("contact_name", "Nombre en contacto"),
    ("credit_id", "Credito"),
    ("phone", "Teléfono cliente"),
    ("agent_number", "Número agente"),
    ("status_label", "Resultado"),
    ("coverage", "Cobertura"),
    ("started_at", "Inicio"),
    ("customer_invite_at", "INVITE cliente"),
    ("customer_ringing_at", "Timbrado cliente"),
    ("customer_answered_at", "Respuesta cliente"),
    ("customer_media_at", "Audio cliente activo"),
    ("customer_ended_at", "Fin tramo cliente"),
    ("customer_pdd_seconds", "Demora hasta timbrado (s)"),
    ("customer_setup_seconds", "Demora hasta respuesta (s)"),
    ("customer_connected_seconds", "Cliente conectado (s)"),
    ("customer_total_seconds", "Tramo cliente total (s)"),
    ("amd_label", "Resultado AMD"),
    ("amd_reason", "Motivo AMD"),
    ("amd_elapsed_ms", "Análisis AMD (ms)"),
    ("amd_voiced_ms", "Voz AMD (ms)"),
    ("amd_words", "Segmentos de voz AMD"),
    ("tts_ms", "Generación TTS (ms)"),
    ("message_started_at", "Inicio reproducción"),
    ("message_completed_at", "Mensaje completo"),
    ("replays", "Repeticiones"),
    ("transfer_requested_at", "Solicitud agente"),
    ("transfer_actor", "Quién solicitó agente"),
    ("agent_invite_at", "INVITE agente"),
    ("agent_ringing_at", "Timbrado agente"),
    ("agent_answered_at", "Respuesta agente"),
    ("agent_connected_seconds", "Agente conectado (s)"),
    ("bridged_at", "Inicio puente"),
    ("bridge_ended_at", "Fin puente"),
    ("bridge_seconds", "Conversación en puente (s)"),
    ("end_actor_label", "Quién inició fin sesión"),
    ("end_reason", "Motivo fin"),
    ("end_evidence", "Evidencia fin"),
    ("customer_sip_code", "SIP cliente"),
    ("agent_sip_code", "SIP agente"),
    ("customer_call_id", "SIP Call-ID cliente"),
    ("agent_call_id", "SIP Call-ID agente"),
    ("finalized_at", "Registro finalizado"),
    ("detail", "Detalle"),
    ("customer_trunk_id", "Troncal cliente"),
    ("agent_trunk_id", "Troncal agente"),
    ("agent_strategy", "Distribución de transferencias"),
    ("agent_pool_wait_seconds", "Espera de teléfono libre (s)"),
    ("contact_id", "ID contacto en campaña"),
    ("attempt_number", "Intento"),
    ("retry_of", "ID intento anterior"),
    ("available_at", "Reintento disponible desde"),
]
DEFINITIONS = [
    ("Fuente", "Base SQLite local; una fila CDR por intento cuya sesión inició; "
     "los reintentos tienen IDs distintos."),
    (
        "Cobertura measured",
        "Telemetría capturada por esta versión. Una celda vacía significa sin evidencia.",
    ),
    (
        "Cobertura legacy",
        "Registro anterior: se conserva su estado y fechas; no se infieren respuesta ni cuelgue.",
    ),
    (
        "Nombre en contacto",
        "Nombre importado. No identifica ni verifica a la persona que contestó.",
    ),
    (
        "Credito",
        "Identificador obligatorio importado con el contacto; se conserva en cada intento.",
    ),
    ("Respuesta", "Respuesta SIP 2xx al INVITE o llamada confirmada; puede ser un buzón."),
    ("AMD", "Clasificación probable por audio; no acredita identidad. Sin IA; puede equivocarse."),
    (
        "Conectado (s)",
        "Desde la respuesta hasta la desconexión observada de cada tramo. Incluye TTS y espera.",
    ),
    (
        "Puente (s)",
        "Desde que se enlaza audio bidireccional hasta la primera desconexión observada.",
    ),
    (
        "ASR",
        "Respuestas observadas / INVITE de cliente observados. Excluye históricos sin telemetría.",
    ),
    ("Éxito transferencia", "Puentes establecidos / solicitudes de agente por DTMF 2."),
    (
        "Promedios",
        "Sólo mediciones disponibles. Tiempos conectados excluyen tramos aún activos "
        "o interrumpidos sin fin.",
    ),
    (
        "Fin remoto",
        "BYE/CANCEL recibido en el tramo cliente/agente. La troncal puede originarlo; "
        "no prueba identidad física.",
    ),
    (
        "Desvíos",
        "Se guardan solicitudes DTMF 2, REFER rechazados y respuestas SIP 3xx observadas. "
        "Un desvío interno del operador puede no ser visible.",
    ),
    (
        "Duraciones",
        "Reloj monotónico, segundos sin redondeo de facturación. No equivalen al CDR "
        "facturado del proveedor.",
    ),
    (
        "Interrupción",
        "Ante cierre abrupto se preserva lo observado y se dejan vacíos los tiempos que "
        "no pudieron medirse.",
    ),
    (
        "Modo",
        "Simulación y SIP se separan mediante el filtro. all mezcla ambos de forma explícita.",
    ),
    (
        "Fechas",
        "Excel usa la zona del reporte; CSV y eventos JSON conservan ISO 8601 UTC con offset.",
    ),
    (
        "Eventos",
        "Cronología técnica sin audio ni cabeceras SIP de autenticación. Los estados "
        "operativos permanecen en SQLite.",
    ),
]


def cdr_csv(rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([label for _, label in CDR_COLUMNS])
    for row in rows:
        values = []
        for key, _ in CDR_COLUMNS:
            value = row.get(key)
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                value = "'" + value
            values.append(value)
        writer.writerow(values)
    return output.getvalue().encode("utf-8-sig")


INK, ACCENT, WASH = "203841", "176278", "E3F0F4"


def excel_report(rows, summary, events, filters):
    workbook = Workbook(write_only=True)
    workbook.properties.creator = "Blaster TTS"
    workbook.properties.title = "Analítica de llamadas"
    zone = ZoneInfo(filters.timezone)

    def sheet(name, headers, widths=None):
        ws = workbook.create_sheet(name)
        ws.freeze_panes = "A2"
        ws.sheet_view.showGridLines = False
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.print_options.horizontalCentered = True
        ws.sheet_properties.outlinePr.summaryRight = False
        from openpyxl.utils import get_column_letter

        for index, label in enumerate(headers, 1):
            ws.column_dimensions[get_column_letter(index)].width = (
                widths[index - 1] if widths else min(42, max(23, len(label) + 3))
            )
        append(ws, headers, header=True)
        return ws

    def append(ws, values, *, header=False):
        cells = []
        for value in values:
            cell = WriteOnlyCell(ws, value=value)
            if isinstance(value, str):
                # Force text: user contact/campaign content cannot become Excel formulas.
                cell.data_type = "s"
            cell.font = Font(name="Aptos", size=11, color="FFFFFF" if header else INK, bold=header)
            cell.alignment = Alignment(vertical="top", wrap_text=header)
            if header:
                cell.fill = PatternFill("solid", fgColor=ACCENT)
            elif isinstance(value, (float, int)):
                cell.number_format = "#,##0.00" if isinstance(value, float) else "#,##0"
            elif isinstance(value, datetime):
                cell.number_format = "yyyy-mm-dd hh:mm:ss"
            cells.append(cell)
        ws.append(cells)

    def date_value(key, value):
        if key.endswith("_at") and value:
            return datetime.fromisoformat(value).astimezone(zone).replace(tzinfo=None)
        return value

    main = sheet(
        "Resumen", ["BLASTER · Analítica de llamadas", "Valor", "Definición"], [43, 25, 75]
    )
    counts = summary["counts"]
    append(
        main, ["Generado", date_value("generated_at", summary["generated_at"]), filters.timezone]
    )
    append(
        main,
        [
            "Período",
            f"{filters.date_from or 'Inicio'} → {filters.date_to or 'Actual'}",
            f"Modo: {filters.mode}; campaña: {filters.campaign_id or 'Todas'}; "
            + (
                f"Credito: {filters.credit_id}"
                if filters.credit_id is not None
                else f"Telefono: {filters.phone}"
                if filters.phone is not None
                else "sin identificador exacto"
            ),
        ],
    )
    append(main, ["Indicador", "Resultado", "Base de cálculo"], header=True)
    for key, label, definition in [
        ("total", "Sesiones iniciadas", "Incluye históricos dentro del filtro"),
        ("measured", "Con telemetría", "Sesiones de esta versión"),
        ("legacy", "Históricos sin telemetría", "No usados en tasas de respuesta"),
        ("attempted", "INVITE cliente enviados", "Intentos de marcación observados"),
        ("answered", "Respuestas cliente", "SIP 2xx/confirmado, incluye buzones"),
        ("transfer_requested", "Solicitudes de agente", "Opción 2 aceptada"),
        ("bridged", "Puentes con agente", "Audio bidireccional establecido"),
        ("message_completed", "Mensajes completos", "Reproducciones que alcanzaron su final"),
    ]:
        append(main, [label, counts[key], definition])
    append(
        main,
        [
            "Tasa de respuesta (%)",
            None if summary["answer_rate"] is None else summary["answer_rate"] * 100,
            "Respuestas / INVITE cliente observados",
        ],
    )
    append(
        main,
        [
            "Transferencias conectadas (%)",
            None if summary["transfer_rate"] is None else summary["transfer_rate"] * 100,
            "Puentes / solicitudes de agente",
        ],
    )
    for key, label in [
        ("customer_connected_seconds", "Cliente conectado"),
        ("agent_connected_seconds", "Agente conectado"),
        ("bridge_seconds", "Conversación con agente"),
    ]:
        metric = summary["durations"].get(key, {})
        append(
            main,
            [
                f"Promedio {label.lower()} (s)",
                metric.get("average"),
                f"{metric.get('samples', 0)} mediciones con fin observado",
            ],
        )
    append(
        main,
        [
            "Nota",
            "Celdas vacías = no observado",
            "Consulta Definiciones antes de interpretar datos.",
        ],
    )

    trend = sheet(
        "Tendencia", ["Fecha local", "Sesiones", "Respuestas", "Puentes"], [24, 20, 20, 20]
    )
    for day in summary["daily"]:
        append(
            trend,
            [datetime.fromisoformat(day["date"]), day["total"], day["answered"], day["bridged"]],
        )
    if summary["daily"]:
        chart = LineChart()
        chart.title = "Actividad de llamadas"
        chart.y_axis.title = "Llamadas"
        chart.x_axis.title = "Fecha local"
        chart.style = 13
        chart.width, chart.height = 25, 12
        chart.add_data(
            Reference(trend, min_col=2, max_col=4, min_row=1, max_row=len(summary["daily"]) + 1),
            titles_from_data=True,
        )
        chart.set_categories(
            Reference(trend, min_col=1, min_row=2, max_row=len(summary["daily"]) + 1)
        )
        main.add_chart(chart, "E5")
    outcomes = sheet("Resultados", ["Resultado", "Llamadas", "Tipo"], [32, 20, 32])
    for group, labels, name in [
        ("outcomes", STATUS_LABELS, "Resultado operativo"),
        ("amd", AMD_LABELS, "Análisis AMD"),
        ("hangup_actors", ACTOR_LABELS, "Fin de sesión"),
    ]:
        for key, value in summary[group].items():
            append(outcomes, [labels.get(key, key), value, name])
    if summary["outcomes"]:
        chart = BarChart()
        chart.type, chart.style = "bar", 13
        chart.title = "Resultados operativos"
        chart.width, chart.height = 25, 12
        chart.add_data(
            Reference(outcomes, min_col=2, min_row=1, max_row=len(summary["outcomes"]) + 1),
            titles_from_data=True,
        )
        chart.set_categories(
            Reference(outcomes, min_col=1, min_row=2, max_row=len(summary["outcomes"]) + 1)
        )
        main.add_chart(chart, "E29")
    campaigns = sheet(
        "Campañas", ["ID", "Campaña", "Modo", "Sesiones", "Respuestas", "Puentes", "Buzón probable"]
    )
    for item in summary["campaigns"]:
        append(
            campaigns,
            [
                item[key]
                for key in ("id", "name", "mode", "total", "answered", "bridged", "machine")
            ],
        )
    cdrs = sheet("CDRs", [label for _, label in CDR_COLUMNS])
    for row in rows:
        append(cdrs, [date_value(key, row.get(key)) for key, _ in CDR_COLUMNS])
    from openpyxl.utils import get_column_letter

    cdrs.auto_filter.ref = f"A1:{get_column_letter(len(CDR_COLUMNS))}{len(rows) + 1}"
    legs = sheet("Tramos", ["ID llamada", "Rol"] + list(LEG_FIELDS))
    for row in rows:
        if "_legs" in row:
            for leg in row["_legs"]:
                append(
                    legs,
                    [row["id"], leg["role"]]
                    + [date_value(key, leg.get(key)) for key in LEG_FIELDS],
                )
            continue
        for role in ("customer", "agent"):
            if row[f"{role}_id"]:
                append(
                    legs,
                    [row["id"], role]
                    + [date_value(key, row[f"{role}_{key}"]) for key in LEG_FIELDS],
                )
    timeline = sheet(
        "Eventos", ["ID evento", "ID llamada", "ID tramo", "Evento", "Fecha local", "Datos JSON"]
    )
    for event in events:
        append(
            timeline,
            [
                event["id"],
                event["job_id"],
                event["leg_id"],
                event["kind"],
                date_value("created_at", event["created_at"]),
                event["data"],
            ],
        )
    definitions = sheet("Definiciones", ["Campo / indicador", "Interpretación"], [36, 110])
    for definition in DEFINITIONS:
        append(definitions, definition)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()
