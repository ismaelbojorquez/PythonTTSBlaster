# Solución de problemas

Ejecuta los comandos de servicio en Ubuntu. No publiques TOML, contraseñas,
tokens, números de contactos ni grabaciones al solicitar ayuda.

## APT no encuentra python3.12

```bash
cat /etc/os-release
python3 --version
```

Ubuntu 22.04 incluye Python 3.10: sigue el bloque Deadsnakes de
[INSTALL.md](../INSTALL.md). Ubuntu 24.04 utiliza sus paquetes oficiales.
No cambies el enlace `/usr/bin/python3` ni uses paquetes de otra versión de Ubuntu.
El instalador selecciona Python 3.12/3.13 y crea su propio entorno virtual.

Si ya instalaste Python, comprueba que esté disponible también bajo sudo:

```bash
python3.12 --version
sudo python3.12 --version
```

Una instalación dentro del directorio privado de un usuario puede no estar en el
PATH de root y no corresponde a la instalación por APT de esta guía.

## NO_PUBKEY en el repositorio de cloudflared

Si APT indica que faltan claves para `pkg.cloudflare.com`, actualiza el archivo
de claves desde Cloudflare. Es mantenimiento del repositorio APT; estos comandos
no reinstalan ni reinician el túnel. [Instrucciones oficiales](https://pkg.cloudflare.com/index.html).

```bash
sudo install -d -m 0755 /usr/share/keyrings
BLASTER_KEY_FILE=$(mktemp)
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o "$BLASTER_KEY_FILE" &&
sudo install -m 0644 "$BLASTER_KEY_FILE" /usr/share/keyrings/cloudflare-main.gpg
rm -f "$BLASTER_KEY_FILE"
sudo apt update
```

La entrada APT de cloudflared debe usar
`Signed-By=/usr/share/keyrings/cloudflare-main.gpg` (o la sintaxis `signed-by=`
en archivos `.list`). Si usa otra ruta, corrige esa entrada siguiendo Cloudflare
y evita entradas duplicadas con distintos `Signed-By`. No desactives la
verificación de firmas ni uses `trusted=yes` para ocultar el fallo.

## El instalador dice que Blaster está activo

Finaliza las llamadas, detén el servicio y vuelve a ejecutar el instalador:

```bash
sudo systemctl stop blaster
sudo bash scripts/install_ubuntu.sh
```

Se bloquean las actualizaciones con el motor activo para evitar sustituir sus
archivos mientras trabaja.

## Falta PJSUA2, Piper o el modelo

Ejecuta el instalador desde el checkout con el servicio detenido. Éste instala
las dependencias, compila PJSUA2 y descarga el modelo que falta. Para desarrollo
usa [CONTRIBUTING.md](../CONTRIBUTING.md). No instales con el `pip` de otro Python.

Si una descarga falla por certificados, corrige el almacén CA del sistema;
no desactives TLS. Si la compilación termina con `Killed`, consulta memoria y
registros del sistema: puede ser una terminación por falta de memoria, no un
error de sintaxis. La primera compilación necesita más recursos que un panel ocioso.

## El servicio no arranca

```bash
sudo systemctl status blaster --no-pager
sudo journalctl -u blaster -n 100 --no-pager
sudo -u blaster /opt/pythonblastertts/.venv/bin/python \
  /opt/pythonblastertts/scripts/check_production.py \
  --config /etc/pythonblastertts/config.toml
```

Corrige el primer error: claves SIP faltantes, rutas, permisos, módulos nativos o
administrador inicial. El TOML debe pertenecer a `blaster` y usar permisos `600`.
El directorio que lo contiene debe permitir escritura para guardados atómicos.
Después de corregir el problema:

```bash
sudo systemctl reset-failed blaster
sudo systemctl start blaster
```

## Ya hay una instancia usando este directorio de datos

Hay otro proceso con el bloqueo de la base. Revisa primero `systemctl status
blaster`; no ejecutes `run.py` manualmente mientras el servicio está iniciado.
En desarrollo, termina la instancia anterior con Ctrl+C. Borrar el archivo de
bloqueo no es una solución: permite que dos procesos abran los mismos datos.

## El dominio devuelve error, pero el proceso está activo

```bash
curl --fail http://127.0.0.1:8765/healthz
```

Si funciona, comprueba que el túnel/proxy apunte a ese origen y que
`web_public_url` coincida con la URL externa exacta. Un 400 puede indicar Host
no admitido; un 403 al guardar puede indicar Origin distinto. Con cookies Secure,
usa la URL HTTPS externa o configura el origen HTTP correcto para acceso por SSH.
El valor `tts.example.com` de la plantilla debe sustituirse por un dominio propio.

## Prueba manual del registro SIP

Detén el servicio antes de usar los puertos de la troncal:

```bash
sudo systemctl stop blaster
sudo -u blaster /opt/pythonblastertts/.venv/bin/python \
  /opt/pythonblastertts/scripts/check_sip.py \
  --config /etc/pythonblastertts/config.toml --trunk default
sudo systemctl start blaster
```

Sustituye `default` por el ID si usas `[[trunks]]`. El script intenta un REGISTER
real, espera hasta 45 segundos y solicita desregistro al terminar; no hace llamadas.
Una troncal autenticada por IP no necesita esta prueba de registro.

| Resultado | Interpretación |
|---|---|
| 401 seguido de 200 | Desafío Digest y registro aceptado |
| 403 | Rechazo; revisar cuenta, origen, formato y reglas con el proveedor |
| 408 local de PJSIP | No llegó una respuesta final a tiempo |
| RX 408 | Se recibió un 408 desde la red |
| 487 tras una cancelación | INVITE terminado; puede ser consecuencia normal de colgar |

Registro aceptado no garantiza permisos de marcación. `ping` verifica ICMP;
una conexión TCP no comprueba una troncal UDP. Si el destino no responde, revisa
host/puerto remoto, transporte, IP autorizada y filtros de red. `local_port` no
cambia el puerto del proveedor. Referencia: [SIP RFC 3261](https://www.rfc-editor.org/rfc/rfc3261.html).

## La llamada entra, pero no hay audio o se corta

Comprueba modelo Piper, su JSON, soporte de códec y puertos RTP/RTCP. Con NAT,
revisa `public_address` y los puertos reenviados. El túnel HTTP no arregla la ruta
de medios. Consulta la etapa y el motivo del fallo en el CDR y el journal.

Si AMD cuelga antes del TTS, revisa su resultado y `unknown_action`. Un resultado
incierto no confirma buzón. [Calibra AMD](amd.md) con muestras representativas.
Para una prueba controlada puedes desactivarlo en TOML y reiniciar sin llamadas activas.

## El agente tarda en timbrar

Compara DTMF 2, envío de INVITE y respuestas 100/183/180 en la cronología. Una
solicitud inmediata seguida por un 180 tardío ubica la demora después del envío,
sin identificar por sí sola qué red la causa. SIP 183 es progreso, no confirmación
de timbrado. Los límites CPS globales y por troncal también pueden introducir espera.

## Reportes o grabaciones no disponibles

Reduce el período si el reporte supera `report_max_rows`. Comprueba que no haya
otra exportación en curso. Para audio, revisa rol, evidencia de inicio, estado de
compresión, retención y espacio libre. El analista no tiene permiso de audio.
Un CDR puede conservarse después de eliminar la grabación por retención.
