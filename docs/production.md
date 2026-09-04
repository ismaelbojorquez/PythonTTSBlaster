# Ejecución en producción: Ubuntu y cloudflared

El despliegue sirve el panel por **HTTP en `127.0.0.1:8765`**, con un único proceso
Python administrado por `systemd`. El túnel existente publica
`tts.icc-soluciones.com`. El instalador no instala ni modifica cloudflared, Nginx,
certificados o HTTPS en el servidor.

## Instalar y arrancar

El instalador utiliza Ubuntu con systemd y **Python 3.12 o 3.13**. Ubuntu 24.04
incluye Python 3.12; en otras versiones verifica `python3 --version`. Se reutiliza
el entorno del servidor si ya existe; de lo contrario se selecciona entre
`python3.12`, `python3.13` y `python3`. No se añade un repositorio
de paquetes externo ni se cambia la versión de Python del sistema.

1. Lleva el código actualizado al servidor, mediante Git o una copia del proyecto.
2. Copia también **`config.production.toml` por SSH/SFTP**. Es privado y está
   excluido de Git: contiene la troncal y la contraseña inicial del administrador.
   No copies la `.venv` del Mac; se genera otra para Linux.
3. Desde la carpeta del código en Ubuntu, ejecuta:

```bash
sudo bash scripts/install_ubuntu.sh --config ./config.production.toml
```

El instalador instala los paquetes de compilación, prepara el entorno virtual,
instala las dependencias Python con `constraints.txt`, compila PJSUA2 2.17 y
descarga la voz configurada mediante Piper. Después verifica los requisitos,
habilita `blaster.service`, lo inicia y espera la respuesta de `/healthz`.
La primera instalación y la compilación requieren conexión a Internet.

Las rutas del despliegue son:

| Contenido | Ruta en Ubuntu |
|---|---|
| Código y entorno virtual | `/opt/pythonblastertts` |
| Configuración privada | `/etc/pythonblastertts/config.toml` |
| SQLite, audio, grabaciones y reportes | `/var/lib/pythonblastertts` |
| Modelos de voz | `/var/lib/pythonblastertts/voices` |
| Servicio | `/etc/systemd/system/blaster.service` |

El proceso usa la cuenta de sistema `blaster`. Puede escribir sus datos y el
directorio del TOML; este último permiso permite guardar cambios atómicos desde
Configuración. El TOML usa permisos `600`. El servicio no puede modificar el
código instalado y escribe sus registros en el journal de systemd.

Si todavía no tienes la configuración privada, prepara la instalación sin
iniciar llamadas ni el servicio:

```bash
sudo bash scripts/install_ubuntu.sh --prepare-only
sudo nano /etc/pythonblastertts/config.toml
sudo bash scripts/install_ubuntu.sh
```

La plantilla es `deploy/config.example.toml`. El instalador genera una contraseña
inicial aleatoria y la guarda únicamente en el TOML. Completa la troncal antes
de ejecutar el último comando. Si el TOML de destino ya existe, **se conserva**;
un nuevo `--config` no sobrescribe sus credenciales ni sus ajustes.

## Dominio y acceso inicial

La ruta del túnel existente debe tener estos valores:

| Campo | Valor |
|---|---|
| Nombre público | `tts.icc-soluciones.com` |
| Servicio de origen | `http://127.0.0.1:8765` |

No se requiere cambiar el servicio cloudflared. La aplicación acepta tanto el
Host público como un Host local si el túnel lo reescribe. Si el túnel apunta a
otro puerto, hazlo coincidir con `web_port` en el TOML.

```toml
web_port = 8765
web_public_url = "https://tts.icc-soluciones.com"
```

`web_public_url` identifica la URL externa que ya publica el túnel y permite
validar Host/Origin y marcar las cookies de sesión. **No crea un servidor HTTPS**
ni instala certificados. Si tu URL externa realmente usa HTTP, utiliza ese
esquema en el campo. Las cabeceras de proxy sólo se aceptan desde loopback.

Abre la URL pública e inicia sesión con los valores de
`auth.bootstrap_username` y `auth.bootstrap_password` del TOML. El primer
administrador se crea antes de aceptar tráfico web. Una base con usuarios conserva
sus cuentas y contraseñas; cambiar estos campos no restablece una cuenta existente.
El acceso público exige autenticación. El resto de usuarios se administra en
**Operación → Usuarios**.

## Comprobar y administrar

```bash
sudo systemctl status blaster --no-pager
sudo systemctl is-enabled blaster
curl --fail http://127.0.0.1:8765/healthz
sudo journalctl -u blaster -f
```

`/healthz` confirma que el proceso HTTP y SQLite responden. No prueba el registro
SIP ni garantiza que la troncal pueda establecer una llamada. El estado de la
troncal aparece dentro del panel autenticado.

```bash
# Comprobar archivos, permisos, módulos nativos y soporte Ogg Opus, sin llamadas.
sudo -u blaster /opt/pythonblastertts/.venv/bin/python \
  /opt/pythonblastertts/scripts/check_production.py \
  --config /etc/pythonblastertts/config.toml

# Detener o iniciar manualmente.
sudo systemctl stop blaster
sudo systemctl start blaster
```

El servicio arranca con Ubuntu y se reinicia tras un fallo. Después de cinco
fallos en dos minutos se detiene para permitir corregir la causa:

```bash
sudo journalctl -u blaster -n 100 --no-pager
sudo systemctl reset-failed blaster
sudo systemctl start blaster
```

Una parada o reinicio termina las llamadas activas. El cierre normal marca las
sesiones interrumpidas y libera el endpoint SIP y la base. Un cierre abrupto se
recupera al arrancar; las campañas manuales no se relanzan automáticamente.
Las programaciones pendientes siguen las reglas de ejecución tardía del TOML.
No agregues workers, `--reload`, Gunicorn u otra instancia: el motor SIP y SQLite
tienen un único propietario.

## Telefonía y persistencia

cloudflared transporta el panel web. **SIP y RTP se conectan directamente con la
troncal** usando la red del servidor. Conserva los límites de canales, CPS y
puertos definidos en el TOML; revisa que los puertos SIP y el rango UDP RTP de
cada troncal sean accesibles según tu proveedor. Si hay NAT estático, el campo
`public_address` debe corresponder al servidor. El instalador no modifica el
firewall ni la lista de IP autorizadas del proveedor.

La instalación no copia automáticamente la base del Mac. Para migrar su historial,
detén ambas instancias, copia el contenido del antiguo `data_dir` a
`/var/lib/pythonblastertts` y asigna sus archivos a `blaster:blaster` antes de
arrancar. Conserva también el modelo de voz en la ruta del servidor. No abras
simultáneamente el mismo SQLite desde dos procesos o una carpeta sincronizada.

Para un respaldo consistente de la instalación, detén el servicio, copia
`/var/lib/pythonblastertts` y `/etc/pythonblastertts` a tu destino de respaldos y
vuelve a iniciarlo. La copia del TOML contiene secretos; mantenla privada.
Los límites de retención y espacio de grabaciones y reportes siguen en el TOML.

## Actualizar

Finaliza las llamadas, detén `blaster`, respalda los datos y actualiza el código
en tu checkout. Ejecuta de nuevo `sudo bash scripts/install_ubuntu.sh`. El
instalador rechaza una actualización con el servicio activo, conserva el TOML
existente y la base, actualiza el código y verifica el arranque. Para volver a
una versión anterior, utiliza su código y un respaldo compatible de su base.

## Verificación del despliegue

En desarrollo se verifican la preparación del TOML privado, la validación de
permisos y rutas, el inicio de sesión con Host público o reescrito, el rechazo de
orígenes ajenos, el administrador inicial, la preservación de usuarios y el cierre
de un proceso Uvicorn real mediante SIGTERM. Estas pruebas usan SQLite temporal y
telefonía simulada. La unidad systemd se valida con `systemd-analyze verify` al
instalarla en Ubuntu; la compilación y la conexión SIP reales se comprueban en ese
servidor. No se ha realizado una instalación remota desde el entorno del Mac.

Resultado de la verificación del 3 de septiembre de 2026: **95 pruebas Python
aprobadas, 7 nativas omitidas y 6 pruebas JavaScript aprobadas**. La resolución
de las dependencias fijadas en `constraints.txt` también se comprobó para Linux
x86_64 con CPython 3.12: 26 paquetes compatibles. Esto verifica la disponibilidad
de los paquetes, sin sustituir la compilación y la prueba de telefonía en Ubuntu.

Referencias: [rutas HTTP de Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/routing/),
[Host del origen](https://developers.cloudflare.com/tunnel/advanced/origin-parameters/#httphostheader),
[cabeceras de proxy de Uvicorn](https://www.uvicorn.org/settings/#http),
[servicios systemd](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html).
