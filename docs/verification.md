# Pruebas y verificación

Las pruebas separan comportamiento de aplicación, integración nativa por
localhost y validación operativa con una troncal. Ninguna prueba sintética
certifica precisión AMD, rendimiento de un servidor o compatibilidad universal.

## Preparar el entorno

Sigue [CONTRIBUTING.md](../CONTRIBUTING.md). Ejecuta desde el repositorio:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests scripts run.py
node --test tests/phone-input.test.mjs tests/management-format.test.mjs
```

Las pruebas Python usan bases temporales y simulación salvo las nativas optativas.
Node.js sólo es necesario para las pruebas del código de formato del navegador.
Un resultado `skipped` significa cobertura omitida, no una prueba aprobada.

## Cobertura de aplicación

- Validación de TOML, CSV, números y variables de plantillas.
- Concurrencia, límites, repetición DTMF y flujo de enlace al agente.
- Persistencia de sesiones, tramos, eventos, CDR y reportes.
- Reglas AMD con voz/tonos sintéticos, silencio y muestras incompletas.
- Rutas de troncales, agenda, alertas y gestión de grabaciones.
- Sesiones web, roles, auditoría y exclusión de secretos en respuestas.
- Vista previa TTS, invalidación y limpieza de muestras temporales.
- Preparación del TOML de producción, permisos y preservación de configuraciones.
- Host/Origin, cookies y bootstrap con un dominio ficticio.
- Arranque de Uvicorn en simulación y cierre real por SIGTERM.

Para cambios de instalación o dominio se puede ejecutar el grupo acotado:

```bash
.venv/bin/python -m pytest tests/test_production.py tests/test_config.py -q
bash -n scripts/install_ubuntu.sh
```

## Integración SIP nativa

Requiere PJSUA2 compilado. La prueba con TTS real también necesita Piper y
`voices/es_MX-claude-high.onnx` con su JSON. Los extremos usan UDP por localhost,
sin leer credenciales de una troncal ni marcar números externos:

```bash
BLASTER_NATIVE_TEST=1 .venv/bin/python -m pytest tests/test_native_sip.py -q
```

Se comprueban reproducción, fin de audio, espera en bucle, DTMF, enlace de dos
llamadas, audio bidireccional y cierre. Los escenarios AMD verifican el detector
integrado con PCM recibido. Las latencias de localhost no representan las del
proveedor o la red móvil.

## Validación de documentación

Antes de una contribución, comprueba los enlaces relativos desde cada documento,
los fragmentos TOML y la sintaxis de los bloques shell. Las URLs de ejemplo deben
usar dominios reservados, y los ejemplos no deben incorporar datos de una
instalación. Mantén los comandos alineados con los scripts reales.

## Verificación en Ubuntu

El instalador ejecuta `systemd-analyze verify`, comprueba dependencias y espera
`/healthz`. Estos pasos se realizan en Ubuntu, no se validan ejecutando systemd en
macOS. El endpoint confirma disponibilidad del panel y SQLite, no telefonía.

En una instalación propia, con contactos de prueba autorizados, verifica:

1. Registro SIP o ruta autenticada por IP.
2. Audio en ambas direcciones y volumen de la voz.
3. Opciones 1/2, llamada al agente y cierre desde ambos extremos.
4. Resultado AMD frente a saludos humanos y buzones conocidos.
5. CDR, grabación, exportaciones y permisos de cada rol.
6. Límites de canales/CPS y comportamiento al perder la troncal.
7. Reinicio, recuperación de pendientes y restauración de un respaldo.

El dimensionamiento requiere medir carga sostenida y uso de CPU, memoria,
disco y red con la configuración final. No se atribuye una tasa de acierto AMD
ni un ahorro económico a los resultados de pruebas sintéticas.
