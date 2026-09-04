# Uso del panel

Para instalar el servidor consulta [INSTALL.md](../INSTALL.md). Esta guía parte
de un panel disponible y una cuenta de usuario creada.

## Acceso y roles

En producción, el instalador genera las credenciales del primer administrador
en `[auth]` del TOML. En desarrollo local sin bootstrap, el primer acceso permite
crearlo. Las cuentas del panel son independientes de los usuarios Linux.

| Rol | Acceso |
|---|---|
| Administrador | Operación, configuración, troncales, usuarios y auditoría |
| Operador | Campañas, plantillas, agenda, reportes, alertas y grabaciones |
| Analista | Consulta y exportación; no modifica datos ni escucha grabaciones |

Los usuarios se administran en **Operación → Usuarios**. Debe quedar un
administrador activo. Los cambios de acceso revocan las sesiones correspondientes.

## Crear una campaña

1. Abre **Campañas → Nueva campaña** y asigna un nombre.
2. Selecciona **País de los contactos**. México (+52) viene seleccionado.
3. En **Transferencias**, captura un número nacional por línea y elige su país.
   Selecciona la distribución y cuánto esperar cuando todo el pool esté ocupado.
4. Pega los contactos o importa un CSV o XLSX con números nacionales, sin el código de
   país. Escribe el mensaje o selecciona una plantilla.
5. Revisa el texto personalizado y pulsa **Escuchar TTS**.
6. En **Cuándo ejecutar la campaña**, elige **Guardar borrador**, **Iniciar ahora**
   o **Programar**. El botón final realiza la opción seleccionada.

Ejemplo ficticio para simulación:

```csv
Credito,Telefono,nombre,fecha,folio
CRED-001,5550000101,Ana,viernes,A102
CRED-002,5550000102,Luis,lunes,B203
```

```text
Hola {nombre}. Te recordamos tu cita del {fecha}. Tu folio es {folio}.
```

Las columnas `Credito` y `Telefono` son obligatorias en cada fila. También se
reconocen `Crédito` y `Teléfono`, sin distinguir mayúsculas. El crédito se conserva
como texto, incluidos sus ceros iniciales. Todas las demás columnas las defines tú y están disponibles como
variables: no hay una lista fija de campos de la plataforma. Por ejemplo:

```csv
Credito,Telefono,Nombre completo,Saldo pendiente,Fecha de pago,Empresa
000184,5550000101,Ana Martínez,1250.50,10 de septiembre,Empresa de ejemplo
000205,5550000102,Luis Pérez,850,15 de septiembre,Otra empresa
```

```text
Hola {Nombre completo}. Te llamamos de {Empresa}. Tu saldo es {Saldo pendiente}
y tu fecha de pago es {Fecha de pago}.
```

En **Variables de tus contactos**, cada botón inserta el encabezado exacto en el
cursor del mensaje y muestra un ejemplo de la primera fila. Se admiten espacios,
acentos y signos como `{Saldo ($)}`. Respeta las mayúsculas del encabezado; se
eliminan sus espacios iniciales/finales. Los encabezados vacíos, repetidos, con
llaves o saltos de línea se rechazan. Cada llamada, la vista previa y el TTS usan
los valores de su fila. Las plantillas pueden usar estos mismos encabezados; si
falta alguno en la lista de contactos, la campaña no se crea. `{{texto}}` produce
llaves literales. Los valores se insertan como texto, sin ejecutar expresiones ni
interpretar otras variables dentro de una celda.

Para Excel, usa `.xlsx`, encabezados en la primera fila y una fila por contacto.
Se carga la primera hoja visible compatible; **Hoja del Excel** permite cambiarla.
Las celdas vacías se conservan como texto vacío. Las fechas se convierten a
`AAAA-MM-DD`; los números enteros no reciben `.0`. Para teléfonos o folios con
ceros iniciales, usa celdas de texto o un formato compuesto por ceros (`00000`).
Los importes conservan su valor numérico: escribe la moneda o la fecha en palabras
en una celda de texto si quieres que el TTS la lea así. Reemplaza las fórmulas y
errores por valores antes de importar. Las hojas no se combinan automáticamente.

El CSV admite coma, punto y coma o tabulador, UTF-8, UTF-16 con BOM y Windows-1252.
Se permiten archivos de hasta 8 MB, 10 000 contactos, 100 columnas adicionales a
Credito y Telefono, encabezados de hasta 64 caracteres y celdas de hasta 1000 caracteres.
Cada mensaje resultante admite hasta 4000 caracteres. No se requiere migración de
la base de datos: las variables continúan guardándose con cada contacto.

El país se aplica a todas las filas de esa campaña. Para llamar a otro país, crea
otra campaña con ese destino. Por ejemplo, México convierte `5512345678` en
`525512345678`; Estados Unidos convierte `2025550123` en `12025550123`. No necesitas
escribir `+`. La conversión usa reglas locales y no consulta servicios de geolocalización.

Se aceptan números que ya traen el prefijo cuando se pueden interpretar sin
ambigüedad; no se duplica. Algunos países requieren un prefijo nacional, como el
`0` de Reino Unido: usa el formato del ejemplo que muestra el campo. Un número
ambiguo o con longitud incorrecta se rechaza antes de crear la campaña y se
identifica la fila del CSV. La validación del formato no verifica que exista la línea.

Los números se guardan con el código internacional y sin `+`, también para
`{telefono}`, el TTS, los CDR y las exportaciones. Las campañas existentes conservan
sus números. Usa `sip.dial_format = "as_entered"` para destinos internacionales;
consulta [configuración](configuration.md). La troncal debe admitir los destinos.
El menú de opciones se agrega automáticamente. Los datos de ejemplo no son una
lista para marcar por una troncal real.

La [vista previa TTS](tts-preview.md) usa el primer contacto y no genera llamadas.
En simulación necesita Piper y el modelo instalados para producir voz real.

## Durante la campaña

La aplicación opera una campaña a la vez y admite varias sesiones simultáneas:

- **Iniciar** admite contactos respetando canales, concurrencia y CPS.
- **Pausar** deja de admitir sesiones nuevas; las ya admitidas continúan.
- **Detener** cancela pendientes y termina las llamadas activas.
- Cerrar el navegador no detiene el motor. Cerrar o reiniciar el servicio sí
  termina las llamadas; una campaña manual interrumpida requiere reanudación.

AMD, si está activo, analiza el saludo. Un humano probable pasa a TTS; un buzón
probable se cuelga. Los inciertos siguen la política configurada. Después:

1. Se genera y reproduce el mensaje personalizado.
2. **1** repite; **2** marca al agente manteniendo al contacto en espera.
3. Cuando el agente contesta y tiene audio activo, se conecta el puente.
4. Cuando uno cuelga, termina también el otro tramo.

El agente debe poder recibir la llamada; contestar desde un buzón también produce
una respuesta SIP. No hay detección AMD en el tramo del agente. El puente ocupa
dos canales hasta el cierre. Las causas de fallo y cada intento quedan registrados.

## Pool de transferencia

Cada campaña admite de 1 a 50 teléfonos de transferencia, con un número nacional
por línea. Todos los teléfonos de ese pool usan el país seleccionado en **País
del pool**, que puede diferir del país de los contactos. Se rechazan duplicados
después de normalizar: `5512345671` y `525512345671` son el mismo destino en México.

| Distribución | Selección entre los números libres |
|---|---|
| Rotación en orden | Continúa desde la posición siguiente y omite ocupados. Es la opción predeterminada; conserva la posición al reiniciar. |
| Aleatoria | Elige al azar. Un número puede repetirse una vez que vuelve a estar libre. |
| Prioridad de lista | Elige el primer número libre en el orden escrito. |

El número queda reservado antes de enviar la marcación, incluso durante la espera
por CPS y el timbrado. La reserva es global entre las troncales de esta instancia
y se mantiene hasta confirmar el cierre del tramo. Si A ya está en conversación,
la siguiente transferencia selecciona B. Si sólo A está libre, puede reutilizarse
cuando su llamada anterior haya terminado.

Si todos están ocupados, el contacto escucha el tono de espera. La cola respeta
el orden de llegada y asigna el siguiente teléfono disponible. **Espera si todos
están ocupados** admite de 0 a 300 segundos; empieza en 30. Con 0 no se hace cola.
Al vencer el plazo se reproduce un aviso de indisponibilidad y termina la llamada.
Colgar, detener la campaña o cerrar el sistema cancela esa solicitud. El límite
global `max_call_seconds` sigue aplicando, incluida la espera.

En cuanto todos los teléfonos quedan reservados, el planificador pausa
automáticamente la originación de contactos nuevos. Las llamadas que ya estaban
en curso continúan y conservan su lugar si solicitan transferencia. Cuando se
confirma el cierre de cualquier teléfono, la campaña reanuda la marcación por sí
sola. La campaña permanece **En curso** durante esta pausa de capacidad; el panel
muestra `0 de N libres` y el motivo, y cada pausa y reanudación queda en auditoría.

La espera del pool es distinta de `agent_timeout`, que limita el timbrado del
teléfono seleccionado. Si ese teléfono rechaza la llamada o no responde, se
conserva el comportamiento de aviso y cierre. El sistema no consulta la ocupación
externa de una línea; sólo conoce sus propias reservas. Si el cierre SIP no se
confirma, el número continúa reservado en lugar de admitir otra transferencia.

En el detalle de campaña, abre **Pool de transferencia** para consultar números
libres, reservados y en conversación. Los CDR y Excel guardan el destino realmente
seleccionado, la distribución y los segundos de espera para obtener un número.
La cronología incluye entrada a la cola, selección y vencimiento. Las campañas
existentes conservan su teléfono como pool de un número.

## Plantillas y programación

En **Operación → Plantillas** guarda mensajes y un pool opcional, con país,
distribución y espera máxima. Usar una plantilla copia sus valores a la campaña;
editarla después no cambia campañas existentes.

La ejecución se decide en **Nueva campaña → Cuándo ejecutar la campaña**:

- **Guardar borrador** (predeterminado): conserva la campaña sin hacer llamadas.
  Después abre su panel y pulsa **Iniciar llamadas** o **Iniciar simulación**.
- **Iniciar ahora**: el botón **Crear e iniciar llamadas** (o simulación) guarda
  y arranca la campaña. Si otra campaña está activa o no hay troncal lista, se
  muestra el motivo y no se crea otra campaña. Si la troncal cambia justo después
  de guardarla, se conserva el borrador y se informa que no pudo iniciarse.
- **Programar**: elige una fecha y hora futuras y una zona horaria. Se propone la
  zona configurada en la aplicación. **Programar campaña** guarda los contactos
  y el horario juntos. Requiere las tareas programadas activas en Configuración.
  Las horas ambiguas o inexistentes por cambios de horario se rechazan. Si una
  hora se repite, elige otra hora o selecciona UTC e introduce su hora equivalente.

La revisión del texto y del TTS está disponible antes de completar el horario.
Las campañas programadas muestran **Programada** y su fecha/zona en el panel.
Puedes cancelar el horario o iniciar antes con **Iniciar ahora y cancelar horario**.
**Operación → Historial de programación** permite consultar los resultados, abrir
campañas y cancelar horarios pendientes; ya no contiene un formulario de creación.
La API anterior de programación sigue disponible para integraciones existentes.

La agenda vive en SQLite y requiere la aplicación abierta y el equipo encendido.
Si el motor está
ocupado o no tiene ruta disponible, espera hasta `late_schedule_minutes`; después
vence y genera una alerta. Iniciar manualmente cancela la programación pendiente.
Detener cancela los contactos pendientes; para conservarlos utiliza Pausar.

## Dashboard, llamadas y CDR

El dashboard filtra por fecha, campaña y origen SIP/simulación. Una respuesta SIP
no certifica que haya contestado una persona; AMD se muestra por separado.

En **Llamadas**, abre una sesión para consultar sus tramos y cronología:

- Marcación, timbrado, respuesta y medios activos.
- Call-ID, respuesta SIP final y troncal utilizada en cada intento.
- Resultado AMD, repeticiones y solicitud DTMF 2.
- Respuesta del agente, duración del puente y cierre de cada tramo.
- Actor observado del cierre: cliente, agente, operador, sistema o desconocido.

Los roles de los tramos indican endpoints SIP; no identifican físicamente a la
persona que colgó. Los registros antiguos con datos faltantes se muestran como
tales y no reciben mediciones inventadas.

## Trazabilidad por Credito o Telefono

**Trazabilidad** busca un identificador exacto en todo el historial, sin limitarse
a una campaña. Selecciona **Credito** o **Telefono** y escribe el valor. Para el
teléfono puedes pegar `+`, espacios, guiones o paréntesis; la consulta utiliza el
número internacional normalizado. El resultado reúne cada intento iniciado y
muestra campaña, fecha, resultado y disponibilidad de grabación. Desde una fila
puedes abrir el CDR completo.

**Descargar XLSX** genera el reporte analítico completo de ese identificador.
**Descargar grabaciones + reporte** produce un ZIP con el mismo XLSX, los archivos
Ogg Opus que continúan disponibles y `manifest-grabaciones.csv`. El manifiesto
incluye todas las llamadas e indica cuáles no tuvieron grabación, vencieron o ya
no tienen archivo; la descarga nunca oculta esas ausencias. Se aplica
`report_max_rows` y no se entrega un subconjunto silencioso.

Administradores y operadores pueden descargar el paquete de audio. Los analistas
pueden consultar la trazabilidad y exportar el XLSX, pero no escuchar ni descargar
grabaciones. Cada XLSX y ZIP queda en la auditoría con actor, identificador y
cantidad de llamadas. Las campañas anteriores a esta función conservan Crédito
vacío: siguen visibles por teléfono, pero no se pueden volver a iniciar con esos
contactos. Crea una campaña nueva con ambas columnas para marcarlos.

## Reportes y alertas

**Reportes** exporta CSV o Excel con resumen, tendencia, resultados, campañas,
CDRs, tramos, eventos y definiciones. Sólo se genera un reporte a la vez. Si se
alcanza `report_max_rows`, reduce el período; no se entrega un archivo parcial.

En **Operación → Reportes automáticos** programa Excel/CSV diario o semanal,
con hora, zona y últimos N días completos. Los archivos se descargan desde el
panel. Los reportes y alertas no envían correo ni mensajes a servicios externos.

Las alertas incluyen troncales no disponibles, tasa de fallos, agenda vencida,
problemas de grabación/espacio y reportes disponibles. Reconocer una alerta no
borra su historial. Los umbrales se configuran en TOML o en Configuración.

## Grabaciones

Con `[recordings].enabled = true`, se graba desde un resultado AMD de humano
probable o una interacción DTMF 1/2. Un buzón o incierto sin interacción no activa
la captura. AMD no garantiza una clasificación perfecta.

La mezcla incluye contacto, TTS desde el inicio de captura y agente durante el
puente. El WAV temporal se comprime localmente a Ogg Opus. En **Campañas → detalle
de campaña**, selecciona un contacto para encontrar **Grabación de llamada**,
con reproducción, pausa, avance y descarga. También está disponible en el CDR
completo. Los administradores y operadores pueden escucharla; los analistas no.
La grabación aparece al terminar la llamada y procesarse el audio. Mientras tanto
se muestra su estado; las llamadas sin captura o con audio vencido lo indican.
La actualización de actividad conserva la reproducción; cambiar de contacto o
sección la pausa. En simulación se etiqueta como
sintético. El audio se elimina según retención/espacio y su CDR se conserva.

Si falta espacio, se omite la captura y se genera una alerta; la llamada continúa.
Consulta [administración](production.md) para respaldar tanto SQLite como los archivos.

## Volver a ejecutar y duplicar

En el detalle de una campaña:

- **Volver a ejecutar** está disponible cuando la campaña está finalizada o
  detenida. El formulario muestra cuántos contactos volverán a recibir una llamada,
  permite asignar un nombre y añadir un motivo opcional. Al confirmar se crea e
  inicia una nueva ejecución con **todos** los contactos, incluso quienes ya
  contestaron. Los teléfonos, variables, mensajes personalizados y pool se copian
  tal como estaban guardados, incluido el Credito; no se vuelven a interpretar
  prefijos de país.
- **Duplicar** crea un borrador independiente en el modo actual, con nombre y motivo
  opcionales. Conserva los contactos y la configuración de campaña, sin heredar
  horarios, resultados, CDR ni grabaciones. El borrador se inicia desde su detalle.
- **Historial de ejecuciones** muestra la secuencia, quién la creó, el inicio y su
  responsable cuando existe registro, el motivo y los recuentos de llamadas.
  Cada entrada abre sus propios contactos, resultados y CDR. Una copia conserva
  también un enlace a su campaña de origen.

La ejecución anterior nunca se borra ni se reinician sus trabajos. La nueva tiene
identificadores de campaña y llamada propios. Duplicar inicia una nueva secuencia;
volver a ejecutar continúa la del origen. Los parámetros globales (AMD, capacidad,
TTS y troncales) son los que estén activos al iniciar el nuevo envío.

La auditoría conserva actor, fecha, origen, nueva campaña, número de ejecución,
modo, alcance, cantidad de contactos y motivo, además del resultado del inicio.
Los administradores pueden consultarla en **Operación → Auditoría**. Los operadores
pueden duplicar y reejecutar; los analistas sólo consultan. Los registros históricos
sin autor conservan esa ausencia, sin asignarles uno supuesto.

Repetir una petición con la misma clave de solicitud no crea otro envío. Si el
motor deja de estar disponible después de guardar, se abre el nuevo borrador con
el error; se puede iniciar desde ahí. Mientras exista una ejecución pendiente de
esa misma secuencia, hay que resolverla antes de crear otra. La reejecución requiere
el mismo modo de origen; para cambiar de simulación a SIP, crea una copia y revisa
su borrador antes de iniciar.

La migración de base v4 a v5 crea un respaldo `*.before-executions-*.bak` cuando
existen campañas. Reinicia la aplicación tras actualizar para cargarla.


## Reintentos automáticos por contacto

En **Nueva campaña → Reintentos sin contacto humano**, elige el máximo de
intentos (1 a 10, incluyendo la primera llamada), la espera y los resultados que
permiten repetir. Por ejemplo, **3 intentos y 5 minutos** permite la llamada
inicial y hasta dos reintentos, separados por al menos cinco minutos desde que
finaliza la llamada anterior. La espera admite segundos, minutos u horas, entre
1 segundo y 7 días. El valor inicial es un solo intento: las campañas existentes
no empiezan a repetir llamadas al actualizar.

Puedes elegir **Sin respuesta**, **Ocupado**, **Buzón probable**, **AMD incierto**
y **Fallo temporal de la troncal**. Esta última opción cubre SIP 500, 502, 503 y
504 antes de una respuesta; no vuelve a marcar por errores de credenciales,
destino inválido, generación de voz o transferencia. Los estados de AMD siguen
siendo estimaciones acústicas, no una identificación infalible.

Se detienen los reintentos cuando se detecta un humano probable, hay interacción
del teclado, se solicita un agente o empieza el mensaje. Esto evita repetir a
quien ya pudo escucharlo aunque no elija una opción. Con AMD desactivado, o con
un resultado incierto que se configure para continuar, iniciar el mensaje también
impide reintentar. Una llamada interrumpida al cerrar la aplicación, o cuyo cierre
no pudo confirmarse, no se repite automáticamente.

En el detalle del **borrador**, abre la línea con el límite y la espera para cambiar
la política y pulsa **Guardar reintentos**. Admin y operador pueden hacerlo antes
del primer inicio, también si el borrador está programado. Después del inicio la
política queda fija para esa ejecución; puedes duplicarla y configurar su nuevo
borrador. Las copias y nuevas ejecuciones heredan la política, comienzan con el
intento 1 y copian una sola vez cada contacto, sin sus resultados anteriores.

Durante una espera no se reservan canales. El motor continúa con los demás
contactos y respeta la concurrencia, CPS y disponibilidad de troncales. La fecha
indica cuándo un intento queda disponible; una pausa, una ruta en espera o falta
de capacidad puede retrasar su marcación. El motor mantiene una sola campaña
activa, incluidas sus esperas de reintento.

**Pausar** deja terminar las llamadas activas y conserva los reintentos pendientes.
**Detener** los cancela. Las fechas se guardan en SQLite; tras reiniciar, la campaña
queda pausada y se continúa con **Reanudar**. Los plazos vencidos quedan disponibles,
siempre sujetos a capacidad. La aplicación debe estar abierta y el equipo encendido.

El listado de campaña mantiene una fila por contacto con su último intento.
Selecciona el contacto para ver **Intentos de este contacto** y abrir cada intento,
su resultado, CDR y grabación cuando exista. El contador separa contactos e intentos.
**Exportar resultados** incluye todos los intentos, incluidos los pendientes;
los CDR, Excel y reportes automáticos incluyen los intentos que ya iniciaron.
Los CDR añaden ID del contacto dentro de la campaña, número de intento, ID del
anterior y fecha de disponibilidad, sin sobrescribir las columnas previas.

La auditoría registra la política inicial y sus cambios, programación, inicio y
cancelación de cada reintento, además del motivo para detenerlos. La migración a
base v6 guarda `*.before-retries-*.bak` si ya existen llamadas. Reinicia la
aplicación después de actualizar para cargar los cambios; no borres la base.
