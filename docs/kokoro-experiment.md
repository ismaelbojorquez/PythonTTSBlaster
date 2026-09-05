# Evaluación reversible de Kokoro

Kokoro ONNX 1.0 se integra como una opción de voz comercial en evaluación. Piper
continúa siendo la voz predeterminada hasta que un administrador elija Kokoro en
**Operación → Voces**. Sus paquetes y modelos se mantienen fuera del entorno
principal en `.venv-kokoro/` y `.cache/kokoro/`.

## Licencia

La biblioteca `kokoro-onnx` declara MIT y los pesos de Kokoro 82M declaran Apache
2.0. Para la pronunciación española utiliza Phonemizer y eSpeak NG, publicados
bajo GPLv3 o posterior. Todas permiten operación comercial. Si se redistribuye el
entorno o sus binarios deben conservarse los avisos y cumplirse las condiciones de
GPL; consulta `THIRD_PARTY.md`.

## Instalación

```bash
./scripts/install_kokoro_experiment.sh
```

Después habilita el comparador sin cambiar la voz activa:

```toml
tts_engine = "piper"

[kokoro]
enabled = true
python = ".venv-kokoro/bin/python"
model = ".cache/kokoro/models/kokoro-v1.0.onnx"
voices = ".cache/kokoro/models/voices-v1.0.bin"
voice = "ef_dora"
language = "es"
speed = 1.0
startup_timeout = 90.0
```

Las voces españolas disponibles son Dora, Alex y Santa. El panel permite medir y
escuchar cada una. **Usar esta voz** la precarga y actualiza el TOML únicamente
cuando no existen llamadas ni una campaña activa. Elegir una voz Piper restaura
Piper y cierra los procesos de Kokoro.

También puede medirse por terminal:

```bash
.venv/bin/python scripts/benchmark_kokoro.py --config config.toml
```

## Medición inicial en Apple Silicon con 8 GB

| Variante | Situación | Generación | Audio | Factor de tiempo real |
|---|---|---:|---:|---:|
| FP32 | motor caliente | 4.3–4.9 s | 17.9–18.3 s | 0.24–0.28× |
| FP32 | dos mensajes simultáneos | 4.65 s | 10.8–11.6 s cada uno | 0.40× |
| INT8 | motor caliente | 10.4–10.6 s | 17.8–18.6 s | 0.57–0.60× |

Dos procesos FP32 utilizaron cerca de 1.0 GB de memoria residente. En esta Mac,
FP32 fue más rápido que INT8. El servidor de producción debe medirse por separado
porque sus cuatro núcleos pueden ofrecer resultados distintos.

Actualmente el mensaje se genera después de que AMD identifica a una persona. La
persona escucha el audio breve de preparación durante ese tiempo. La prueba de
llamada debe confirmar si esa espera es aceptable antes de activar Kokoro en una
campaña real.

## Reversión

Selecciona cualquier voz Piper o establece:

```toml
tts_engine = "piper"
```

Detén Blaster antes de liberar el espacio de la evaluación:

```bash
rm -rf .venv-kokoro .cache/kokoro
```

Después elimina la sección `[kokoro]` o cambia `enabled = false`. Las campañas,
grabaciones, CDR y modelos Piper no dependen de esas carpetas.
