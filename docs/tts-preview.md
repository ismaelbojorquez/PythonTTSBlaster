# Escuchar el TTS antes de crear una campaña

En **Nueva campaña → Así será la llamada → Escuchar TTS**, escribe el mensaje y
pulsa el botón. Si utilizas variables como `{nombre}`, carga primero un contacto
con esas columnas y selecciona su país: se utilizan los datos de la primera fila
del CSV o Excel importado, con cualquier encabezado como variable (`{Nombre completo}`,
`{Importe}`, etc.) y el teléfono convertido al formato internacional que se marcará. Un mensaje
sin variables puede escucharse sin completar el nombre de campaña ni el agente.

La muestra usa el modelo Piper indicado en `voice_model` de `config.toml` e incluye
el menú final de opciones 1 y 2. Funciona también en modo simulación si el modelo
y Piper están instalados. La primera muestra puede tardar más porque carga la voz;
las siguientes reutilizan el modelo. En SIP se comparte el motor ya cargado.

El reproductor permite pausar y volver a escuchar sin generar otra muestra.
Editar el mensaje, los contactos, su país o la plantilla invalida el audio anterior. Al
salir del editor o cerrar sesión se detiene la reproducción y se libera la muestra.

La vista previa no crea campañas ni llamadas, no utiliza la troncal y no se guarda
como grabación o CDR. Sólo se registra la acción de generar audio en auditoría.
El WAV temporal del servidor se elimina al terminar; se admite una generación de
vista previa a la vez, con el límite de tiempo `tts_timeout`.
