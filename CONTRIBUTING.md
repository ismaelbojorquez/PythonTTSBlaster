# Contribuir

Las contribuciones pueden mejorar el motor, las pruebas, la interfaz o la
documentación. Describe el problema, el resultado esperado y cómo comprobar el
cambio. Utiliza datos ficticios en ejemplos, pruebas e incidencias.

## Preparar desarrollo

Trabaja en un fork o copia del repositorio con Python 3.12. Linux y macOS están
soportados para desarrollo; la instalación permanente en Ubuntu tiene su propia
[guía](INSTALL.md).

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -c constraints.txt '.[dev]'
if [ ! -f config.toml ]; then
  cp config.example.toml config.toml
fi
chmod 600 config.toml
.venv/bin/python run.py --config config.toml
```

Conserva `mode = "simulation"` para trabajar sin una troncal. El primer acceso
local permite crear el administrador. La simulación no necesita PJSUA2 ni voz.
Para un checkout con configuración existente, conserva su TOML o utiliza un
archivo privado distinto y pásalo con `--config`.

## Voz y telefonía nativa opcionales

En Ubuntu necesitas compilador C/C++, make, pkg-config, SWIG y cabeceras de la
misma versión de Python del entorno:

```bash
sudo apt install -y build-essential pkg-config swig python3.12-dev python3.12-venv libsndfile1 libopus-dev
```

En macOS instala las Command Line Tools de Xcode (`xcode-select --install`) y
SWIG con tu gestor de paquetes. PJSUA2 se compila sin dispositivos de sonido.
Con las herramientas disponibles:

```bash
.venv/bin/python -m pip install -c constraints.txt '.[voice]' setuptools wheel
.venv/bin/python scripts/build_pjsua2.py
.venv/bin/python -m piper.download_voices es_MX-claude-high --download-dir voices
```

El script compila PJSIP en `build/` e instala el módulo en `.venv`. No necesita
sudo ni un servidor Asterisk. Para sólo escuchar la vista previa, basta instalar
`.[voice]` y descargar el modelo; se puede omitir la compilación de PJSUA2.

## Comprobar cambios

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests scripts run.py
node --test tests/phone-input.test.mjs tests/management-format.test.mjs
```

Node.js sólo se usa para esas pruebas JavaScript, no para ejecutar la plataforma.
El [documento de verificación](docs/verification.md) describe las pruebas SIP
nativas, sus requisitos y lo que no cubre la simulación.

## Proponer una contribución

1. Crea una rama en tu copia y realiza un cambio acotado.
2. Incluye una prueba cuando cambies comportamiento del motor, permisos o persistencia.
3. Actualiza los ejemplos y documentación si cambian opciones o instrucciones.
4. Revisa `git diff` y `git status` para excluir datos privados y archivos generados.
5. Abre una pull request con el problema, el comportamiento resultante y las
   comprobaciones realizadas. Indica las pruebas omitidas y el motivo.

No uses una troncal real en pruebas automatizadas ni publiques capturas con datos
de clientes. No agregues `config.toml`, bases SQLite, reportes, audios reales,
modelos descargados ni claves al repositorio. Los ejemplos de dominio deben usar
`example.com` o `.example`. Consulta [SECURITY.md](SECURITY.md) para vulnerabilidades.

## Convenciones del proyecto

- Configuración y secretos operativos en TOML; no añadir dependencia de `.env`.
- Un proceso propietario del motor y SQLite; callbacks SIP breves y sin informes.
- Conservar causas y mediciones desconocidas como desconocidas.
- No reintentar una llamada cuyo estado siga activo o incierto sin resolver su cierre.
- Reutilizar [arquitectura](docs/architecture.md) y [sistema de diseño](DESIGN.md).
- Preservar los avisos de [licencias de dependencias](THIRD_PARTY.md).
