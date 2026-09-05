# Documentación

## Instalar y operar

- [Ejecución local en Mac](local.md): carpeta del proyecto, `.venv` y localhost.
- [Instalación opcional en Ubuntu](../INSTALL.md): usuario `deploy`, Python y systemd.
- [Configuración](configuration.md): TOML, troncales, puertos, límites y voz.
- [Uso del panel](usage.md): campañas, trazabilidad, agenda, reportes y grabaciones.
- [Producción](production.md): servicio, actualización, respaldos y recuperación.
- [Solución de problemas](troubleshooting.md): instalación, acceso, SIP y audio.
- [AMD](amd.md): reglas acústicas, incertidumbre y calibración.
- [Vista previa TTS](tts-preview.md): escuchar el mensaje antes de crear la campaña.
- [Evaluación de Kokoro](kokoro-experiment.md): instalación comercial, medición y reversión.

## Entender y contribuir

- [Arquitectura](architecture.md): proceso, hilos, estado y persistencia.
- [Pruebas](verification.md): simulación, integración nativa y validación operativa.
- [Contribuciones](../CONTRIBUTING.md): entorno y propuestas de cambios.
- [Seguridad](../SECURITY.md): información privada y reporte de vulnerabilidades.
- [Alcance del producto](../PRODUCT.md) y [sistema de diseño](../DESIGN.md).
- [Licencia MIT](../LICENSE) y [dependencias](../THIRD_PARTY.md).

La guía local se ejecuta en tu Mac; `INSTALL.md` describe el despliegue opcional
en Ubuntu. Las direcciones de ejemplo deben sustituirse. Las rutas
`/opt/pythonblastertts`, `/etc/pythonblastertts` y `/var/lib/pythonblastertts`
son las que crea el instalador, no referencias a un servidor particular.
