# Despliegue desde cero en Ubuntu con Cloudflare Tunnel

Esta guía parte de un servidor Ubuntu limpio y termina con Python Blaster TTS
ejecutándose al iniciar el sistema. El panel escucha únicamente en
`127.0.0.1:8765`; Cloudflare Tunnel publica el dominio sin abrir el puerto web
en Internet. SIP y RTP continúan conectándose directamente con la troncal.

La instalación crea dos cuentas Linux:

| Cuenta | Propósito |
|---|---|
| `deploy` | Acceso por SSH, actualización del repositorio y administración con `sudo` |
| `blaster` | Cuenta sin acceso interactivo que ejecuta la aplicación |

La cuenta administradora del panel es independiente de ambas. Sus datos se
definen en `/etc/pythonblastertts/config.toml`.

## 1. Información necesaria

Prepara estos datos antes de comenzar:

- Dirección IPv4 del servidor.
- Dominio activo en una cuenta de Cloudflare, por ejemplo `example.com`.
- Subdominio para el panel, por ejemplo `app.example.com`.
- Dominio, usuario, contraseña, transporte y puerto de la troncal SIP.
- Direcciones IP y puertos autorizados por el proveedor SIP.
- Clave pública SSH de la computadora administradora.

Los nombres `app.example.com`, `sip.proveedor.example`, `IP_DEL_SERVIDOR`,
`IP_DEL_PROVEEDOR` y las contraseñas de muestra deben sustituirse. No escribas
los signos `<` y `>` alrededor de un valor en la terminal.

Requisitos admitidos:

- Ubuntu Server 24.04 LTS recomendado.
- Ubuntu Server 22.04 LTS con Python 3.12 de Deadsnakes.
- Python 3.12 o 3.13. Python 3.10 y 3.14 no son compatibles con este despliegue.
- Una dirección IP con conectividad SIP/RTP directa o un NAT estático configurado.
- Salida a Internet durante la instalación.

No copies `.venv`, bases, modelos ni cachés desde macOS. El servidor compila e
instala sus propios componentes.

## 2. Entrar al servidor y crear `deploy`

Desde tu computadora, inicia sesión con la cuenta entregada por el proveedor:

```bash
ssh root@IP_DEL_SERVIDOR
```

Si el proveedor entrega otro usuario con `sudo`, úsalo en lugar de `root` y
antepone `sudo` a los comandos administrativos.

Actualiza el sistema e instala las herramientas iniciales:

```bash
apt update
apt upgrade -y
apt install -y sudo git curl ca-certificates nano gnupg software-properties-common ufw
```

Si la actualización instala un kernel nuevo, reinicia y vuelve a entrar antes
de continuar:

```bash
reboot
```

Crea el usuario de administración:

```bash
adduser deploy
usermod -aG sudo deploy
```

`adduser` solicita la contraseña Linux y algunos datos opcionales. La contraseña
se utilizará al ejecutar `sudo`.

### Autorizar una clave SSH

Si la cuenta inicial ya utiliza la clave que quieres conservar, cópiala:

```bash
install -d -o deploy -g deploy -m 0700 /home/deploy/.ssh
cp /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 0600 /home/deploy/.ssh/authorized_keys
```

Si no existe `/root/.ssh/authorized_keys`, crea el archivo y pega **una clave
pública**, como el contenido de `id_ed25519.pub`:

```bash
install -d -o deploy -g deploy -m 0700 /home/deploy/.ssh
nano /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 0600 /home/deploy/.ssh/authorized_keys
```

La clave privada permanece en tu computadora. Antes de cerrar la sesión inicial,
abre otra terminal y comprueba el nuevo acceso:

```bash
ssh deploy@IP_DEL_SERVIDOR
```

Ya dentro como `deploy`:

```bash
whoami
sudo -v
cat /etc/os-release
```

`whoami` debe responder `deploy`. Consulta la documentación de
[usuarios](https://ubuntu.com/server/docs/security-users/) y
[OpenSSH](https://ubuntu.com/server/docs/how-to/security/openssh-server/) de
Ubuntu si el servidor aplica una política SSH adicional.

## 3. Instalar Python

Ejecuta solamente el bloque correspondiente a tu versión de Ubuntu. No cambies
el enlace `/usr/bin/python3` del sistema.

### Ubuntu 24.04 LTS

```bash
sudo add-apt-repository -y universe
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev
```

### Ubuntu 22.04 LTS

Ubuntu 22.04 incluye Python 3.10. Esta instalación utiliza el PPA comunitario
[Deadsnakes](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa?field.series_filter=jammy).
Si la política del servidor sólo permite paquetes oficiales de Ubuntu, instala
Ubuntu 24.04.

```bash
sudo add-apt-repository -y universe
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev
```

Comprueba la instalación:

```bash
python3.12 --version
python3.12 -m venv --help >/dev/null
```

## 4. Clonar el repositorio público

Clona como `deploy`, sin `sudo`:

```bash
cd /home/deploy
git clone https://github.com/ismaelbojorquez/PythonTTSBlaster.git python-blaster-tts
cd /home/deploy/python-blaster-tts
git status --short
```

`git status --short` debe quedar vacío. Si utilizas un fork, sustituye solamente
la URL del repositorio.

## 5. Preparar la aplicación

Ejecuta el instalador en modo preparación:

```bash
sudo bash scripts/install_ubuntu.sh --prepare-only
```

Este paso realiza lo siguiente:

1. Instala compiladores y bibliotecas de audio.
2. Crea la cuenta de servicio `blaster`.
3. Copia el código a `/opt/pythonblastertts`.
4. Crea `/opt/pythonblastertts/.venv`.
5. Instala las dependencias Python.
6. Compila PJSUA2 2.17 para el Python del servidor.
7. Descarga la voz Piper configurada.
8. Crea el TOML privado si todavía no existe.
9. Instala la unidad `blaster.service` sin iniciarla.

La primera compilación puede tardar varios minutos. El instalador nunca
reemplaza un `/etc/pythonblastertts/config.toml` existente.

Las rutas finales son:

| Contenido | Ruta |
|---|---|
| Código y entorno | `/opt/pythonblastertts` |
| Configuración privada | `/etc/pythonblastertts/config.toml` |
| Base, grabaciones y reportes | `/var/lib/pythonblastertts` |
| Modelo Piper | `/var/lib/pythonblastertts/voices` |
| Servicio | `/etc/systemd/system/blaster.service` |

## 6. Configurar el sistema

Abre el TOML como la cuenta que lo administra:

```bash
sudo -u blaster nano /etc/pythonblastertts/config.toml
```

Edita las claves que ya existen. No dupliques secciones. Todos los secretos se
guardan en este TOML; no se necesita un archivo `.env`.

### Valores generales

Antes de la primera sección `[ ... ]`, configura:

```toml
mode = "sip"
web_port = 8765
web_public_url = "https://app.example.com"
data_dir = "/var/lib/pythonblastertts"
reporting_timezone = "America/Mexico_City"
concurrency = 20
trunk_channels = 40
calls_per_second = 1.0
tts_workers = 2
tts_engine = "piper"
voice_model = "/var/lib/pythonblastertts/voices/es_MX-claude-high.onnx"
```

Sustituye `app.example.com` por el hostname que publicarás en Cloudflare. La
capacidad debe respetar los canales y CPS contratados. Cada sesión reserva dos
canales para poder transferir con un agente; `20` sesiones requieren `40` canales.

### Troncal SIP

Para una troncal con registro y contraseña:

```toml
[sip]
domain = "sip.proveedor.example"
username = "USUARIO_SIP"
password = 'CONTRASEÑA_SIP'
auth_username = ""
caller_id = ""
registrar = "sip:sip.proveedor.example:5060"
proxy = ""
registration_enabled = true
dial_format = "as_entered"
transport = "udp"
bind_address = "0.0.0.0"
local_port = 5060
public_address = ""
rtp_port = 10000
rtp_port_range = 200
```

Usa comillas simples para una contraseña literal que contenga caracteres
especiales. No copies una línea `register =>` de Asterisk: separa sus valores en
`username`, `password`, `registrar` y, cuando aplique, `auth_username`.

Para autenticación por IP utiliza `registration_enabled = false` y conserva la
identidad exigida por el proveedor. Configura `public_address` cuando el servidor
esté detrás de NAT estático y el proveedor requiera esa dirección en SIP/SDP.
Consulta [Configuración](docs/configuration.md) para varias troncales, puertos y
formatos de marcación.

### Administrador inicial

Configura una cuenta temporal para el primer acceso web:

```toml
[auth]
enabled = true
session_hours = 8
bootstrap_username = "administrador"
bootstrap_password = 'CAMBIA_ESTA_CONTRASEÑA_DE_12_O_MAS'
bootstrap_display_name = "Administrador"
```

La contraseña debe tener al menos 12 caracteres. Estos campos crean el primer
administrador sólo cuando la base todavía no contiene usuarios.

Guarda en nano con **Ctrl+O**, Enter y sal con **Ctrl+X**. Restaura permisos y
comprueba que el TOML pueda leerse y actualizarse:

```bash
sudo chown blaster:blaster /etc/pythonblastertts
sudo chown blaster:blaster /etc/pythonblastertts/config.toml
sudo chmod 0750 /etc/pythonblastertts
sudo chmod 0600 /etc/pythonblastertts/config.toml
sudo -u blaster test -r /etc/pythonblastertts/config.toml
sudo -u blaster test -w /etc/pythonblastertts/config.toml
```

No ejecutes `cat` sobre el TOML en una sesión grabada o al solicitar soporte.

## 7. Configurar el firewall

Cloudflare Tunnel utiliza conexiones salientes; el panel `8765` no necesita una
regla de entrada. Conserva SSH antes de habilitar UFW:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
```

Autoriza SIP y RTP únicamente desde las direcciones entregadas por tu proveedor.
Este ejemplo corresponde a UDP 5060 y UDP 10000–10200:

```bash
sudo ufw allow from IP_DEL_PROVEEDOR to any port 5060 proto udp
sudo ufw allow from IP_DEL_PROVEEDOR to any port 10000:10200 proto udp
```

Repite las reglas para cada red autorizada. Si la troncal usa TCP, cambia la regla
SIP a `proto tcp`. No habilites el firewall hasta confirmar que `OpenSSH` aparece:

```bash
sudo ufw show added
sudo ufw enable
sudo ufw status verbose
```

Si la red limita tráfico **saliente**, Cloudflare requiere TCP y UDP 7844. La
política predeterminada `allow outgoing` ya los permite. Consulta la
[matriz oficial de firewall de Cloudflare](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/).

## 8. Validar antes de iniciar

Comprueba la instalación sin abrir el panel ni realizar llamadas:

```bash
sudo -u blaster /opt/pythonblastertts/.venv/bin/python -B \
  /opt/pythonblastertts/scripts/check_production.py \
  --config /etc/pythonblastertts/config.toml
```

El resultado esperado es:

```text
Requisitos de producción válidos. Sin llamadas.
```

Para probar un registro SIP real sin marcar, mantén el servicio detenido:

```bash
sudo -u blaster /opt/pythonblastertts/.venv/bin/python -B \
  /opt/pythonblastertts/scripts/check_sip.py \
  --config /etc/pythonblastertts/config.toml --trunk default
```

Una secuencia `401` seguida de `200` representa el desafío de autenticación y el
registro aceptado. Consulta [Solución de problemas](docs/troubleshooting.md) para
408, 403 y otros resultados.

## 9. Iniciar Blaster

Desde el checkout de `deploy`, ejecuta el instalador completo:

```bash
cd /home/deploy/python-blaster-tts
sudo bash scripts/install_ubuntu.sh
```

Comprueba el servicio y el origen local:

```bash
sudo systemctl status blaster --no-pager
sudo systemctl is-enabled blaster
curl --fail http://127.0.0.1:8765/healthz
```

La respuesta debe ser `{"status":"ok"}`. Para consultar el registro:

```bash
sudo journalctl -u blaster -n 100 --no-pager
```

No ejecutes `run.py` manualmente mientras `blaster.service` esté activo; ambos
procesos intentarían usar la misma base y los mismos puertos SIP.

## 10. Crear el túnel en Cloudflare

Este procedimiento utiliza un túnel administrado desde el panel de Cloudflare.
Cloudflare recomienda ejecutar `cloudflared` como servicio para que arranque con
el sistema. El dominio debe estar activo en la cuenta antes de crear la ruta.

En el panel de Cloudflare:

1. Abre **Networking → Tunnels**.
2. Selecciona **Create Tunnel**.
3. Asigna un nombre, por ejemplo `blaster-production`.
4. Elige Linux como entorno del conector.
5. Conserva abierta la pantalla que muestra el token de instalación.
6. En **Routes**, agrega una **Published application**.
7. Selecciona el subdominio y dominio, por ejemplo `app.example.com`.
8. Configura el servicio como **HTTP** con URL `http://127.0.0.1:8765`.
9. Guarda la ruta.

La ruta creada desde el panel genera el registro DNS del túnel. El HTTPS público
termina en Cloudflare y la conexión local continúa por HTTP en loopback. No
configures `https://127.0.0.1:8765`: Blaster no sirve TLS local.

Referencia: [configuración oficial de Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/setup/)
y [rutas de aplicaciones publicadas](https://developers.cloudflare.com/tunnel/routing/).

## 11. Instalar `cloudflared`

En el servidor, agrega el repositorio firmado de Cloudflare:

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update
sudo apt install -y cloudflared
cloudflared --version
```

Estos son los comandos publicados por Cloudflare para Debian y Ubuntu. Consulta
su [repositorio oficial de paquetes](https://pkg.cloudflare.com/index.html).

El token del túnel permite ejecutar el conector y debe tratarse como una
contraseña. Para evitar guardarlo en el historial, cópialo desde la pantalla del
túnel y usa una lectura silenciosa:

```bash
read -rsp 'Pega el token del túnel y presiona Enter: ' CLOUDFLARE_TUNNEL_TOKEN
echo
sudo cloudflared service install "$CLOUDFLARE_TUNNEL_TOKEN"
unset CLOUDFLARE_TUNNEL_TOKEN
```

No escribas `TOKEN_DEL_TUNEL` literalmente. `service install` crea y habilita
`cloudflared.service`.

Comprueba el conector:

```bash
sudo systemctl status cloudflared --no-pager
sudo systemctl is-enabled cloudflared
sudo journalctl -u cloudflared -n 100 --no-pager
```

El túnel debe aparecer como **Healthy** en Cloudflare. La documentación oficial
explica la [instalación mediante token](https://developers.cloudflare.com/tunnel/setup/)
y la [rotación del token](https://developers.cloudflare.com/tunnel/advanced/tunnel-tokens/).

## 12. Verificación final

Comprueba ambos servicios:

```bash
sudo systemctl is-active blaster cloudflared
sudo systemctl is-enabled blaster cloudflared
curl --fail http://127.0.0.1:8765/healthz
curl --fail https://app.example.com/healthz
```

Sustituye `app.example.com`. Después abre esa URL en un navegador e inicia sesión
con el administrador configurado. Revisa en el panel:

1. Estado de la troncal.
2. Voz y tiempo de generación.
3. Pool de teléfonos de transferencia.
4. Límites de sesiones, canales y CPS.
5. Zona horaria y automatización.

Realiza una llamada controlada y autorizada. Comprueba el mensaje, DTMF 1,
transferencia con DTMF 2, audio bidireccional, grabación y CDR.

Finalmente reinicia el servidor para verificar el arranque automático:

```bash
sudo reboot
```

Después de reconectar:

```bash
sudo systemctl is-active blaster cloudflared
curl --fail https://app.example.com/healthz
```

Las campañas programadas se ejecutan por el servicio aunque el navegador y la
sesión SSH estén cerrados.

## 13. Activar Kokoro en el servidor (opcional)

La instalación base utiliza Piper porque consume menos recursos y permite validar
primero telefonía y red. Para instalar Kokoro de forma aislada:

```bash
sudo systemctl stop blaster
sudo env PYTHON_BIN=/usr/bin/python3.12 bash \
  /opt/pythonblastertts/scripts/install_kokoro_experiment.sh
```

Edita el TOML:

```bash
sudo -u blaster nano /etc/pythonblastertts/config.toml
```

Configura:

```toml
tts_engine = "kokoro"

[kokoro]
enabled = true
python = "/opt/pythonblastertts/.venv-kokoro/bin/python"
model = "/opt/pythonblastertts/.cache/kokoro/models/kokoro-v1.0.onnx"
voices = "/opt/pythonblastertts/.cache/kokoro/models/voices-v1.0.bin"
voice = "ef_dora"
language = "es"
speed = 1.0
startup_timeout = 90.0
```

Valida y vuelve a iniciar:

```bash
sudo -u blaster /opt/pythonblastertts/.venv/bin/python -B \
  /opt/pythonblastertts/scripts/check_production.py \
  --config /etc/pythonblastertts/config.toml
sudo systemctl start blaster
sudo journalctl -u blaster -n 100 --no-pager
```

Mide las voces desde **Operación → Voces** antes de una campaña. Consulta la
[evaluación de Kokoro](docs/kokoro-experiment.md) para consumo y reversión.

## 14. Operación posterior

Continúa con estas guías:

- [Cloudflare Tunnel](docs/cloudflare-tunnel.md): servicio, actualización, token y diagnóstico.
- [Administración en producción](docs/production.md): respaldos, actualización y restauración.
- [Configuración](docs/configuration.md): troncales, capacidad, puertos y grabaciones.
- [Uso del panel](docs/usage.md): campañas, programación, CDR y reportes.
- [Solución de problemas](docs/troubleshooting.md): fallos de arranque, web, SIP y audio.
- [Seguridad](SECURITY.md): secretos, datos y exposición pública.
