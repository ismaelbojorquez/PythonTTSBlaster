---
name: Blaster TTS
description: A precise local workbench for Spanish-language voice campaigns and call analytics.
colors:
  paper: "#fff"
  canvas: "#f7f9fa"
  rail: "#edf2f4"
  ink: "#203841"
  muted: "#536b76"
  line: "#d9e2e7"
  accent: "#176278"
  accent-hover: "#104d60"
  wash: "#e3f0f4"
  danger: "#ad3434"
  focus: "#4f9eb8"
  field-border: "#afc1cb"
  state-neutral-ink: "#445e6a"
  state-simulation-bg: "#fff1d4"
  state-simulation-ink: "#825a13"
  state-active-bg: "#e2f1ed"
  state-active-ink: "#216851"
  state-error-bg: "#fbe9e9"
  state-error-ink: "#963939"
  state-progress-bg: "#e2eef6"
  state-progress-ink: "#285d7c"
  series-1: "#39987d"
  series-2: "#ca9134"
  series-3: "#8499ab"
  series-4: "#b86666"
  series-5: "#756996"
  series-6: "#9aab9a"
  series-7: "#b48962"
  series-8: "#446477"
  filter-surface: "#eef3f5"
  report-surface: "#e7f0f3"
  evidence-surface: "#e9f0f3"
  chart-grid: "#eaf0f3"
  meter-track: "#e8eef1"
  coverage-bg: "#fff5dd"
  coverage-ink: "#72521a"
  operations-accent: "#19687c"
  operations-wash: "#e6f0f4"
  operations-muted: "#456578"
  operations-line: "#d4e1e7"
typography:
  headline:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "28px"
    fontWeight: 650
    lineHeight: 1.22
    letterSpacing: "-0.025em"
  title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "16px"
    fontWeight: 650
  body:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.6
  data:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "13px"
    fontWeight: 400
  label:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "12px"
    fontWeight: 600
  badge:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "11px"
    fontWeight: 600
  analytics-headline:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "27px"
    fontWeight: 650
    lineHeight: 1.22
    letterSpacing: "-0.025em"
  metric:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "29px"
    fontWeight: 600
    lineHeight: 1.05
    letterSpacing: "-0.025em"
  chart-title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "14px"
    fontWeight: 650
  chart-label:
    fontSize: "11px"
  filter-label:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "10px"
    fontWeight: 600
    letterSpacing: "0.045em"
  timing-value:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "17px"
    fontWeight: 620
  operations-form-title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "20px"
    fontWeight: 650
rounded:
  meter: "2px"
  compact: "4px"
  control: "7px"
  badge: "5px"
  tooltip: "6px"
  panel: "9px"
  operations-panel: "8px"
spacing:
  tight: "8px"
  compact: "10px"
  control: "12px"
  filter: "15px"
  group: "16px"
  analytics-gap: "17px"
  panel: "20px"
  section: "24px"
  workspace: "36px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    padding: "10px 15px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-secondary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 15px"
  button-subtle:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 15px"
  button-danger-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.danger}"
    rounded: "{rounded.control}"
    padding: "10px 15px"
  field:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "12px"
    width: "100%"
  campaign-navigation:
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "13px 11px"
    width: "100%"
  primary-navigation:
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px"
    width: "100%"
  select:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 34px 10px 11px"
  filter-bar:
    backgroundColor: "{colors.filter-surface}"
    rounded: "{rounded.panel}"
    padding: "15px"
  status-badge:
    backgroundColor: "{colors.rail}"
    textColor: "{colors.state-neutral-ink}"
    typography: "{typography.badge}"
    rounded: "{rounded.badge}"
    padding: "5px 9px"
  ledger:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.panel}"
  call-detail:
    backgroundColor: "{colors.rail}"
    rounded: "{rounded.panel}"
    padding: "22px"
  chart-panel:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.panel}"
    padding: "19px 20px"
  chart-tooltip:
    backgroundColor: "{colors.ink}"
    rounded: "{rounded.tooltip}"
    padding: "12px"
  evidence-panel:
    backgroundColor: "{colors.evidence-surface}"
    rounded: "{rounded.panel}"
    padding: "20px"
  report-manifest:
    backgroundColor: "{colors.report-surface}"
    rounded: "{rounded.panel}"
    padding: "28px"
  mobile-cdr-row:
    backgroundColor: "{colors.paper}"
    padding: "16px 13px"
  operations-navigation:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.badge}"
    padding: "10px 12px"
  operations-navigation-active:
    backgroundColor: "{colors.operations-accent}"
    textColor: "{colors.paper}"
  operations-navigation-hover:
    backgroundColor: "{colors.operations-wash}"
  operations-record:
    padding: "20px 0"
  operations-form:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.operations-panel}"
    padding: "24px"
  recording-panel:
    backgroundColor: "{colors.operations-wash}"
    rounded: "{rounded.operations-panel}"
    padding: "20px"
---

# Design System: Blaster TTS

## Overview

**Creative North Star: "The Campaign Workbench"**

Blaster is a quiet, precise work surface for handling voice campaigns and investigating their results. Cool white, slate structure, and petrol-blue actions make data and controls easy to distinguish. Familiar browser controls, clear Spanish labels, and compact typography support repeated operational work.

The visual identity comes from aligned records, restrained tonal panels, and explicit state labels. Broad workspace gaps separate tasks while tighter spacing keeps names, telephone numbers, states, and actions together. Data charts use the same fine rules and muted labels as records. The interface uses authored SVG marks and line icons; it does not depend on photography or raster decoration.

**Key Characteristics:**

- Cool white surfaces with slate text and structural rules.
- Petrol-blue actions and restrained, labeled state colors.
- One workhorse sans family with tabular numeric data.
- Flat panels, compact controls, and clear keyboard focus.
- Responsive records and detail panels that preserve selection context.
- Data charts paired with labels, counts, and accessible source values.

## Colors

The palette combines cool neutral surfaces with a deep petrol action color; green, amber, blue, and red describe operational states.

### Primary

- **Petrol** (`accent`): primary actions, links, active navigation text, field carets, and inline variable syntax. **Deep Petrol** (`accent-hover`) marks primary-button hover.
- **Pale Petrol Wash** (`wash`): contextual information and secondary-control hover.
- **Operations Petrol** (`operations-accent`): selected task navigation, disclosure labels, and checkbox accents within Operación. **Operations Wash** (`operations-wash`) supports task-navigation hover, save feedback, and recording evidence. These observed local variants preserve the existing petrol identity.

### Neutral

- **Paper** (`paper`): the top bar, ledger, fields, and secondary controls.
- **Cool Canvas** (`canvas`): the main workspace and table heading band.
- **Slate Mist** (`rail`): the campaign rail, call detail, and neutral state badges.
- **Slate Ink** (`ink`): primary text. **Muted Slate** (`muted`) supports descriptions, timestamps, and secondary numeric values.
- **Structural Slate** (`line`): single-pixel divisions and panel edges. **Field Border** (`field-border`) gives editable controls a stronger edge.
- **Operations Slate** (`operations-muted`) supports record summaries, definition labels, and field help. **Operations Rule** (`operations-line`) separates operation records and field groups and outlines their forms.

### State colors

- **Amber Simulation / AMD** (`state-simulation-*`): simulation mode, probable voicemail, and uncertain AMD badges. AMD uncertainty is also expressed in text.
- **Green Active** (`state-active-*`): live mode, running campaigns, message playback, menu waiting, and an agent connection.
- **Blue Progress** (`state-progress-*`): dialing, voice generation, and dialing an agent.
- **Red Outcome** (`state-error-*`): failed, busy, cancelled, and interrupted calls. Quiet destructive actions use `danger`.
- **Neutral Outcome** (`rail` and `state-neutral-ink`): other states, including draft, pending, paused, stopped, completed, no answer, and no selection.
- **Focus Blue** (`focus`): visible keyboard focus; it is a control boundary, not a status color.

**The Labeled State Rule.** Every status color accompanies a readable Spanish label; color alone never explains the call state.

### Chart series and analytic surfaces

The nine-slot chart palette starts with Petrol (`accent`, series 0), then Sea Green (`series-1`), Ochre (`series-2`), Blue Slate (`series-3`), Muted Red (`series-4`), Violet Slate (`series-5`), Sage (`series-6`), Sand (`series-7`), and Deep Blue Slate (`series-8`). These same slots appear in the locally rendered charts, legends, and meter rows. The trend assigns the first three slots to sessions, responses, and agent conversations respectively; its session area has a very faint petrol fill (`#17627812`).

Outcome slices are ordered by count before palette assignment. Meter rows receive slots by their displayed order. These are categorical series colors, not a fixed mapping from a result to a semantic state; the corresponding legend or row label is required.

**Filter Slate** (`filter-surface`) groups filters; **Report Slate** (`report-surface`) unifies the timing strip and file manifest; **Evidence Slate** (`evidence-surface`) separates call evidence from its timeline. **Chart Grid** (`chart-grid`) and **Meter Track** (`meter-track`) stay faint behind data. Coverage notices use `coverage-bg` and `coverage-ink` to explain historical gaps.

**The Named Series Rule.** Keep each chart, its legend, and its tabular or text values aligned; never infer an outcome from a series color without reading its label.

## Typography

The platform sans stack is the workhorse family for headings, body text, labels, and data. There is no separate display face. Weight, size, and spacing carry hierarchy without adding an expressive type system.

### Hierarchy

- **Headline**: page and campaign titles use the frontmatter headline role; small screens reduce standard titles to (25px). Long campaign names wrap within the heading area.
- **Title**: detail and editor section headings use the title role.
- **Body**: the root size is the body role; prose uses generous leading. Detail-message copy is compact (13px) with (1.7) line height.
- **Data**: contact rows use (13px), with semibold names and smaller telephone numbers (12px). Secondary metadata commonly uses (11px).
- **Label**: table headings and small control labels sit below body text; badges use the badge role and become (10px) at the mobile breakpoint.
- **Capacity values**: prominent counts use (25px), medium weight (550), and smaller muted denominators (15px); counts reduce to (22px) on mobile.
- **Analytics titles and metrics**: shared analytics page titles use the analytics-headline role, reducing to (23px) on mobile. Main metric values use the metric role, also reducing to (23px); supporting descriptions use (10–11px). Timing values use the timing-value role. The CDR detail title is (24px).
- **Chart and filter labels**: chart panel titles use the chart-title role. Canvas ticks and legends are (11px), with the bundled chart renderer's default sans family. Filters use the compact uppercase filter-label role; these are persistent field labels, not section eyebrows.
- **Operations headings and values**: form and generated-file section headings use the operations-form-title role. Record headings and fieldset legends use (16px); field labels use (13px), and definition labels use (12px). Definition values are semibold tabular data. Technical disclosures retain literal codes in code/preformatted text while normal record titles stay in Spanish.

**The Numeric Alignment Rule.** Use tabular numerals for ledger data, telephone details, timestamps, capacity counts, and numeric capacity inputs. Monospace is reserved for actual variable syntax and disclosed technical evidence through the browser's code treatment.

## Layout

The desktop shell is a navigation rail (224px) beside a flexible workspace. Its five primary destinations are Dashboard, Campañas, Llamadas/CDR, Reportes, and Operación, followed by the new-campaign action and recent campaigns. A white top bar (78px high) establishes the shared frame. The capacity strip appears only in campaign operation and creation. The workspace has horizontal gutters (36px), increasing to (48px) from (1500px).

The current campaign surface places a flexible contact ledger beside a detail column (270px), separated by (24px). At widths up to (1200px), the detail column narrows to (235px), its padding becomes (18px), and the gap becomes (16px). From (1500px), the detail column grows to (310px). The editor follows a related field-and-preview grid with a maximum width (1000px); its desktop preview is (310px) wide.

At widths up to (1000px), the rail narrows to (190px), the ledger and detail stack, and editor fields precede their preview. Selecting a contact focuses the detail region and scrolls it into view. The visible “Volver al contacto” control returns focus and scroll position to the selected contact.

Analytics shares a filter band across Dashboard, Llamadas, and Reportes. The desktop band has six aligned columns for period, dates, campaign, origin, and apply. Four main metrics sit in one ruled strip. Lead charts use a broad trend column beside a narrower outcome column; supporting panels form three columns. The recurring analytic grid gap is the analytics-gap token. Campaign summaries use aligned rows; the reports surface pairs explanatory copy with a file manifest within a maximum width (1050px).

At widths up to (1180px), filters become three columns, supporting charts become two columns, and the timing strip stacks its heading above its metrics. Up to (900px), lead charts, the CDR timeline/evidence area, and reports stack; main and CDR metrics become two columns. Timing metrics step from five columns to three, then two on mobile.

At widths up to (680px), the rail becomes a compact header with horizontally scrolling primary section navigation and a new-campaign button. The brand and recent campaigns are hidden in this header. The top bar becomes (56px) high; workspace gutters are (16px). Filters use two columns, with campaign selection and apply spanning the full width. Charts use single-column panels; the smaller donut and its count legend sit side by side. Metric strips reach the workspace edges. The original campaign ledger retains its contact and state columns; its selected detail remains available below.

The CDR explorer has a separate mobile treatment: its desktop seven-column table becomes a stack of two-column call records. Each record retains contact, date/campaign, result, AMD, connected duration, agent duration, and termination initiator. Contact and date occupy full-width rows; the explicit “Ver detalle de llamada” affordance leads into the full record. Page size is (50) records on desktop and (25) on mobile.

Operación uses the shared page heading and a wrapping task-navigation row, followed by ruled records and inline forms. Record headers pair identity and summary with text actions; definition values use three equal columns with gaps (14px 28px). Forms use two equal columns with gaps (20px 24px), paper surfaces, and padding (24px). At widths up to (760px), forms become one column, record values become two columns with gaps (16px), and header actions move below the summary. Form padding becomes (18px), footer actions wrap, and no record fields are hidden. The (760px) operations breakpoint is separate from the shell's (680px) breakpoint.

The session entry sits directly on the canvas in a centered column with maximum width (420px), padding (28px), and top margin (12vh), reducing to (5vh) at the operations breakpoint. The signed-in user appears in the top bar with a width limit (160px) and ellipsis; that name is hidden below (760px), while “Salir” remains available.

Use tight gaps for related controls and wider gaps between working sections. The reusable spacing steps in the frontmatter record the implementation's rhythm, rather than prescribing a new uniform scale. Tables retain their semantic structure and can scroll inside their container when necessary.

## Elevation & Depth

The system is flat by default. Surface tones, one-pixel rules, and selected-row fills establish structure. Selected paper navigation items use very faint shadows: recent campaigns use (`0 2px 6px #1c374009`), and primary destinations use (`0 2px 7px #1c37400b`). Ledger, charts, detail, preview, metrics, and form controls do not use elevated card shadows.

**The Structural Surface Rule.** Separate working areas with tone, spacing, and fine rules; reserve faint shadows for selected navigation.

## Shapes

Controls have softly squared corners using the control radius. Badges are smaller rounded rectangles using the badge radius. The ledger and call detail share the panel radius; the editor preview has a closely related corner (10px). Borders stay thin and cool. Circular shapes belong to the connection indicator and numbered call-sequence markers.

Analytics extends the same panel radius to charts, filters, campaign summaries, evidence, and the report manifest. Compact navigation captions, legend rows, and file-format tags use the compact radius. Chart tooltips use the tooltip radius. Thin meter tracks are (6px) high with the small meter radius; the charts are data surfaces rather than decorative progress ornaments.

Operations forms and the recording strip use the operations-panel radius. Operation records remain open rows divided by fine rules. Selected task buttons use the badge radius, and native checkboxes remain compact squares (18px).

Small action icons are authored SVG with open strokes, rounded caps and joins, and inherited text color. The recurring plus and flow arrows use a (16px) icon box and stroke width (1.7). They accompany text rather than replacing an action label.

## Components

### Buttons

Direct, compact, and clearly named. Standard buttons have a minimum height (40px), semibold text, and the common control shape. Primary buttons use petrol and paper; hover deepens the fill. Secondary buttons use paper with a cool border and wash on hover. Subtle buttons are transparent and gain a wash on hover. Quiet destructive buttons use red text and a pale red hover surface.

Keyboard focus uses a blue outline (3px) with an offset (3px). Disabled buttons retain their shape at reduced opacity (0.45) and use the unavailable cursor. Compact pagination and contact buttons use smaller measured heights; these are local variants, not replacements for the standard action button.

### Inputs / Fields

White fields have a stronger cool border, internal padding, a petrol caret, and the shared focus treatment. Labels remain visible above the controls; muted help text explains formatting below them. Text areas resize vertically and use (1.6) line height. Native selects share the control radius, border, and minimum height (40px), with space reserved for the native arrow. They retain browser focus styling; the authored blue outline targets inputs, text areas, links, and buttons. CSV import exposes a text link with a focus-within outline. Validation uses native form constraints and a visible error notice with `role="alert"`; the implementation does not define an individual red-border field state.

Telephone examples omit the plus sign. The agent field and CSV `telefono` column remove plus signs immediately during entry, paste, and file import while preserving cursor position and other CSV variables. Saved numbers contain digits only.

### Navigation

Primary navigation combines authored line icons with short destination labels, a minimum height (42px), and a small CDR caption. The current destination uses paper, petrol text, the faint navigation shadow, and `aria-current="page"`. Mobile navigation retains labels and hides icons. Recent-campaign navigation preserves the earlier wrapping title and smaller count/state metadata pattern; it is hidden in the mobile rail. Hover applies a cooler slate fill.

Operación adds a small count caption when alerts remain unresolved and unreviewed. Its task navigation has eight administrator destinations: Troncales, Plantillas, Programación, Reportes automáticos, Alertas, Configuración, Usuarios, and Auditoría. Configuración, Usuarios, and Auditoría are omitted for other roles. Task buttons use `aria-current="page"`, white text on Operations Petrol for the active task, and a wash on inactive hover. They wrap at available width; mobile padding is (10px 9px) with (13px) text. The heading and subtitle name the current task.

### Status badges

Compact text badges keep their labels on one line and use the state palette described above. Default neutral badges are appropriate for outcomes without an active or error-specific treatment. A connected badge has a short background-color transition (350ms, ease-out), enabled only when reduced motion is not requested. Other state changes are immediate.

### Ledger

A paper container holds a light heading band, aligned contact records, fine row rules, and a quiet pagination footer. Contacts are real buttons with `aria-pressed` selection state; names appear above telephone numbers. Selected rows use a pale petrol fill, and hovering a row applies a subtle cool wash. Use semantic captions and column headers even when the caption is visually hidden.

### Call detail and simulation keypad

The slate detail panel groups identity, telephone number, state, personalized message, actions, and a compact chronological activity list. Timestamps use muted tabular numerals. The simulation keypad presents two side-by-side white choices with prominent digits and descriptive labels; hang-up actions span both columns and use quiet red text.

At stacked widths, the detail region accepts programmatic focus with its own blue outline (2px, offset 4px) and scroll margin (20px). Return-to-contact navigation remains a visible underlined text control. Updates preserve the focused action when the corresponding control still exists.

### Editor preview and notices

The editor preview uses a pale slate-blue surface and a numbered vertical call sequence. It shares the page's workhorse type and restrained borders. Information notices use a petrol wash; error notices use pale red with dark red text. Preview results use petrol text and `role="status"`. Messages provide operational context without relying on decorative iconography.

Below “Revisar personalización” and its result, a thin rule separates “Escucha antes
de enviar” within “Así será la llamada”. The full-width secondary “Escuchar TTS”
action generates the configured Piper voice with the first contact's variables and
the final keypad menu. It needs no campaign name or agent number; variable-free
text works before a CSV is entered or imported. The block follows the existing
two-column-to-single-column editor reflow.

Generation disables the action, labels it “Generando audio…”, and announces progress
in a polite live region. Only one generation runs at a time. Ready audio updates
the personalized message, exposes a wrapping voice/first-contact caption (or
“Mensaje sin datos de contacto”), and uses full-width native playback controls with
an accessible name. An autoplay restriction leaves an explicit instruction to press
play. Errors stay beside the action with the player hidden; missing contacts prompt
the operator to add the required column or replace the variable with text.

Changes to the message, CSV contacts, or selected template clear the prior sample
and discard stale responses; after an existing or pending sample, they also replace
the old personalized text and clear its previous review result. An outstanding
generation keeps the action disabled until it finishes. Leaving the editor, resetting
the form, signing out, or leaving the page stops playback and releases its Blob URL;
the server deletes temporary WAV files. The preview creates no campaign or call.

### Charts, metrics, and filters

Metric strips use strong tabular values, small labels and explanatory denominators, and fine rules instead of individual floating cards. Chart panels use white surfaces, (19px 20px) padding, concise titles, muted subtitles, and visible units where relevant. The desktop trend plot is (235px) high; mobile chart boxes become (210px). The outcome donut is (175px), reducing to (140px), with a (78%) cutout, paper separators, and a centered total.

Trend lines use a (2px) stroke and restrained curve tension (0.18). Ordinary points are hidden except in very short series; hover reveals a point. Horizontal grid lines start from zero and keep axes quiet. The trend exposes its values through an expandable table. Outcome legend rows are buttons with names, counts, and desktop percentages; selecting one opens the CDR explorer with that result and the existing date, campaign, and origin filters. HTML meters pair every bar with its label and value.

Chart animation is disabled. Analytics panels have a short opacity transition (160ms, ease-out), and an active summary fetch sets `aria-busy` with opacity (0.62). Empty periods, missing measurements, and historical coverage receive explicit text; unavailable durations display “—”. These are data states, not zero-valued decoration.

### CDR explorer and evidence

The desktop explorer uses a scrollable table with a minimum width (940px), keeping seven columns available. Contact buttons open a full detail article. On mobile, those same records become the complete labeled call cards described in Layout; the finalization field remains visible. Tables use tabular durations, small campaign/date metadata, normal state badges, and textual AMD classification.

The full CDR presents identity and outcome, four compact measurements, a scrollable customer/agent leg table, a timestamped timeline, and a tonal evidence panel. Long IDs wrap within the evidence panel. Historical records announce their missing telemetry. Opening the article moves focus and scrolls it into view; “Volver a las llamadas” returns to the filtered explorer and focuses search. The separate campaign detail continues to return to the selected contact.

### Reports

Reports reuse the same applied period, campaign, and origin context. A flat slate file manifest groups the format, report title, and sheet outline; it is not a simulated file-browser control. Export buttons disable while preparing a download, and a live status message describes progress, success, or failure. Below, ruled definition pairs explain the data represented in the file and stack on mobile.

### Operations records and inline forms

Open, ruled records put the name and state before detail values and actions. Troncales shows priority, distribution weight, reserved/total channels, calls per second, the local SIP port, and the complete RTP range. The same record structure supports a single trunk, principal and backup routes, templates, scheduled campaigns, generated reports, alerts, users, and audit. “Historial”, “Editar”, “Usar en campaña”, and other text actions remain explicitly named.

Forms follow their lists and pair a primary save action with “Cancelar edición”. Editing scrolls the form into view and focuses its field; read-only trunk identifiers receive a pale slate fill. Password fields stay empty when editing, with a label explaining when blank preserves the saved secret. Native field constraints handle validation. Loading sets `aria-busy` and shows “Cargando información…”; successful saves show “Cambios guardados.” in the shared live feedback region. Empty lists explain their next useful action.

Configuración starts with a separate “Puertos SIP y RTP” form: a trunk selector loads that trunk's local SIP port, even RTP starting port, and port count. Its save action is distinct from “Límites y comportamiento”. The latter uses ruled fieldsets for global session/channel/CPS limits and distribution, call timings, audio retention/storage, and schedules/alerts. Field help names units and explains that global and per-trunk limits apply together; a session reserves two channels. Remote SIP server settings remain in the trunk editor.

### Scheduled records and technical evidence

Scheduled campaign and automatic-report rows keep the due/next-run date beside the stored IANA zone, using that record's zone to format the time. The editable zone remains an explicit field. Generated files, alerts, audit records, and trunk history display the reporting-zone identifier with their timestamp. Audit titles describe the action in Spanish and present actor, result, and record; “Detalles técnicos” retains original codes, targets, and details in a native disclosure. Long identifiers and preformatted details wrap within the record.

Template messages preserve line breaks and remain within (76ch); their action opens campaign creation with the message and agent filled. Scheduled campaigns expose cancellation while pending. Automatic reports pair their recurring schedule with a separate “Archivos generados” list and explicit download links. Alerts distinguish pending, reviewed, and resolved states in text, with “Marcar revisada” when applicable.

### Session entry and roles

The entry form uses the existing SVG brand, a short title, persistent labels, and a full-width primary action. First use adds the name field and “Crear administrador”; later visits show “Inicia sesión” and “Entrar”. Errors occupy a reserved red text line with `role="alert"`. The submit button disables during the request. User access records show name, username, role, and enabled state; their editor explains administrator, operator, and analyst access. Analyst views omit write actions, and administrative navigation stays limited to administrators.

### Recording evidence

The CDR places a flat recording strip before the call legs. It pairs “Grabación” and its status with the capture trigger, Ogg Opus format, available size, and a synthetic-audio label for simulation. Ready recordings expose a native audio control with `preload="none"` and “Descargar audio” to permitted roles. Other states explain compression, retention expiry, failure, or unavailable access. The strip wraps its content and limits the player's width to its container; padding reduces to (16px) below (760px). Copy distinguishes probable-human detection from keypad interaction and never presents either trigger as verified identity.

## Do's and Don'ts

### Do:

- **Do** use petrol for actions and labeled state colors for operational meaning.
- **Do** keep records aligned and numeric values tabular.
- **Do** group related data with compact spacing and separate working sections with larger gaps.
- **Do** preserve visible keyboard focus and the contact-to-detail return path when layouts stack.
- **Do** use authored SVG line icons alongside explicit action labels.
- **Do** pair chart series with labels and source values, and preserve the active data cut when drilling into results.
- **Do** keep every CDR field visible in the mobile record and show missing measurements explicitly.
- **Do** keep each operational date adjacent to its zone and each recorded action adjacent to its actor and result.
- **Do** use readable Spanish summaries before expandable technical evidence.

### Don't:

- **Don't** communicate a call state through color alone.
- **Don't** add elevated shadows to every panel or control.
- **Don't** replace the workhorse hierarchy with decorative display typography or monospace labels.
- **Don't** shrink the full desktop grid into the mobile viewport; use the documented stacking behavior.
- **Don't** replace control labels with standalone glyphs or emoji.
- **Don't** assign permanent outcome meanings to the ordered chart-series palette.
- **Don't** render missing telemetry as a measured zero or present a SIP endpoint as a verified person.
- **Don't** hide operational limits, action labels, or evidence when records stack on mobile.
