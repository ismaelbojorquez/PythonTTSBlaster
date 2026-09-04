# Ejecutar en tu Mac

La aplicación se ejecuta desde la carpeta del repositorio con el Python de
`.venv`. El panel está en [http://localhost:8765](http://localhost:8765). No
necesita un dominio, túnel, servicio de macOS ni instalación global de la app.

## Si ya utilizabas el proyecto en este Mac

Abre Terminal en la carpeta del proyecto y ejecuta:

```bash
.venv/bin/python run.py --config config.toml --check
.venv/bin/python run.py --config config.toml
```

El primer comando valida la configuración sin iniciar telefonía. El segundo
abre el panel y, con `mode = "sip"`, inicia el registro de la troncal.

También puedes abrir `iniciar.command` con doble clic en Finder. El lanzador
cambia a la carpeta del proyecto y utiliza su `.venv`, aunque lo abras desde
otro directorio. Para validar con ese lanzador:

```bash
./iniciar.command --check
```

Mantén la terminal abierta mientras usas el sistema. Para terminar, pulsa
**Ctrl+C** en esa terminal. Las campañas programadas requieren que la aplicación
esté ejecutándose y que el Mac permanezca despierto.

## Configuración local

Edita `config.toml` en la raíz del proyecto. Estos campos van antes de cualquier
sección como `[sip]` o `[auth]`; reemplaza las líneas existentes si ya aparecen:

```toml
mode = "sip"
web_port = 8765
web_public_url = ""
data_dir = "data"
voice_model = "voices/es_MX-claude-high.onnx"
```

`web_public_url` vacío habilita el acceso HTTP local sin cookies que requieran
HTTPS. También puedes entrar por [127.0.0.1:8765](http://127.0.0.1:8765).

La troncal conserva su servidor en `[sip].domain` y `[sip].registrar`: esos
valores son el destino de telefonía, independientes de la dirección del panel.
Todas las contraseñas siguen en el TOML. Aplica permisos privados:

```bash
chmod 600 config.toml
```

Conserva `auth.enabled = true` para los usuarios, roles y auditoría. Si ya
existen usuarios en la base local, utiliza sus credenciales. En una base nueva,
el administrador inicial se crea desde `[auth]` si hay credenciales de bootstrap;
si no las hay, el primer acceso permite crearlo.

Las rutas `data` y `voices` se resuelven junto al TOML. La base local es
`data/blaster.sqlite3`. Los datos guardados en otro servidor no se descargan
automáticamente a esta carpeta.

## Preparar una copia nueva

Si este mismo Mac ya tiene su `.venv` y modelos, utiliza directamente el arranque
anterior. Para una copia nueva, con Python 3.12 o 3.13 disponible:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -c constraints.txt '.[voice]' setuptools wheel
if [ ! -f config.toml ]; then
  cp config.example.toml config.toml
fi
chmod 600 config.toml
```

Si utilizas Python 3.12, sustituye `python3.13` en el primer comando. Las
dependencias se instalan dentro de `.venv`. La copia nueva empieza en simulación;
configura tu troncal y cambia a `mode = "sip"` cuando esté lista.

La telefonía requiere PJSUA2 compilado para el Python de este Mac. Con las
herramientas de compilación descritas en [CONTRIBUTING.md](../CONTRIBUTING.md),
prepara el módulo y descarga la voz:

```bash
.venv/bin/python scripts/build_pjsua2.py
.venv/bin/python -m piper.download_voices es_MX-claude-high --download-dir voices
```

Una `.venv` de Ubuntu no se puede reutilizar en macOS. El lanzador no instala
dependencias ni descarga modelos cada vez que arranca.

## Si no abre

- **Ya hay una instancia usando este directorio de datos:** utiliza el panel
  existente o detén su proceso desde la terminal donde lo abriste.
- **Puerto 8765 ocupado:** revisa `lsof -nP -iTCP:8765 -sTCP:LISTEN` para identificar
  el proceso antes de detenerlo; también puedes cambiar `web_port` en el TOML.
- **Falta un módulo:** ejecuta con `.venv/bin/python`; para una copia nueva,
  completa la preparación anterior.
- **Archivo pendiente de descargar en iCloud:** conserva descargada la carpeta
  del proyecto, incluidos `.venv`, `voices` y `data`.
- **Troncal sin registrar:** el acceso al panel y la conexión SIP se comprueban
  por separado. Consulta la [guía de diagnóstico](troubleshooting.md).
