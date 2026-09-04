# Detección local de buzón sin IA

El detector utiliza reglas acústicas en Python/NumPy, integradas con el audio entrante
de PJSUA2. No usa modelos entrenados, reconocimiento de palabras, servicios web,
Asterisk ni FreeSWITCH. El TTS usa Piper, un modelo neuronal local; AMD no utiliza modelos de IA.

## Criterios de diseño

El detector combina temporización de voz y pausas con análisis espectral de tonos.
Está integrado en el mismo proceso que SIP y no necesita una central ni una API
externa. Las reglas son una implementación propia. No hay una evaluación con
llamadas etiquetadas que permita atribuirle una precisión comparativa de mercado.

## Recorrido de la llamada

1. El contacto contesta y PJSUA2 confirma medios activos. No se analiza el 183.
2. Se conecta exclusivamente su audio recibido a un puerto PCM de 8 kHz, mono,
   16 bits. No se reproduce tono de espera ni TTS durante este análisis.
3. **Humano probable:** saludo breve y pausa. Se libera el detector y comienza
   la generación/reproducción del mensaje con el menú habitual.
4. **Buzón probable:** saludo largo, demasiados segmentos de voz o un pitido
   estable. Se cuelga sin sintetizar el mensaje ni marcar al agente.
5. **Incierto:** silencio inicial, plazo agotado o muestras inutilizables. Se
   aplica `unknown_action`; no se presenta como buzón confirmado.

El análisis se aplica al contacto. El número del agente conserva la marcación y
el puente existentes. El detector no continúa escuchando durante el mensaje ni
la conversación. Una contestadora que imite un saludo humano corto puede pasar
el filtro; no se detectará un pitido que llegue después de decidir humano.

Los estados del panel son **Detectando voz**, **Buzón probable** y **AMD incierto**.
El historial conserva resultado, causa, duración y número de segmentos. Los dos
resultados que cuelgan son terminales, liberan canales y aparecen en el CSV con
su detalle. Una decisión humano o incierto que continúa se consulta en el
historial aunque luego el estado final cambie a conversación finalizada.

## Configuración de ejemplo

Todos los parámetros están en `[amd]` de `config.toml`. El archivo de ejemplo
contiene el siguiente perfil inicial comentado:

| Parámetro | Valor | Efecto |
|---|---:|---|
| `enabled` | `true` | Activa AMD antes del TTS. |
| `unknown_action` | `"hangup"` | Prioriza cortar tiempo conectado si no se puede decidir. `"continue"` permite seguir. |
| `total_analysis_ms` | 5000 | Plazo de análisis, incluyendo ausencia de muestras. |
| `initial_silence_ms` | 2500 | Sin un saludo válido en este plazo: incierto. |
| `after_greeting_silence_ms` | 1000 | Pausa tras voz breve para clasificar humano probable. |
| `greeting_speech_ms` | 2400 | Voz acumulada que dispara buzón probable. No incluye las pausas. |
| `minimum_word_ms` | 100 | Duración mínima de un segmento para reconocer un saludo. |
| `between_words_silence_ms` | 100 | Pausa para comenzar otro segmento. |
| `maximum_words` | 5 | Más de cinco segmentos dispara buzón probable. No son palabras transcritas. |
| `silence_threshold` | 256 | Umbral RMS sobre PCM16, después de quitar el desplazamiento DC. |
| `beep_enabled` | `true` | Usa también detección de pitido. |
| `beep_min_ms` | 240 | Duración mínima de un tono estable. |
| `beep_min_hz` / `beep_max_hz` | 600 / 2000 | Banda de tonos examinada. |
| `beep_purity` | 0.90 | Concentración espectral mínima en torno a una frecuencia. |
| `beep_frequency_tolerance_hz` | 35 | Variación máxima respecto de la frecuencia inicial del tono. |

Se procesan tramas de 20 ms; las comparaciones se redondean efectivamente a esa
resolución. El pitido usa ventanas Hann de 40 ms, FFT y energía de tres bins
alrededor del pico. Dos tonos de energía comparable no pasan la prueba de pureza.
Esto ayuda a separar DTMF del pitido; no sustituye a un detector de fax, IVR o
filtros de llamadas. Un silbido o una vocal casi sinusoidal pueden confundirlo.

Un saludo artificial de 400 ms seguido de silencio decide humano aproximadamente
al completar 1400 ms de audio. Un saludo continuo se corta al acumular 2400 ms de
voz. Son consecuencias de los umbrales, no tiempos garantizados para la red real.
El reloj de análisis empieza al abrir la captura; la señalización y el cierre SIP
tienen sus propios tiempos. Durante un hueco RTP PJMEDIA puede entregar silencio
o audio reconstruido: el detector no puede saber si ese silencio vino del teléfono.

Reinicia el proceso después de editar el TOML, al terminar las llamadas activas:

```bash
.venv/bin/python run.py --config config.toml --check
.venv/bin/python run.py --config config.toml
```

Para volver al flujo anterior: `enabled = false`. En configuraciones antiguas
sin `[amd]`, AMD permanece apagado. En simulación se utiliza un saludo artificial;
la demostración no mide la precisión con personas o buzones reales.

## Coste y precisión

AMD necesita audio después de la respuesta. **No garantiza evitar el cargo por
una llamada contestada por buzón.** Cortar pronto reduce tiempo conectado, pero
el ahorro facturado depende del cobro inicial, redondeo y tarifa de la troncal.
Si se cobra el primer minuto completo, colgar a los 2 segundos puede costar lo
mismo que a los 40. El ahorro debe medirse con la tarifa y el tráfico de cada instalación.
La necesidad de respuesta/audio antes de clasificar también está documentada por
[Vonage](https://developer.vonage.com/en/voice/voice-api/concepts/advanced-machine-detection).

Un saludo humano largo puede confundirse con buzón; un mensaje grabado corto con
pausa puede confundirse con humano. Ruido, volumen bajo, RTP defectuoso y sistemas
de filtro de llamadas afectan el resultado. Con `unknown_action = "hangup"` también
se pierden humanos silenciosos o lentos. La aplicación conserva el motivo para
que se pueda ajustar el perfil sin ocultar esos casos.

Los valores iniciales requieren calibración con la troncal y destinos reales.
No se midió un porcentaje de precisión y no se atribuye uno a las pruebas
sintéticas. Conviene comparar muestras etiquetadas de varios teléfonos y
operadores; los riesgos de ajustar sólo con unos pocos teléfonos están descritos
en las [recomendaciones de Twilio](https://www.twilio.com/docs/voice/answering-machine-detection-faq-best-practices).

- Humanos marcados como buzón por saludo largo: aumentar `greeting_speech_ms` o
  `maximum_words`, dentro del plazo total. Aumentará el tiempo conectado a máquinas.
- Buzones breves marcados como humano: aumentar `after_greeting_silence_ms`.
  También aumenta el silencio que percibe una persona antes de escuchar el mensaje.
- Humanos que tardan en hablar: aumentar `initial_silence_ms` o cambiar inciertos
  a `"continue"`; esto deja pasar más buzones silenciosos.
- Voz baja/ruido: ajustar `silence_threshold` con muestras representativas.
  Bajarlo aumenta sensibilidad a voz débil y también a ruido.

## Verificación sin gastar en llamadas

```bash
.venv/bin/python scripts/check_amd.py --config config.toml --wav saludo.wav
```

Acepta WAV PCM16 mono a 8000 Hz. No registra la troncal ni llama; aplica los mismos
umbrales aunque `enabled` esté apagado. La duración mostrada es tiempo del audio.
El archivo debe incluir las pausas reales; no se inventa silencio al final de un
archivo recortado. Un archivo insuficiente produce incierto.

Las pruebas automatizadas incluyen saludos, mensajes largos, pitidos, tonos
dobles, clics, DC, ruido bajo, silencio, plazos, desbordamiento, concurrencia y
cancelación. Una prueba SIP nativa envía tres flujos PCMU por localhost, verifica
sus tres resultados y que sólo el saludo humano provoca TTS. Otra comprueba que,
tras liberar la captura, siguen funcionando reproducción, DTMF y puente.

## Recursos y privacidad del audio

[`AudioMediaPort`](https://docs.pjsip.org/en/latest/specific-guides/audio/audio_frame_manipulation.html)
entrega tramas a una cola acotada: como máximo un segundo de PCM por llamada.
El callback nativo sólo copia muestras; NumPy analiza fuera del reloj de medios.
Un desbordamiento produce incierto para no clasificar audio incompleto como humano.
No se guardan WAV de entrada ni se envían muestras a otro servicio. La captura se
desconecta al decidir, al colgar, al detener campaña o al cerrar el motor.
