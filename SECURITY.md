# Seguridad

## Información privada

El repositorio publica plantillas y datos sintéticos. La configuración de cada
instalación, su base, contactos, CDR, reportes y grabaciones son información privada.
Los archivos `config.toml`, `config.production.toml`, `.env`, bases y audios
generados están excluidos mediante `.gitignore`.

Un archivo ignorado puede haber sido agregado antes a Git: revisa también los
archivos versionados y el historial antes de publicar. Si se expuso una clave,
revócala o rótala; eliminarla del último commit no elimina las copias anteriores.

Los secretos SIP y el bootstrap del administrador se guardan en TOML. La aplicación
conserva hashes de contraseñas de usuarios y sesiones en SQLite. Los reportes y
respuestas de configuración no deben incluir contraseñas SIP ni secretos bootstrap.

## Despliegue

El panel escucha en loopback y utiliza autenticación por sesión y roles. El
acceso externo debe coincidir con `web_public_url`. El servicio suministrado
crea el administrador antes de servir tráfico y limita escritura a configuración
y datos. Consulta [INSTALL.md](INSTALL.md) y [producción](docs/production.md).

El HTTP interno está pensado para un proxy/túnel en el mismo servidor o reenvío
SSH. SIP usa UDP/TCP sin TLS/SRTP en esta versión. Configura la conectividad y los
permisos de red según el entorno y los datos que transportará la instalación.
Protege los respaldos igual que los datos originales.

## Comunicar una vulnerabilidad

Si el repositorio tiene habilitados reportes privados, utiliza **Security →
Report a vulnerability** en GitHub. Consulta el
[procedimiento de GitHub](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately).
Si esa opción no existe, solicita a los mantenedores un canal privado mediante
una incidencia sin incluir detalles de explotación ni información sensible.

Incluye de forma privada la revisión afectada, sistema operativo, pasos mínimos
de reproducción, impacto observado y un ejemplo con datos ficticios. No adjuntes
credenciales reales, bases de producción ni grabaciones de terceros.

Los errores de uso o instalación sin implicaciones de seguridad pueden reportarse
en una incidencia pública con registros depurados. Este documento no establece
un plazo de respuesta ni un programa de recompensas.
