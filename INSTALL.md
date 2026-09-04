# Instalación desde cero en Ubuntu

Para ejecutar desde la carpeta del proyecto en macOS, utiliza la
[guía local](docs/local.md). Este despliegue en servidor es opcional.

Esta guía lleva un servidor Ubuntu hasta una instalación ejecutándose con
systemd. El panel sirve **HTTP en `127.0.0.1:8765`**. El acceso público utiliza
un túnel o proxy administrado por el operador. El instalador no instala HTTPS,
certificados, Nginx ni cloudflared.

## 1. Requisitos y valores de ejemplo

- Ubuntu Server 24.04 LTS, o 22.04 LTS siguiendo su apartado de Python.
- Acceso inicial por SSH o consola con una cuenta que tenga `sudo`.
- Internet durante la instalación para APT, Python, PJSIP y el modelo de voz.
- Una troncal SIP y sus datos de autenticación o autorización por IP.
- Un dominio y un túnel/proxy existente si habrá acceso público.

Sustituye `IP_DEL_SERVIDOR`, `USUARIO_INICIAL`, `TU_USUARIO` y `TU_REPOSITORIO`
en los comandos. `tts.example.com` es un dominio de documentación: reemplázalo
por tu nombre público. No copies la `.venv` de otro equipo.

El usuario Linux `deploy` administra el código. El instalador crea `blaster`
para ejecutar el servicio. El administrador del panel es otra cuenta,
independiente de las cuentas Linux.

## 2. Crear el usuario deploy

Desde tu computadora, conecta con la cuenta inicial del servidor:

```bash
ssh USUARIO_INICIAL@IP_DEL_SERVIDOR
```

En el servidor:

```bash
sudo apt update
sudo apt install -y sudo git curl ca-certificates nano software-properties-common gnupg
sudo adduser deploy
sudo usermod -aG sudo deploy
```

`adduser` solicita la contraseña Linux de `deploy`; se usa también para `sudo`.
Si la cuenta ya existe, omite `adduser`. Estos pasos siguen la
[administración de usuarios de Ubuntu](https://ubuntu.com/server/docs/security-users/).

Si el servidor permite SSH con contraseña, prueba `ssh deploy@IP_DEL_SERVIDOR`
en otra terminal de tu computadora. Si sólo permite claves, autoriza tu
**clave pública** desde la sesión administrativa existente:

```bash
sudo install -d -o deploy -g deploy -m 0700 /home/deploy/.ssh
sudo nano /home/deploy/.ssh/authorized_keys
sudo chown deploy:deploy /home/deploy/.ssh/authorized_keys
sudo chmod 0600 /home/deploy/.ssh/authorized_keys
```

Pega una línea de tu archivo público, por ejemplo `id_ed25519.pub`, y conserva
las claves ya autorizadas. La clave privada permanece en tu computadora.
Prueba el acceso antes de cerrar la sesión administrativa. Si SSH restringe
usuarios o grupos, incorpora `deploy` a esa política con el administrador del
servidor. Consulta [OpenSSH en Ubuntu](https://ubuntu.com/server/docs/how-to/security/openssh-server/).

Desde tu computadora, abre la sesión de trabajo:

```bash
ssh deploy@IP_DEL_SERVIDOR
```

En el servidor, verifica:

```bash
whoami
sudo -v
cat /etc/os-release
python3 --version
```

`whoami` debe mostrar `deploy`. Los pasos siguientes se ejecutan en esa sesión.
Desde la consola del proveedor también puedes usar `sudo -iu deploy` con la
cuenta administrativa inicial.

## 3. Instalar Python

Ejecuta **sólo el bloque correspondiente a tu Ubuntu**. Se instala Python 3.12;
el instalador también acepta 3.13. El comando `python3` del sistema se conserva.
Python 3.10 y 3.14 no son válidos para este despliegue.

### Ubuntu 24.04 LTS

Python 3.12 y sus complementos están en los repositorios de Ubuntu; `venv`
requiere `universe`. [Paquete oficial](https://packages.ubuntu.com/noble/python3.12-venv).

```bash
sudo add-apt-repository -y universe
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev
```

### Ubuntu 22.04 LTS

Jammy incluye Python 3.10. Para instalar 3.12 se utiliza el PPA comunitario
[Deadsnakes](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa?field.series_filter=jammy).
Es externo a Ubuntu y sus actualizaciones dependen de sus mantenedores. Si la
política del servidor exige sólo paquetes oficiales de Ubuntu, utiliza 24.04.

```bash
sudo add-apt-repository -y universe
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev
```

### Comprobar Python

```bash
python3.12 --version
python3.12 -m venv --help
```

Debe mostrar `Python 3.12.x`. Si APT informa firmas inválidas o paquetes que no
encuentra, consulta [solución de problemas](docs/troubleshooting.md). El entorno
virtual de producción lo creará el instalador.

## 4. Descargar el repositorio

Sustituye la URL por la del repositorio público o tu fork. Clona como `deploy`,
sin `sudo`, para conservar la propiedad del directorio de trabajo:

```bash
cd /home/deploy
git clone https://github.com/TU_USUARIO/TU_REPOSITORIO.git python-blaster-tts
cd /home/deploy/python-blaster-tts
```

Si ya clonaste el repositorio, entra en su carpeta existente. Usa esa ruta en
los comandos posteriores; no necesitas clonarlo de nuevo.

## 5. Preparar dependencias y configuración

```bash
sudo bash scripts/install_ubuntu.sh --prepare-only
```

Instala herramientas de compilación, crea `blaster`, copia el código a
`/opt/pythonblastertts`, prepara su `.venv`, instala dependencias con
`constraints.txt`, compila PJSUA2 y descarga el modelo Piper. La primera ejecución
puede tardar varios minutos. Todavía no inicia el servicio.

Crea `/etc/pythonblastertts/config.toml` con permisos `600` y contraseña inicial
aleatoria. Si ya existe, lo conserva. Los archivos privados `config.toml` y
`config.production.toml` no se descargan desde Git.

Para importar un TOML propio, cópialo al servidor por un canal privado y utiliza
este comando **en lugar del anterior**, antes de crear el TOML de destino:

```bash
sudo bash scripts/install_ubuntu.sh --config /ruta/privada/config.production.toml --prepare-only
```

Un `--config` posterior no reemplaza la configuración existente.

## 6. Configurar dominio, troncal y administrador

```bash
sudo nano /etc/pythonblastertts/config.toml
```

Edita los campos existentes; no agregues secciones duplicadas. Al principio del
archivo, antes de `[amd]`, `[sip]` u otra sección, deben estar:

```toml
mode = "sip"
web_port = 8765
web_public_url = "https://tts.example.com"
data_dir = "/var/lib/pythonblastertts"
voice_model = "/var/lib/pythonblastertts/voices/es_MX-claude-high.onnx"
```

Reemplaza `tts.example.com` por tu dominio. `web_public_url` identifica la URL
externa del túnel/proxy; el proceso sigue sirviendo HTTP en loopback. Para acceso
exclusivo mediante reenvío SSH, usa `http://localhost:8765`.

Para una sola troncal, edita estos campos de `[sip]` con los datos del proveedor:

```toml
[sip]
domain = "sip.proveedor.example"
username = "USUARIO_SIP"
password = 'CAMBIA_ESTA_CLAVE'
auth_username = ""
caller_id = ""
registrar = "sip:sip.proveedor.example:5060"
registration_enabled = true
transport = "udp"
dial_format = "as_entered"
```

Conserva los otros parámetros de la sección. Si la troncal autentica por IP,
usa `registration_enabled = false` y la identidad acordada con el proveedor.
Una cadena `register => ...` de Asterisk se descompone en estos campos; no se pega
como una directiva. Consulta [puertos, NAT y varias troncales](docs/configuration.md).

En `[auth]`, conserva `enabled = true`. Consulta `bootstrap_username` y
`bootstrap_password`: serán las credenciales del primer administrador web.
Puedes cambiarlas antes del primer arranque; la contraseña debe tener al menos
12 caracteres. Si la base ya tiene usuarios, estos campos no modifican sus
contraseñas. Los secretos de configuración permanecen en el TOML.

Guarda en nano con **Ctrl+O**, Enter y sal con **Ctrl+X**.

## 7. Iniciar y verificar

Desde la carpeta del repositorio:

```bash
sudo bash scripts/install_ubuntu.sh
sudo systemctl status blaster --no-pager
sudo systemctl is-enabled blaster
curl --fail http://127.0.0.1:8765/healthz
```

El servicio debe estar activo y habilitado; `/healthz` devuelve
`{"status":"ok"}`. Arranca con Ubuntu y se reinicia ante fallos. Ese endpoint
comprueba HTTP y SQLite; no confirma registro SIP ni audio con la troncal.

Para consultar errores:

```bash
sudo journalctl -u blaster -n 100 --no-pager
```

## 8. Entrar al panel

En el túnel/proxy existente, configura el dominio elegido con origen
`http://127.0.0.1:8765`, suponiendo que corre en el mismo servidor. El puerto debe
coincidir con `web_port`. No hace falta abrirlo a Internet. Para cloudflared,
consulta sus [rutas HTTP](https://developers.cloudflare.com/tunnel/routing/).

Abre tu dominio e inicia sesión con el administrador del TOML. Para acceso SSH,
con `web_public_url = "http://localhost:8765"`, ejecuta en tu computadora:

```bash
ssh -N -L 8765:127.0.0.1:8765 deploy@IP_DEL_SERVIDOR
```

Mantén esa conexión abierta y visita [localhost:8765](http://localhost:8765).
La [guía de uso](docs/usage.md) explica cómo crear la primera campaña.

## 9. Validar telefonía

Revisa el estado de la troncal en el panel. Con un contacto de prueba autorizado,
comprueba mensaje, repetición con 1, enlace con 2, audio en ambos sentidos y cierre
desde ambos teléfonos. La conexión con agente ocupa dos canales simultáneos.

SIP y RTP usan directamente la red del servidor; el túnel HTTP no transporta
las llamadas. Confirma IP autorizada, puertos y NAT con el proveedor. Consulta
[diagnóstico SIP](docs/troubleshooting.md) si el registro o el audio fallan.

Para actualizaciones, respaldos y recuperación, continúa en
[Administración en producción](docs/production.md).
