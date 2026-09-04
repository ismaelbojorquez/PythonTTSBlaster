# Verificación de la primera versión

## Operación, múltiples troncales y grabaciones — 3 de septiembre de 2026

- Suite completa: `BLASTER_NATIVE_TEST=1 .venv/bin/python -m pytest -q`,
  **83 aprobadas** en 37.94 s. Seis pruebas JavaScript de limpieza de números,
  zonas horarias y presentación de auditoría aprobadas. Ruff, sintaxis JavaScript
  y `pip check` correctos. Persisten dos
  avisos de obsolescencia en dependencias de TestClient.
- Se verificaron distribución ponderada 3:1, reserva de canales, respaldo por
  capacidad o fallo SIP final, funcionamiento con una sola troncal y enfriamiento
  de rutas. Un fallo 503 seguido de éxito en otra ruta conserva ambos intentos
  en el historial y un solo resultado final del contacto.
- Prueba nativa exclusivamente en localhost: dos cuentas SIP comparten transporte;
  cliente y agente se enlazan y sus tonos de 600/900 Hz aparecen en la grabación
  mezclada. Se espera el cierre real del WAV antes de comprimir: PJSIP libera el
  puerto de conferencia de forma asíncrona. El Opus resultante se reabre con audio,
  ocupa menos de la mitad del PCM de la prueba y el WAV temporal se elimina.
- Se probaron acceso inicial, roles, revocación de sesiones, protección del último
  administrador, auditoría sin secretos y persistencia del hash de contraseña.
  Límites y puertos se guardan en TOML; la contraseña SIP no se devuelve por API
  ni se copia a la tabla de troncales.
- Programación: despacho único, margen de retraso, zonas horarias y transiciones
  de horario. Reportes: una ejecución por vencimiento, descarga autenticada y
  alertas sin duplicación. Grabaciones: evidencia AMD/DTMF y caducidad del audio
  conservando el CDR.
- Navegador Chrome a 1440 × 1100 y 390 × 844, sobre base aislada de simulación:
  alta de plantilla, campaña desde plantilla, programación, reporte automático,
  navegación de administración, descarga Excel y reproducción de Opus. Sin errores
  de consola ni desbordamiento horizontal. El Excel descargado se reabrió con ocho
  hojas y 48 columnas CDR. Capturas en `.impeccable/review/operations/`.
- Correcciones de revisión: SIP/RTP editables directamente en Configuración,
  guardado desde navegador y persistencia en TOML comprobados; horarios de Nueva
  York mostrados en su propia zona aunque la global sea Ciudad de México;
  auditoría e historial con nombres operativos y evidencia técnica desplegable.
  El endpoint antiguo de concurrencia también exige rol administrador; las cuatro
  pruebas de gestión volvieron a pasar después de cerrar ese permiso.
- Validación adicional de migración de configuración: al usar `[[trunks]]`, un
  rango RTP pequeño en el bloque `[sip]` antiguo ya no limita la capacidad global.
  Las rutas vigentes siguen exigiendo puertos suficientes para sus propios canales.
  Caso nuevo aprobado junto con todas las pruebas de configuración.
- Revisión visual independiente: disposición final `ship`; las tres correcciones
  de su lista quedaron resueltas. Dictamen limitado a esa lista, documentado en
  `.impeccable/review/operations/verdict-pass.md`. El detector se ejecutó una vez
  en modo degradado por falta de parsers y emitió avisos de documentación, no una
  certificación completa de contraste/accesibilidad. Su aviso de comp pendiente
  corresponde a un artefacto anterior ajeno a esta ampliación.
- Paquete reinstalado y CLI instalada validada desde fuera del proyecto con
  `--check`; dependencias consistentes. Servidor de QA detenido al terminar.
- `config.toml` real validado con `--check`; credenciales SIP conservadas. La
  base del usuario no se usó como fixture ni se realizaron llamadas por su troncal.
  La migración operativa se ejecutará al iniciar la versión actualizada.

Estas pruebas verifican integración local, no disponibilidad de varias troncales
del proveedor ni precisión del AMD con personas reales. La grabación comienza
tras AMD humano probable o interacción DTMF; no incluye el saludo analizado.
La aplicación debe permanecer ejecutándose para lanzar campañas y reportes.

## Analítica, CDR y reportes — actualización del 3 de septiembre de 2026

- La migración se probó desde el esquema histórico y verifica que crea una copia,
  conserva la fila original y deja ASR/tiempos desconocidos sin inferir.
- El flujo de simulación prueba respuesta de los dos tramos, DTMF 2, puente y
  finalización por el agente; el resumen reconcilia intentos, respuestas y puentes.
- El flujo SIP nativo contra el peer local verifica Call-ID, respuesta de ambos
  tramos, transferencia, duración del puente y BYE remoto del agente.
- CSV se valida con BOM UTF-8 y el XLSX se reabre con sus ocho hojas, 46 columnas
  CDR y dos gráficos. Los textos importados se escriben como texto para impedir
  fórmulas inyectadas.
- Se inspeccionó el dashboard con 62 llamadas sintéticas aisladas a 1440 px y
  390 px; no hubo errores de consola ni desbordamiento horizontal móvil.
- Suite completa con SIP nativo: 75 pruebas correctas. Ruff sobre fuentes,
  pruebas y scripts: correcto. El Excel descargado desde el navegador se reabrió
  correctamente; se verificó que los teléfonos siguen siendo texto y las
  duraciones números, y que entradas que parecen fórmulas no se ejecutan.

## AMD sin IA — actualización del 3 de septiembre de 2026

- `BLASTER_NATIVE_TEST=1 .venv/bin/python -m pytest -q`: **73 aprobadas** en
  34.51 segundos. Permanecen dos avisos de dependencias de TestClient.
- Casos nuevos: saludo corto, voz prolongada, segmentos, tonos estables y dobles,
  DTMF acústico, clics, ruido bajo, DC, silencio, límite de tiempo sin muestras,
  saturación de cola, cancelación, políticas de inciertos y detección concurrente.
- SIP nativo en localhost: tres llamadas PCMU simultáneas con saludo artificial,
  pitido y silencio. Sólo la primera inicia TTS; las otras terminan sin transmitir
  audio. Se verifican estados, limpieza de llamadas y archivos temporales.
- La prueba nativa de reproducción/puente analiza primero un tono recibido y
  luego reutiliza la misma llamada para WAV, DTMF y conversación bidireccional.
- La prueba completa con Piper sigue aprobada. El nuevo AMD no incorpora IA;
  Piper conserva su función de síntesis existente.
- Ruff sin errores y cuatro pruebas de limpieza de números JavaScript aprobadas.
- `config.toml` validado con AMD activo, máximo 5000 ms e inciertos que cuelgan.
  No se cambió la configuración de autenticación SIP ni el formato de marcación.
- Estas pruebas demuestran reglas e integración, **no precisión de clasificación
  con saludos reales ni ahorro facturado**. Los datos acústicos son sintéticos.
  No se hicieron llamadas por la troncal para desarrollar AMD.

Los apartados siguientes conservan el historial de verificaciones anteriores.

## Selección de voz de baja latencia — 3 de septiembre de 2026

- Se comparó Piper `ald-medium`, Piper `claude-high` y Kokoro ONNX INT8 `ef_dora`
  con el mismo mensaje español. La troncal y el panel permanecieron cerrados.
- Tres ejecuciones: `claude-high` 0.62–0.73 s para 12.5–12.7 s de audio;
  `ald-medium` 1.49–2.24 s para 13.1 s; Kokoro 10.89–12.63 s para 11.0 s.
- Memoria residente máxima de los procesos: aproximadamente 316 MB para Piper
  `claude-high` y 552 MB para Kokoro ONNX INT8.
- Con `tts_workers = 2`, tres solicitudes terminaron a los 0.92, 1.25 y 3.19 s.
  Con tres trabajadores las mismas solicitudes necesitaron cerca de 6 s por
  contención. Se mantienen dos trabajadores.
- Se descargó la voz desde el catálogo oficial de Piper y se configuró
  `voice_model = "voices/es_MX-claude-high.onnx"`. La configuración se validó
  sin iniciar llamadas. Los tres audios comparables se conservaron en `examples/`.
- La medición comprueba latencia en este Mac; la preferencia de voz y su sonido
  después de G.711 deben revisarse escuchando los archivos y con una llamada de
  prueba autorizada.
- Se ejecutaron seis pruebas de configuración, panel y flujo nativo con la voz
  nueva: todas aprobadas. La llamada local reprodujo, repitió y enlazó al agente.
  Ruff y `pip check` sin errores; paquete reinstalado. No se inició la troncal.

Fecha: 3 de septiembre de 2026. Entorno: macOS arm64, Python 3.13,
PJSIP/PJSUA2 2.17 y Piper 1.7.0. Las versiones de Python están registradas en
`constraints.txt`.

## Resultados ejecutados

- `BLASTER_NATIVE_TEST=1 .venv/bin/python -m pytest -q`: **21 pruebas aprobadas**.
  Incluyen flujo de repetición y agente, límites de capacidad, ocupado, tiempos
  de espera, pérdida de registro, cancelación, recuperación, aislamiento de modos,
  plantillas/CSV, exportación, límites de origen y exclusión de una segunda instancia.
- La prueba nativa inicia un extremo SIP temporal en localhost, establece dos
  llamadas, reproduce y cancela WAV, recibe telephone-event, forma el puente,
  reenvía DTMF y detecta BYE remoto. Mide frecuencias del audio recibido para
  comprobar que cada extremo escucha al otro. No usa un proveedor telefónico.
- `.venv/bin/ruff check src tests scripts run.py`: sin errores.
- `pip check`: sin conflictos de dependencias. Pytest muestra dos avisos de
  deprecación procedentes de Starlette/AnyIO; no son fallos de las pruebas.
- Piper generó `examples/mensaje.wav`: PCM de 16 bits, mono, 22050 Hz, 9.07 segundos.
- El panel se verificó en navegador: creación de demostración, inicio, selección
  de contacto, opción 2, conversación con agente y cierre desde el agente. También
  se creó una campaña manual validando sus variables antes de guardarla.
- Navegación móvil: seleccionar un contacto enfoca y revela su detalle; el botón
  de retorno devuelve el foco al contacto. Revisión visual de los dos ajustes
  finales: disposición `ship`, ambos resueltos. No equivale a certificación completa
  de accesibilidad ni a pruebas de telefonía externa.

## Pendiente de infraestructura del usuario

No se ha registrado la aplicación en una troncal externa ni se han marcado
números reales. Faltan comprobaciones con sus datos: autenticación/registro,
formato de marcación, Caller ID autorizado, firewall/NAT, audio en ambos sentidos,
DTMF del proveedor, disponibilidad del destino agente y límites de canales/CPS.
No se hicieron pruebas de carga prolongada ni se certificó el límite de 30
sesiones en un hardware concreto.

El modo SIP implementado usa G.711 y UDP/TCP. TLS/SRTP, CGNAT con relé,
transferencia REFER, detección de contestadora y operación multiusuario no forman
parte del alcance inicial.

## Limpieza automática de números

- `.venv/bin/python -m pytest -q`: 42 aprobadas y 1 prueba nativa omitida.
  Se verificó que vista previa, API, almacenamiento y marcación eliminen `+`.
- `node --test tests/phone-input.test.mjs`: 4 aprobadas. Cubren CSV con columnas
  reordenadas, BOM, comillas, saltos de línea y signos `+` en otras variables,
  además de conservar la selección y el cursor durante la limpieza.
- Ruff sin errores. Reinstalación local del paquete completada.
- Chrome, 1440 px y 390 px: escritura, pegado, importación CSV, vista previa y
  guardado de borrador correctos; sin errores JavaScript ni desbordamiento móvil.
  Revisión visual completada. La prueba usó simulación y datos temporales; el
  servidor temporal se detuvo sin utilizar la troncal.
- El detector de diseño no encontró coincidencias, pero trabajó en modo limitado
  por falta de sus analizadores HTML. También señaló metadatos de composición
  antiguos; no se modificaron como parte de este ajuste del formulario.

## Corte durante la generación de voz tras contestar

Se reprodujo un fallo del reproductor: trataba cada EOF del tono de espera en
bucle como una finalización definitiva. El motor interpretaba esto como un fallo
de audio y colgaba si Piper aún estaba sintetizando. PJSUA2 emite ese callback
en cada repetición, como indica su
[referencia de AudioMediaPlayer](https://docs.pjsip.org/en/2.17/api/generated/pjsip/group/group__PJSUA2__MED.html).
El reproductor ahora notifica la finalización únicamente para archivos sin bucle.

- La prueba nativa de espera falló antes de corregir el código y pasó después.
- `BLASTER_NATIVE_TEST=1 .venv/bin/python -m pytest -q`: **45 aprobadas**.
  El nuevo recorrido completo usa Piper real, retrasa la síntesis 2.5 segundos,
  reproduce su WAV a través de RTP, recibe las opciones 1 y 2, enlaza al agente
  y termina correctamente cuando éste cuelga. Sólo utiliza localhost.
- Los fallos de reproducción conservan la operación, el código y el motivo de
  PJSUA2; los fallos de campaña conservan también la etapa. Se verificó que no
  se incluyera la contraseña SIP en el historial ni en los registros.
- Ruff sin errores y paquete reinstalado en `.venv`. No se reinició el proceso
  del operador ni se realizaron llamadas por la troncal durante estas pruebas.

## Tiempo de solicitud y timbrado del agente

La demora informada de 5–10 segundos no se reprodujo en localhost. Se midieron
0.064 segundos desde el envío del DTMF 2 del extremo de prueba hasta que el otro
extremo recibió el INVITE, tanto antes como después de añadir los registros.
Esto no mide la latencia de la troncal del usuario ni la entrega del DTMF desde
su teléfono. El historial antiguo sólo permitía conocer inicio de transferencia
y conexión; no permitía atribuir el tiempo intermedio a una causa.

Ahora se conservan por separado el envío del INVITE y las respuestas de la
transacción SIP, usando `onCallTsxState`. Los tiempos se cuentan desde que Python
procesa la opción 2, antes de detener la reproducción. La terminal incluye el
tiempo local de cola/envío y fecha y hora en los mensajes. No se registran
cabeceras SIP ni credenciales.

Se probó un agente local que primero responde 180 y demora 1.2 segundos antes de
responder 200: la solicitud siguió llegando en 0.064 segundos y el historial
conservó envío, timbrado y respuesta por separado. La opción 183 se describe como
progreso, sin afirmar que el teléfono esté timbrando.

- `BLASTER_NATIVE_TEST=1 .venv/bin/python -m pytest -q`: 45 aprobadas.
- Ruff sin errores; paquete reinstalado. Pruebas sólo en localhost.
- Pendiente: recoger estos tiempos en una nueva prueba del usuario con su troncal
  para localizar la demora real. No se cambió el límite de llamadas por segundo.
