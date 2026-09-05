# Alcance del producto

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python, FastAPI, Uvicorn, SQLite, PJSUA2 embebido y voces locales. El navegador
presenta operación y analítica; el mismo proceso conserva la cola y las llamadas.
Los gráficos se sirven localmente y los reportes Excel se generan en Python.

## Product Purpose

Gestionar campañas salientes por SIP, reproducir mensajes personalizados,
recibir opciones DTMF y enlazar al contacto con un agente. Conservar evidencia
de llamadas, intentos, AMD, tiempos, enlaces y terminaciones para su análisis.

## Users

Operadores de campañas en español o inglés, administradores de telefonía y analistas.
Cada rol dispone de permisos propios en el panel y en la API. La interfaz, las
fechas, los números y las exportaciones manuales siguen el idioma elegido por
cada navegador. La apariencia puede alternarse entre tema claro y oscuro; la
primera visita sigue la preferencia del equipo y las elecciones posteriores se
conservan localmente.

## Capabilities and Constraints

Una campaña activa con sesiones concurrentes configurables. Una a ocho troncales
con distribución y respaldo. Dos canales reservados por sesión. Python conserva
el puente de audio hasta el cierre; no se requiere una central externa.

La aplicación y su control están escritos en Python con bibliotecas nativas
para SIP y voz. Piper y Kokoro utilizan inferencia local; AMD aplica reglas acústicas sin
modelos entrenados. La configuración y los secretos operativos se guardan en TOML;
las cuentas web utilizan hashes de contraseña en SQLite.

Incluye plantillas, vista previa TTS, agenda persistente, dashboard, CDR, Excel,
reportes automáticos, alertas locales, roles, auditoría y grabación Ogg Opus desde
evidencia humana. Las grabaciones requieren permisos y tienen retención configurable.
AMD puede conservar temporalmente sólo el saludo analizado para que un operador
lo escuche y lo etiquete como persona o buzón; la retención y el máximo de muestras
son configurables y el audio puede eliminarse sin borrar el CDR.

## Operating Context

Un proceso de aplicación en Linux/macOS; el despliegue administrado utiliza
Ubuntu y systemd. El HTTP se sirve en loopback, con acceso externo mediante un
túnel o proxy configurado por el operador. La simulación permite probar el flujo
sin conexión telefónica. Los archivos de ejemplo contienen datos sintéticos.

## Evidence on Hand

El estado de una llamada describe señales observadas, no identidad física. Una
respuesta SIP puede ser humana o de buzón; AMD entrega una clasificación probable
aunque utilice reglas deterministas. Los datos desconocidos siguen siendo desconocidos.

Las pruebas automatizadas cubren simulación e integración SIP por localhost.
La calidad del audio, AMD, latencia y capacidad requieren validación por red,
proveedor y hardware. Consulta [verificación](docs/verification.md).
