# Configuración

La configuración y sus secretos se guardan en TOML. El despliegue utiliza
`/etc/pythonblastertts/config.toml`; el desarrollo utiliza `config.toml` junto al
repositorio. No se leen contraseñas desde `.env`.

La referencia completa de campos está en [config.example.toml](../config.example.toml).
La [plantilla de producción](../deploy/config.example.toml) utiliza rutas de
servidor. Los fragmentos de esta guía se editan dentro de las secciones existentes;
no deben pegarse creando secciones duplicadas.

## Panel, datos y voz

| Campo raíz | Función |
|---|---|
| `mode` | `simulation` para pruebas; `sip` para telefonía real |
| `web_port` | Puerto HTTP local, predeterminado 8765 |
| `web_public_url` | Origen externo exacto, por ejemplo `https://tts.example.com` |
| `data_dir` | SQLite, archivos temporales, grabaciones y reportes |
| `reporting_timezone` | Zona IANA para presentar fechas; la base conserva UTC |
| `report_max_rows` | Límite por exportación; reduce el período si se excede |
| `voice_model` | Archivo Piper `.onnx`, acompañado por `.onnx.json` |
| `tts_workers` | Síntesis simultáneas, de 1 a 8; empieza con 2 y mide |
| `tts_timeout` | Límite de espera de síntesis en segundos |

Los campos raíz se escriben antes de cualquier `[seccion]`. Las rutas relativas
se resuelven junto al TOML. El servicio suministrado requiere los datos en
`/var/lib/pythonblastertts` y la voz dentro de su carpeta `voices`.

`web_public_url` no admite rutas, credenciales, comodines ni parámetros. Debe
coincidir con el origen del navegador. Un esquema externo `https` marca las
cookies como Secure, pero no habilita HTTPS en Uvicorn. En desarrollo local puede
estar vacío; el servicio de producción exige un valor y autenticación activa.

La voz predeterminada es `es_MX-claude-high`. El instalador la descarga si falta.
Para otra voz Piper, configura su nombre antes de preparar una instalación nueva
o descarga el modelo y su JSON al directorio de voces y cambia `voice_model` con
el servicio detenido. La vista previa utiliza el mismo modelo que las llamadas.

## Una troncal SIP

Con `trunks` vacío o ausente, `[sip]` define una ruta con identificador `default`.
No se necesita una segunda troncal para operar.

| Campo de `[sip]` | Valor esperado |
|---|---|
| `domain` | Host o `host:puerto`, sin prefijo `sip:` |
| `username` | Identidad SIP de la cuenta |
| `password` | Contraseña de la troncal |
| `auth_username` | Usuario de autenticación; vacío utiliza `username` |
| `caller_id` | Identidad de origen autorizada; vacío utiliza `username` |
| `registrar` | URI de registro, por ejemplo `sip:sip.proveedor.example:5060` |
| `proxy` | Proxy saliente opcional, por ejemplo `sip:sbc.proveedor.example;lr` |
| `registration_enabled` | `true` para REGISTER; `false` para autenticación por IP |
| `transport` | `udp` o `tcp` |
| `local_port` | Puerto SIP del servidor local; no es el puerto remoto |
| `bind_address` | Dirección local de escucha; por defecto `0.0.0.0` |
| `public_address` | IP pública anunciada si hay NAT estático |
| `rtp_port` | Inicio par del rango de medios UDP |
| `rtp_port_range` | Amplitud del rango; al menos dos puertos por canal |
| `dial_format` | `as_entered` o `mexico_52`, según el proveedor |

Una cadena de Asterisk como `register => usuario:clave@servidor:5060/usuario`
se traduce a `username`, `password`, `domain` y `registrar`. El sufijo de contacto
de ese formato no es una opción adicional del TOML. PJSUA2 construye su registro.

Para claves con `$` o barras invertidas se pueden usar cadenas literales TOML:

```toml
[sip]
password = 'CLAVE_DE_EJEMPLO'
```

Si la clave contiene una comilla simple, utiliza una cadena con comillas dobles y
los escapes TOML apropiados. El formulario no devuelve las claves guardadas;
al editar una troncal, el campo vacío conserva la contraseña existente.

## Marcación

La captura elimina `+`, espacios, paréntesis y guiones del teléfono del contacto
y del agente. `as_entered` no agrega prefijos. `mexico_52` normaliza a 52 más los
10 dígitos nacionales, sin `+`. No se agrega un prefijo de salida de una central.
Las identidades y el formato deben estar autorizados por el proveedor.

## Capacidad y tiempos

| Campo raíz | Alcance |
|---|---|
| `concurrency` | Sesiones simultáneas, de 1 a 30 |
| `trunk_channels` | Canales globales, de 2 a 60 |
| `calls_per_second` | Ritmo máximo global de nuevas llamadas, incluido el agente |
| `ring_timeout` | Espera de respuesta del contacto, en segundos |
| `agent_timeout` | Espera de respuesta del agente, en segundos |
| `choice_timeout` | Espera de una opción DTMF, en segundos |
| `max_call_seconds` | Duración máxima de la sesión completa |
| `max_repeats` | Límite de repeticiones solicitadas por teclado |

Se exige `2 * concurrency <= trunk_channels`. Por ejemplo, 10 canales permiten
como máximo 5 sesiones reservadas. A esto se suman los límites de cada troncal.
El máximo del software no sustituye una prueba de carga del servidor y proveedor.

## Varias troncales

Se admiten hasta ocho perfiles. Al existir `[[trunks]]`, esos perfiles sustituyen
la ruta implícita de `[sip]`. También pueden administrarse en **Operación → Troncales**.
Ejemplo de dos perfiles; los parámetros globales siguen al principio del TOML:

```toml
routing = "priority"
concurrency = 3
trunk_channels = 10
calls_per_second = 1.0

[[trunks]]
id = "principal"
name = "Troncal principal"
enabled = true
priority = 10
weight = 1
channels = 6
calls_per_second = 1.0

[trunks.sip]
domain = "sip.principal.example"
username = "USUARIO_PRINCIPAL"
password = 'CLAVE_PRINCIPAL'
registrar = "sip:sip.principal.example:5060"
registration_enabled = true
transport = "udp"
local_port = 5060
rtp_port = 10000
rtp_port_range = 100

[[trunks]]
id = "respaldo"
name = "Troncal de respaldo"
enabled = true
priority = 20
weight = 1
channels = 4
calls_per_second = 1.0

[trunks.sip]
domain = "sip.respaldo.example"
username = "USUARIO_RESPALDO"
password = 'CLAVE_RESPALDO'
registrar = "sip:sip.respaldo.example:5060"
registration_enabled = true
transport = "udp"
local_port = 5070
rtp_port = 10200
rtp_port_range = 100
```

Menor prioridad numérica significa ruta preferida. Entre iguales, `priority`
reparte de forma equilibrada y `weighted` utiliza `weight`. Cada sesión reserva
sus dos canales en una misma troncal. Los límites globales y por ruta se aplican
juntos, incluidos los INVITE del agente.

Una ruta sin registro disponible no recibe nuevas llamadas. Un rechazo final
408/502/503/504 antes de contestar puede provocar otro intento por una ruta distinta.
Un 403 o un ocupado no disparan ese cambio. No se migra una conversación establecida
ni se duplica un INVITE todavía activo. El CDR conserva los intentos anteriores.

## Puertos y red

El panel HTTP y la telefonía utilizan redes distintas. El túnel web no transporta
SIP/RTP. El proveedor debe alcanzar los puertos acordados en el servidor y aceptar
su IP de origen. En NAT estático, anuncia `public_address` y conserva los puertos
al reenviarlos. STUN, TURN y compatibilidad universal con CGNAT no están implementados.

Por defecto, SIP utiliza 5060 y RTP/RTCP el rango UDP 10000–10200. Para varias
troncales configura rangos de medios separados; el ejemplo anterior usa puertos
SIP separados también. El instalador no modifica el firewall. No abras todo UDP:
aplica las direcciones y rangos que correspondan a tu proveedor.

## Acceso, AMD, grabaciones y automatización

- `[auth]`: sesiones y administrador inicial. El bootstrap sólo crea una cuenta
  cuando la base no tiene usuarios. Las claves posteriores de usuarios se guardan
  como hashes en SQLite; las claves SIP permanecen en TOML.
- `[amd]`: perfil acústico; consulta [AMD](amd.md). El ejemplo está activado y
  cuelga los resultados inciertos. Una configuración antigua sin sección AMD
  conserva la detección desactivada.
- `[recordings]`: activación, retención, espacio máximo y espacio libre mínimo.
- `[automation]`: sondeo de agenda, margen de retraso, umbrales de alertas y
  retención de reportes. Véase [uso del panel](usage.md).

## Aplicar cambios

Las opciones disponibles en **Operación → Configuración** se validan y guardan
en TOML; los cambios del motor requieren que no haya campañas activas. Si editas
el archivo manualmente, termina las llamadas y reinicia el servicio:

```bash
sudo systemctl restart blaster
sudo journalctl -u blaster -n 60 --no-pager
```

En desarrollo, valida con `.venv/bin/python run.py --config config.toml --check`.
En producción, el servicio ejecuta su comprobación antes de iniciar. La
[guía de administración](production.md) documenta una comprobación manual.
