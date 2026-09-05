# Escuchar el TTS antes de crear una campaña

En **Nueva campaña → Así será la llamada → Escuchar TTS**, escribe el mensaje y
pulsa el botón. Si utilizas variables como `{nombre}`, carga primero un contacto
con esas columnas y selecciona su país: se utilizan los datos de la primera fila
del CSV o Excel importado, con cualquier encabezado como variable (`{Nombre completo}`,
`{Importe}`, etc.) y el teléfono convertido al formato internacional que se marcará. Un mensaje
sin variables puede escucharse sin completar el nombre de campaña ni el agente.

La muestra usa el motor indicado en `tts_engine` de `config.toml` e incluye
el menú final de opciones 1 y 2. Funciona también en modo simulación si la voz
está instalada. La primera muestra puede tardar más porque carga la voz;
las siguientes reutilizan el modelo. En SIP se comparte el motor ya cargado.

Debajo del reproductor se muestran el tiempo de generación, los segundos de audio
producidos y el factor de tiempo real. Un factor `0.25×`, por ejemplo, significa
que generar el audio tomó una cuarta parte de su duración. También aparece una
recomendación operativa calculada en ese equipo. La carga inicial se presenta por
separado y no forma parte de la recomendación porque el motor mantiene la voz
precargada durante las llamadas.

Los administradores pueden abrir **Comparar voces** desde el creador o entrar a
**Operación → Voces**. Cada modelo instalado puede medirse con una frase fija y
escucharse antes de activarlo. Activar una voz la carga y verifica primero, luego
actualiza `voice_model` en el TOML. Se requiere detener la campaña y esperar a que
terminen las llamadas.

El reproductor permite pausar y volver a escuchar sin generar otra muestra.
Editar el mensaje, los contactos, su país o la plantilla invalida el audio anterior. Al
salir del editor o cerrar sesión se detiene la reproducción y se libera la muestra.

La vista previa no crea campañas ni llamadas, no utiliza la troncal y no se guarda
como grabación o CDR. Sólo se registra la acción de generar audio en auditoría.
El WAV temporal del servidor se elimina al terminar; se admite una generación de
vista previa a la vez, con el límite de tiempo `tts_timeout`.
