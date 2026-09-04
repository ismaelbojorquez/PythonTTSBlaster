# Dependencias y procedencia

- **PJSIP 2.17**: https://github.com/pjsip/pjproject/tree/2.17. Código descargado
  por el script de compilación desde el repositorio oficial. Conserva las licencias
  del proyecto y de sus componentes; consulta `COPYING` y la información comercial
  de Teluu antes de distribuir un producto que lo incluya.
- **Piper**: https://github.com/OHF-Voice/piper1-gpl. Motor local con licencia
  GPL-3.0; instalación mediante `piper-tts` desde PyPI.
- **NumPy**: https://numpy.org/. Cálculo numérico y FFT del AMD determinista;
  no aporta modelos de IA. Su distribución conserva su licencia BSD y avisos
  de componentes incluidos. Las reglas AMD son una implementación propia;
  Asterisk y FreeSWITCH sólo se consultaron como referencias de funcionalidades.
- **Voz predeterminada del ejemplo**: `es_MX-claude-high`, descargada mediante la
  herramienta oficial de Piper. Su tarjeta declara español de México, 22,050 Hz
  y licencia Apache-2.0 para el conjunto de datos. La muestra
  `es_MX-ald-medium` se conserva para comparación. Tarjeta de Claude:
  https://huggingface.co/rhasspy/piper-voices/tree/main/es/es_MX/claude/high.
- **Voz de ejemplo original**: `es_MX-ald-medium`, descargada mediante la herramienta
  oficial de Piper desde
  https://huggingface.co/rhasspy/piper-voices/tree/main/es/es_MX/ald/medium.
  El modelo y su configuración quedan en `voices/`, fuera del control de versiones.
  Consulta el `MODEL_CARD` de esa voz para sus condiciones de uso.
- **examples/mensaje.wav**: generado localmente con esa voz a partir del texto
  ficticio «Hola Ana. Te recordamos tu cita de mañana. Presiona uno para escuchar
  de nuevo el mensaje. Presiona dos para hablar con un agente.» No contiene audio
  capturado de personas ni de llamadas.
- **Kokoro ONNX 1.0 INT8**: se utilizó únicamente para comparar latencia. La
  envoltura `kokoro-onnx` declara MIT y el modelo Kokoro declara Apache-2.0:
  https://github.com/thewh1teagle/kokoro-onnx. No es una dependencia del motor
  instalado. `examples/tts-kokoro-dora-int8.wav` es audio sintético de prueba.
- **Comparación TTS**: los tres archivos `examples/tts-*.wav` usan el mismo texto
  ficticio. No contienen grabaciones, clonación de voz ni datos de una llamada.
- **Interfaz**: sin fuentes remotas, CDN, fotos ni paquetes de iconos. El símbolo
  geométrico y los diagramas SVG están creados dentro del proyecto.
- **Chart.js 4.5.1**: https://www.chartjs.org/. Distribución UMD conservada dentro
  de `static/` para que el dashboard funcione sin internet. Licencia MIT.
- **openpyxl 3.1.5**: https://openpyxl.readthedocs.io/. Genera los reportes XLSX
  localmente desde Python. Licencia MIT; `et-xmlfile` se instala como dependencia.

- **SoundFile 0.13.1**: https://python-soundfile.readthedocs.io/. Codificación y
  lectura local Ogg Opus a través de libsndfile, incluida en su wheel para macOS.
  Consulta las licencias empaquetadas de SoundFile, libsndfile y sus codecs.
- **tomlkit 0.15.1**: https://github.com/python-poetry/tomlkit. Escritura del TOML
  conservando comentarios y formato. Licencia MIT.
- **phonenumbers 9.0.38**: https://github.com/daviddrysdale/python-phonenumbers.
  Reglas locales de numeración internacional basadas en libphonenumber. Convierte
  los números nacionales usando el país seleccionado. Licencia Apache-2.0.

El código original de la aplicación se distribuye bajo la licencia
[MIT](LICENSE), Copyright (c) 2026 c1ph3rbyt3. Las dependencias y voces conservan
sus propias licencias y avisos; la licencia de la aplicación no los sustituye.
