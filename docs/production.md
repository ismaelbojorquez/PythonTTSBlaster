# Administración en producción

Para una instalación nueva sigue [INSTALL.md](../INSTALL.md). Esta guía describe
el servicio ya instalado con HTTP en loopback y acceso mediante túnel/proxy o SSH.

## Directorios y cuentas

| Contenido | Ruta o cuenta |
|---|---|
| Copia de trabajo del administrador | `/home/deploy/python-blaster-tts` en los ejemplos |
| Código y entorno virtual del servicio | `/opt/pythonblastertts` |
| Configuración privada | `/etc/pythonblastertts/config.toml` |
| SQLite, audios y reportes | `/var/lib/pythonblastertts` |
| Modelos Piper | `/var/lib/pythonblastertts/voices` |
| Unidad systemd | `/etc/systemd/system/blaster.service` |
| Administración del servidor | `deploy`, con permisos sudo |
| Ejecución de la aplicación | `blaster`, sin inicio de sesión interactivo |

El servicio puede escribir su directorio de datos y el del TOML para guardar
cambios atómicos. El TOML tiene permisos `600`. El código y la `.venv` los administra
root. Los registros van al journal de systemd. No se ejecutan múltiples workers:
SQLite, agenda y motor SIP tienen un único propietario.

## Estado, inicio y parada

```bash
sudo systemctl status blaster --no-pager
sudo systemctl is-enabled blaster
curl --fail http://127.0.0.1:8765/healthz
sudo journalctl -u blaster -f
```

`/healthz` confirma HTTP y SQLite, no disponibilidad de la troncal. El estado SIP
se consulta en el panel. Sustituye 8765 en las comprobaciones si cambias `web_port`.

```bash
sudo systemctl stop blaster
sudo systemctl start blaster
```

Una parada o reinicio termina las llamadas activas. El cierre normal libera el
endpoint y registra las interrupciones. Tras una interrupción, una campaña manual
no se relanza sola; los horarios pendientes siguen el margen de ejecución tardía.

El servicio se reinicia ante fallos, con un límite de cinco arranques en dos
minutos. Después de corregir la causa de fallos repetidos:

```bash
sudo systemctl reset-failed blaster
sudo systemctl start blaster
```

## Comprobar la configuración

Esta comprobación no marca ni registra la troncal:

```bash
sudo -u blaster /opt/pythonblastertts/.venv/bin/python \
  /opt/pythonblastertts/scripts/check_production.py \
  --config /etc/pythonblastertts/config.toml
```

Verifica rutas, permisos, autenticación inicial, modelo, módulos nativos y soporte
Ogg Opus. El servicio la ejecuta antes de arrancar. Los ajustes disponibles en el
panel se guardan en TOML; las ediciones manuales requieren reiniciar el servicio.
Consulta [configuración](configuration.md) antes de cambiar puertos o capacidad.

## Acceso por dominio

Configura `web_public_url` con el origen exacto del navegador, por ejemplo
`https://tts.example.com`. El ejemplo debe sustituirse por un dominio propio.
El origen del túnel/proxy en el mismo servidor es `http://127.0.0.1:8765`.
El proceso sólo acepta cabeceras de proxy desde loopback.

El esquema externo HTTPS activa cookies Secure; no instala HTTPS en la aplicación.
Para acceso sólo por SSH se puede usar `web_public_url = "http://localhost:8765"`
y el reenvío descrito en [instalación](../INSTALL.md). Un error de Host/Origin no
se corrige desactivando autenticación: comprueba que la URL coincida.

## Respaldo consistente

Finaliza las llamadas y detén el servicio antes de respaldar SQLite. Incluye el
TOML, la base, grabaciones y reportes. Este ejemplo crea una copia privada en el
mismo servidor; trasládala a tu almacenamiento de respaldos para protegerte de
la pérdida del servidor:

```bash
sudo systemctl stop blaster
BLASTER_BACKUP="/var/backups/pythonblastertts/$(date -u +%Y%m%dT%H%M%SZ)"
sudo install -d -m 0700 "$BLASTER_BACKUP"
sudo tar -czf "$BLASTER_BACKUP/state.tar.gz" -C / \
  etc/pythonblastertts var/lib/pythonblastertts
sudo chmod 0600 "$BLASTER_BACKUP/state.tar.gz"
sudo tar -tzf "$BLASTER_BACKUP/state.tar.gz" > /dev/null
sudo systemctl start blaster
```

Conserva la ruta del respaldo. La copia contiene secretos y datos operativos;
no debe subirse al repositorio. Una copia de SQLite por sí sola no incluye audio
ni archivos de reportes. No copies sólo el `.sqlite3` mientras hay escrituras.

Para restaurar, detén el servicio, conserva los directorios actuales con otro
nombre y restaura los directorios completos desde una copia confiable. No mezcles
una base restaurada con archivos WAL/SHM de otra ejecución. Asigna los directorios
de configuración/datos a `blaster:blaster` y el TOML a modo `600`; valida antes
de iniciar. Usa código compatible con la versión de la base restaurada.

## Actualizar

Finaliza las llamadas, detén el servicio y toma un respaldo. Después, como
`deploy`, desde tu copia de trabajo:

```bash
cd /home/deploy/python-blaster-tts
git status --short
git pull --ff-only
sudo bash scripts/install_ubuntu.sh
```

Resuelve cambios locales antes del pull. El instalador rechaza actualizaciones
con el servicio activo; conserva TOML y datos, actualiza dependencias/código,
compila PJSUA2 y verifica el arranque. Cambiar el código del checkout sin ejecutar
el instalador no actualiza la copia que usa el servicio.

Para volver a una versión anterior, usa su revisión de código y una copia de
la base compatible. No se garantiza que una base migrada pueda abrirse con una
versión anterior sin restauración.

## Migrar desde otro equipo

Detén ambas instancias. Instala las dependencias en el servidor destino y copia
el contenido del antiguo `data_dir` al directorio de datos de producción, junto
con su TOML privado. Ajusta rutas, dominio y red SIP al nuevo servidor. Conserva
la voz en la carpeta prevista y asigna propietarios/permisos del servicio.
No copies entornos virtuales entre sistemas ni abras el mismo SQLite desde
carpetas sincronizadas o varios procesos.

## Retención y red

La retención de grabaciones y reportes se configura en TOML. Los CDR permanecen
cuando vence un audio. Revisa espacio disponible y alertas desde el panel.

SIP/RTP se conectan directamente al proveedor. Comprueba IP autorizada, rango de
medios y NAT cuando cambies de servidor o troncal. El instalador no administra
firewall, túneles ni autorización de IP del proveedor.

Referencias: [rutas Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/routing/),
[cabeceras de proxy de Uvicorn](https://www.uvicorn.org/settings/#http) y
[servicios systemd](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html).
