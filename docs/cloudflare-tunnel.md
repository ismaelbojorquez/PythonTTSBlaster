# Cloudflare Tunnel en producción

Esta guía administra el acceso web después de instalar Blaster. Para crear el
servidor completo sigue primero [INSTALL.md](../INSTALL.md).

## Arquitectura

```text
Navegador ── HTTPS ── Cloudflare ── túnel saliente ── cloudflared
                                                        │
                                                        └── HTTP 127.0.0.1:8765 ── Blaster

Proveedor SIP ── SIP/RTP directo ── IP del servidor ── Blaster
```

El túnel publica solamente el panel. No transporta SIP, RTP ni audio telefónico.
Blaster mantiene el puerto web enlazado a loopback y confía cabeceras de proxy
únicamente desde el mismo servidor.

## Valores que deben coincidir

Para el hostname público `app.example.com`:

| Lugar | Valor |
|---|---|
| `/etc/pythonblastertts/config.toml` | `web_public_url = "https://app.example.com"` |
| Ruta publicada del túnel | Hostname `app.example.com` |
| Servicio de origen | `http://127.0.0.1:8765` |
| Puerto local de Blaster | `web_port = 8765` |

La URL pública incluye `https://`. El servicio local utiliza `http://`; no
instales certificados en Blaster ni actives HTTPS en Uvicorn.

## Instalar el paquete oficial

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

Fuente: [paquetes oficiales de Cloudflare](https://pkg.cloudflare.com/index.html).

## Crear un túnel administrado remotamente

En Cloudflare:

1. Abre **Networking → Tunnels**.
2. Selecciona **Create Tunnel**.
3. Asigna un nombre identificable.
4. Elige Linux como conector.
5. Copia únicamente el token de la orden de instalación.
6. Abre **Routes → Add route → Published application**.
7. Selecciona el hostname público.
8. Establece el servicio `http://127.0.0.1:8765`.
9. Guarda la ruta y espera a que el conector aparezca como **Healthy**.

La ruta creada en el panel administra también el CNAME hacia el túnel. No crees
un segundo registro DNS con el mismo nombre. Consulta el procedimiento oficial
de [creación y publicación](https://developers.cloudflare.com/tunnel/setup/).

## Instalar el conector como servicio

El token permite ejecutar el túnel. No lo pegues en un issue, registro, captura,
TOML o archivo del repositorio. Evita guardarlo en el historial de la terminal:

```bash
read -rsp 'Pega el token del túnel y presiona Enter: ' CLOUDFLARE_TUNNEL_TOKEN
echo
sudo cloudflared service install "$CLOUDFLARE_TUNNEL_TOKEN"
unset CLOUDFLARE_TUNNEL_TOKEN
```

Comprueba el servicio:

```bash
sudo systemctl is-enabled cloudflared
sudo systemctl is-active cloudflared
sudo systemctl status cloudflared --no-pager
sudo journalctl -u cloudflared -n 100 --no-pager
```

`cloudflared service install` registra el conector para iniciar con Ubuntu. No
necesitas mantener una sesión SSH abierta.

## Verificar por capas

Primero confirma Blaster sin involucrar DNS ni Cloudflare:

```bash
sudo systemctl is-active blaster
curl --fail http://127.0.0.1:8765/healthz
```

Después confirma el conector:

```bash
sudo systemctl is-active cloudflared
sudo journalctl -u cloudflared -n 50 --no-pager
```

Finalmente prueba el hostname:

```bash
curl --fail https://app.example.com/healthz
```

Una respuesta correcta en las tres capas devuelve `{"status":"ok"}`. El estado
**Healthy** del túnel confirma su conexión con Cloudflare, pero no comprueba por
sí mismo que Blaster responda en el origen.

## Firewall

Cloudflare Tunnel inicia conexiones salientes y no necesita una regla de entrada
para 8765, 80 o 443. Con la política habitual de UFW:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
```

Si el proveedor del servidor restringe salida, permite TCP y UDP 7844 hacia los
destinos publicados por Cloudflare. UDP corresponde a QUIC y TCP al transporte
HTTP/2. Consulta los [requisitos oficiales de firewall](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/).

Las reglas SIP/RTP se administran por separado y deben limitarse, cuando sea
posible, a las redes del proveedor telefónico.

## Operación diaria

Estado y registro:

```bash
sudo systemctl status cloudflared --no-pager
sudo journalctl -u cloudflared -f
```

Reinicio del conector:

```bash
sudo systemctl restart cloudflared
```

Actualizar una instalación hecha con APT:

```bash
sudo apt update
sudo apt install --only-upgrade cloudflared
sudo systemctl restart cloudflared
cloudflared --version
```

Fuente: [actualización oficial de cloudflared](https://developers.cloudflare.com/tunnel/downloads/update-cloudflared/).

Una actualización del túnel no exige reiniciar Blaster. Una actualización de
Blaster tampoco exige recrear el túnel mientras el puerto local y el hostname se
conserven.

## Rotar el token

Rota el token desde **Networking → Tunnels → tu túnel → Rotate token**. El token
anterior no podrá establecer conexiones nuevas después de la rotación. En el
servidor instala el nuevo valor:

```bash
sudo cloudflared service uninstall
read -rsp 'Pega el token nuevo y presiona Enter: ' CLOUDFLARE_TUNNEL_TOKEN
echo
sudo cloudflared service install "$CLOUDFLARE_TUNNEL_TOKEN"
unset CLOUDFLARE_TUNNEL_TOKEN
sudo systemctl status cloudflared --no-pager
```

Realiza la rotación en una ventana operativa porque reinstalar el servicio
interrumpe brevemente el acceso web. Referencia:
[tokens de túnel](https://developers.cloudflare.com/tunnel/advanced/tunnel-tokens/).

## Cambiar el hostname o puerto

Finaliza campañas y aplica el cambio como una sola ventana de mantenimiento:

1. Modifica `web_public_url` o `web_port` en el TOML.
2. Edita la ruta publicada en Cloudflare con el mismo hostname y origen.
3. Reinicia Blaster.
4. Comprueba el origen local.
5. Comprueba la URL pública.

```bash
sudo -u blaster nano /etc/pythonblastertts/config.toml
sudo systemctl restart blaster
curl --fail http://127.0.0.1:8765/healthz
curl --fail https://app.example.com/healthz
```

Si cambia `web_port`, actualiza también el puerto de ambos comandos y el servicio
de origen en Cloudflare.

## Diagnóstico

### El origen local no responde

```bash
sudo systemctl status blaster --no-pager
sudo journalctl -u blaster -n 100 --no-pager
sudo -u blaster /opt/pythonblastertts/.venv/bin/python \
  /opt/pythonblastertts/scripts/check_production.py \
  --config /etc/pythonblastertts/config.toml
```

Corrige primero Blaster. El túnel no puede publicar un origen detenido.

### El origen responde y el dominio no

```bash
sudo systemctl status cloudflared --no-pager
sudo journalctl -u cloudflared -n 100 --no-pager
getent ahosts app.example.com
```

Revisa el estado **Healthy**, el hostname de la ruta y el servicio exacto
`http://127.0.0.1:8765`. No utilices la URL pública como servicio de origen.

### Error 400 o 403 al entrar o guardar

Comprueba que `web_public_url` sea exactamente el origen del navegador:

```toml
web_public_url = "https://app.example.com"
```

No agregues rutas ni una diagonal final. Después reinicia Blaster. El hostname se
usa para validar Host, Origin y las cookies de sesión.

### El túnel no conecta

Comprueba resolución DNS y salida 7844 TCP/UDP. En redes restrictivas, los
registros de `cloudflared` indican si QUIC no puede conectarse. Permite también
TCP 7844 para que el conector pueda utilizar HTTP/2.

### `NO_PUBKEY` durante `apt update`

Vuelve a descargar la clave en `/usr/share/keyrings/cloudflare-main.gpg` y
confirma que la entrada APT usa exactamente esa ruta en `signed-by`. No desactives
la verificación de firmas. Consulta [Solución de problemas](troubleshooting.md).
