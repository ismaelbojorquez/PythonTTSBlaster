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
2. Escribe el mensaje o selecciona una plantilla.
3. Captura el teléfono del agente que atenderá la opción 2.
4. Pega los contactos o importa un CSV.
5. Revisa el texto personalizado y pulsa **Escuchar TTS**.
6. Guarda la campaña y elige iniciar o programar su ejecución.

Ejemplo ficticio para simulación:

```csv
telefono,nombre,fecha,folio
525550000101,Ana,viernes,A102
525550000102,Luis,lunes,B203
```

```text
Hola {nombre}. Te recordamos tu cita del {fecha}. Tu folio es {folio}.
```

La columna `telefono` es obligatoria; las demás son variables. Se admiten hasta
10 000 contactos por campaña y 4000 caracteres por mensaje resultante. Los nombres
de variables son simples; no se ejecutan expresiones Python.

El menú de opciones se agrega automáticamente. La captura elimina `+` y otros
separadores del teléfono. El formato final depende de `sip.dial_format`;
consulta [configuración](configuration.md). Los datos de ejemplo no son una lista
para marcar por una troncal real.

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

## Plantillas y programación

En **Operación → Plantillas** guarda mensajes y un agente predeterminado. Usar una
plantilla copia sus valores a la campaña; editarla después no cambia campañas existentes.

En **Programar** o **Operación → Programación**, elige fecha, hora y zona IANA.
La agenda vive en SQLite y requiere el servicio encendido. Si el motor está
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
puente. El WAV temporal se comprime localmente a Ogg Opus. El CDR ofrece el
reproductor y descarga a los roles autorizados. En simulación se etiqueta como
sintético. El audio se elimina según retención/espacio y su CDR se conserva.

Si falta espacio, se omite la captura y se genera una alerta; la llamada continúa.
Consulta [administración](production.md) para respaldar tanto SQLite como los archivos.
