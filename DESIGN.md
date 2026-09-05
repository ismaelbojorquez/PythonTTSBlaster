---
name: Blaster TTS
description: Una consola editorial de audio para operar campañas, llamadas y evidencia con precisión.
colors:
  signal-lime: "#d9ff43"
  signal-lime-hover: "#c8ef31"
  graphite: "#171714"
  mineral-paper: "#ffffff"
  mineral-canvas: "#f5f6f3"
  mineral-wash: "#eceee9"
  ink: "#171714"
  muted-ink: "#66685f"
  structural-line: "#dde0da"
  strong-line: "#aeb2aa"
  field-line: "#b8bcb4"
  dark-canvas: "#11120f"
  dark-paper: "#1b1c19"
  dark-wash: "#242620"
  dark-line: "#353731"
  dark-ink: "#f1f2ec"
  dark-muted: "#a6a89f"
  success: "#286b4c"
  warning: "#d28c28"
  danger: "#a83a32"
typography:
  display:
    fontFamily: '"Manrope Blaster", ui-sans-serif, sans-serif'
    fontSize: "clamp(30px, 3.2vw, 48px)"
    fontWeight: 640
    lineHeight: 1.02
    letterSpacing: "-0.055em"
  headline:
    fontFamily: '"Manrope Blaster", ui-sans-serif, sans-serif'
    fontSize: "clamp(28px, 2.3vw, 38px)"
    fontWeight: 640
    lineHeight: 1.08
    letterSpacing: "-0.045em"
  title:
    fontFamily: '"Manrope Blaster", ui-sans-serif, sans-serif'
    fontSize: "15px"
    fontWeight: 640
    letterSpacing: "-0.025em"
  body:
    fontFamily: '"Manrope Blaster", ui-sans-serif, sans-serif'
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: '"Manrope Blaster", ui-sans-serif, sans-serif'
    fontSize: "10px"
    fontWeight: 680
    letterSpacing: "0.055em"
  data:
    fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", monospace'
    fontSize: "13px"
    fontWeight: 500
rounded:
  status: "6px"
  control: "9px"
  field: "9px"
  panel: "14px"
  feature: "18px"
spacing:
  tight: "6px"
  control: "12px"
  group: "18px"
  panel: "23px"
  section: "30px"
  workspace: "36px"
components:
  button-primary:
    backgroundColor: "{colors.signal-lime}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.control}"
    padding: "10px 15px"
    height: "42px"
  button-secondary:
    backgroundColor: "{colors.mineral-paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 15px"
    height: "42px"
  field:
    backgroundColor: "{colors.mineral-paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "12px"
    height: "44px"
  card:
    backgroundColor: "{colors.mineral-paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "23px"
  navigation-active:
    backgroundColor: "{colors.mineral-canvas}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.control}"
    padding: "10px 11px"
---

# Design System: Blaster TTS

## Overview

**Creative North Star: "Signal Studio"**

Blaster es una consola de audio editorial: precisa, sobria y preparada para una operación densa. El grafito contiene la navegación y los paneles de escucha; el blanco mineral mantiene legibles los formularios, historiales y gráficas durante jornadas largas. El verde lima funciona como señal viva, de la misma manera que un nivel de audio indica que algo está listo, activo o requiere una acción.

La interfaz combina bordes finos, controles táctiles y datos monoespaciados. La profundidad es baja y ambiental. Las barras de señal son la geometría propia de la marca y aparecen en el símbolo, encabezados y superficies oscuras sin convertirse en ruido decorativo.

**Key Characteristics:**

- Navegación grafito con una superficie activa clara.
- Campo mineral claro y paneles blancos para lectura prolongada.
- Verde lima reservado para acción primaria, actividad y énfasis breve.
- Titulares compactos con Manrope local y cifras monoespaciadas.
- Líneas de señal y medidores rectos como lenguaje visual de audio.
- Movimiento corto que comunica estado y respeta reducción de movimiento.

## Colors

La paleta parte de neutrales minerales y utiliza el color sólo para comunicar prioridad o estado.

### Primary

- **Signal Lime:** acción primaria, estado vivo, selección y puntos de énfasis pequeños.
- **Graphite:** navegación, paneles de escucha, texto principal y gráficas dominantes.

### Secondary

- **Operational Green:** respuestas, conexiones y resultados favorables.
- **Measured Amber:** advertencias, simulación, buzón y series comparativas.
- **Quiet Red:** errores, cancelación y acciones destructivas.

### Neutral

- **Mineral Paper:** paneles y controles que deben leerse como superficies directas.
- **Mineral Canvas:** campo continuo de la aplicación.
- **Mineral Wash:** agrupación de filtros, controles y estados secundarios.
- **Structural Line:** divisiones de tablas, métricas y secciones.
- **Muted Ink:** instrucciones y metadatos.

### Dark Theme

- **Dark Canvas:** campo continuo de baja luminancia.
- **Dark Paper:** paneles elevados y formularios.
- **Dark Wash:** agrupaciones, filtros y estados secundarios.
- **Dark Line:** separación visible sin elevar el contraste en exceso.
- **Dark Ink / Muted:** texto principal y texto auxiliar para lectura prolongada.

El tema inicial sigue la preferencia del sistema operativo y la elección del
usuario se conserva en el navegador. Signal Lime mantiene el mismo significado
en ambos temas. Las gráficas cambian sus ejes, líneas, fondos y series junto con
la interfaz.

**The Signal Rarity Rule.** Signal Lime debe ocupar una porción pequeña de cada vista. Su rareza conserva la jerarquía de las acciones y el significado de actividad.

**The Evidence Color Rule.** El color de estado acompaña una etiqueta textual; nunca es la única evidencia de una condición.

## Typography

**Display Font:** Manrope Blaster, empaquetada localmente, con respaldo sans genérico.
**Body Font:** Manrope Blaster.
**Label/Mono Font:** SFMono-Regular, Consolas o Liberation Mono para cifras, tiempos e identificadores.

**Character:** Manrope aporta curvas limpias y titulares densos sin verse promocional. El mono distingue telemetría y números que deben compararse con rapidez.

### Hierarchy

- **Display** (640, 30–48px, 1.02): mensajes de reportes y estados vacíos con mucho espacio disponible.
- **Headline** (640, 28–38px, 1.08): título principal de cada vista.
- **Title** (640, 15px): paneles, tarjetas y grupos operativos.
- **Body** (400, 14px, 1.6): instrucciones y contenido; mantener líneas explicativas alrededor de 66–76 caracteres.
- **Label** (680, 10px, espaciado amplio): encabezados de tabla, filtros y metadatos compactos.
- **Data** (500, 13px): cifras, horas, teléfonos, contadores y valores técnicos.

**The Two Voices Rule.** Manrope describe; mono mide. No introducir una tercera familia tipográfica.

## Layout

En escritorio, un rail de 248px contiene toda la navegación y el espacio restante forma el área de trabajo. Por encima de 1500px el rail crece a 260px y el lienzo usa 48px de margen. Los paneles analíticos usan columnas fluidas con `minmax`; las tablas conservan su densidad dentro de contenedores desplazables.

La separación normal entre paneles es 18px y las secciones usan 30–36px. Las vistas de edición combinan un formulario ancho con una previsualización oscura de 350px; por debajo de 1000px se apilan. A 680px, la navegación se convierte en una tira horizontal desplazable y los paneles pasan a una columna. A 430px, métricas, filtros y paginación se apilan sin producir desplazamiento horizontal del documento.

**The Contained Scroll Rule.** Sólo la navegación, las pestañas o la tabla que necesita espacio pueden desplazarse horizontalmente; la página completa nunca debe hacerlo.

## Elevation & Depth

El sistema es plano por defecto. Líneas neutras separan la mayoría de las superficies y una sombra ambiental baja eleva paneles grandes o controles flotantes. Los paneles oscuros de audio y reportes usan una sombra más amplia para señalar un cambio de contexto.

### Shadow Vocabulary

- **Control:** `0 1px 1px rgb(23 23 20 / 7%), 0 6px 16px rgb(23 23 20 / 5%)` para botones elevados.
- **Panel:** `0 1px 0 rgb(23 23 20 / 4%), 0 10px 28px rgb(23 23 20 / 4%)` para tarjetas y ledgers.
- **Focused Dark Surface:** entre 16px y 40px de difusión con 12–14% de grafito para escucha, detalle y manifiestos.

**The Flat First Rule.** Una sombra no sustituye un borde ni crea jerarquía por sí sola; primero deben funcionar el orden, el contraste y la línea estructural.

## Shapes

Los controles usan esquinas de 9px y los paneles 14px. Las insignias permanecen compactas con 6px. La geometría distintiva es vertical y acústica: barras redondeadas de distinta altura, medidores rectos y líneas breves. Los círculos se reservan para pulsos de conexión y gráficas radiales.

## Components

### Buttons

- **Shape:** rectángulo táctil de 9px y al menos 42px de alto.
- **Primary:** Signal Lime con texto grafito, borde ligeramente más oscuro y sombra de control.
- **Hover / Focus:** desplazamiento de un píxel, borde más fuerte y aro de foco lima translúcido.
- **Secondary / Subtle:** papel con borde neutro, o superficie transparente que gana fondo al pasar el cursor.

### Chips

- **Style:** insignias rectangulares compactas con borde, fondo tonal y texto explícito.
- **State:** verde para actividad, ámbar para espera o simulación y rojo para error o cancelación.

### Cards / Containers

- **Corner Style:** 14px con línea Structural Line.
- **Background:** Mineral Paper para datos; Graphite para escucha, temporización y manifiestos.
- **Shadow Strategy:** Panel sólo en superficies principales.
- **Internal Padding:** 22–23px en escritorio y 18–20px en móvil.

### Inputs / Fields

- **Style:** papel, borde Field Line, 9px y 44px de altura mínima.
- **Focus:** borde oliva y halo lima de tres píxeles.
- **Error / Disabled:** texto Quiet Red para error y menor opacidad para controles deshabilitados.

### Navigation

El rail usa texto gris neutro sobre grafito. La sección activa cambia a una superficie mineral con texto oscuro; un indicador lima estrecho confirma la selección. En móvil, las secciones forman una tira horizontal con etiquetas y desplazamiento táctil.

### Signal Field

Una secuencia de barras verticales de distinta altura identifica voz, movimiento y capacidad. Puede aparecer en el símbolo, un encabezado o una superficie oscura, siempre como acento secundario y con baja densidad.

## Do's and Don'ts

### Do:

- **Do** reservar Signal Lime para la acción más importante y señales de actividad.
- **Do** usar cifras monoespaciadas en métricas, tiempos, contadores e identificadores.
- **Do** mantener tablas densas dentro de un scroll propio y una paginación visible.
- **Do** conservar transiciones de estado entre 180 y 260ms y respetar `prefers-reduced-motion`.
- **Do** emparejar toda codificación por color con texto legible.

### Don't:

- **Don't** copiar marcas, logotipos o componentes de otros productos de voz.
- **Don't** usar gradientes, cristal translúcido, botones redondos sobredimensionados o sombras duras.
- **Don't** convertir cada bloque en una tarjeta; una regla o un espacio suele ser suficiente.
- **Don't** usar el verde lima como fondo extenso ni como color de párrafos.
- **Don't** animar la entrada completa de una página operativa.
