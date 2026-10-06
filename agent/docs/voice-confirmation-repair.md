# Voz, interrupciones y confirmación natural · 5–6 de octubre de 2026

## Causas comprobadas

Los eventos humanos mostraron «Confirmo la operación» bien transcrito y rechazado por el controlador. «Ejejeje Dije Confirmo» tampoco se interpretó, aunque el último segmento fue «Dije Confirmo» con buena confianza acústica. El parser exigía consumir toda la frase con un conjunto limitado de cláusulas, y la política conversacional reforzaba la exigencia de decir solamente «Confirmo».

También hubo errores reales de reconocimiento: «Comfórabo» y «Con fechito en concursos». No se conservaron grabaciones del micrófono humano porque raw_audio está desactivado. No es posible reconstruir ni medir esa entrada a partir de una transcripción; esos textos no se convierten arbitrariamente en autorizaciones.

El inicio de voz generaba dos interrupciones: la estrategia de turno de Pipecat y el callback del Supervisor. Ambas pasaban por la cabeza de toda la tubería, reiniciando procesadores de entrada y reconocimiento además de la salida. Se reemplazó esa ruta por una interrupción de salida única, inmediatamente después de detectar voz.

El adaptador HTTP de Piper emitía TTSStoppedFrame desde finally, incluso al cancelar. Ese cierre competía con el cierre del contexto gestionado por Pipecat. Ahora respeta el ciclo del proveedor HTTP y distingue contextos obsoletos de respuestas realmente vacías. «TTS context … completed with no audio» se clasificaba además como fallo del micrófono y aparecía como JSON crudo en la consola; ahora se presenta como fallo de reproducción y se conserva la escucha.

La prueba de interrupción encontró otra regresión: «Gianna, continuamos» después de pausar conservaba el borrador, pero el modelo decía que seguían sin recuperar WAITING_CONFIRMATION. Se corrigió el control de reanudación y la política exige ejecutar resume para volver a presentar una revisión válida.

## Cambios y pruebas

En una regresión de voz, «áreas registradas» se transcribió como «horas registradas»; se amplió el vocabulario del sistema. Una ejecución posterior aprobó las aserciones antiguas, pero su ticket decía «gomas (ocas)» en lugar de hojas de papel. Esa ejecución se conserva como rechazada por contenido: detectar recibo, origen y categoría no basta. `test_harness_voice.py` ahora exige hojas/papel e impresoras y rechaza esos sustantivos inventados.

La señal limpia de RNNoise sigue alimentando Silero/SmartTurn, pero Whisper recibe PCM original emparejado mediante una FIFO acotada. Esto conserva información acústica que una supresión de ruido puede atenuar, incluidas consonantes sin voz. La política exige aclarar una palabra dudosa antes de inventar un repuesto o causa. Las pruebas unitarias comprueban el emparejamiento aunque el resampler agrupe chunks y la separación entre audio de detección y reconocimiento.

La interpretación semántica usa el mismo DeepSeek configurado y decide sobre la oración completa y el borrador revisado. No dispone de capacidad de escritura. Una respuesta tardía o dudosa no puede autorizar otro cambio: se conservan las comprobaciones de generación, actor, sesión, revisión, hash, propiedad y vencimiento. Una corrección tiene prioridad sobre la aprobación.

La voz agrega evaluación de similitud fonética, sin reescribir la transcripción guardada ni convertir cualquier ruido en aprobación. Se exige intención approve y un piso de 80 para voz, 85 para texto; los valores son juicios del modelo, no probabilidades calibradas. El caso «Consirvo» reproduce una variante de «Confirmo» que el modelo interpreta dentro de una revisión vigente. Negaciones, condiciones, citas, otro ticket/estado y palabras con otro significado siguen sin autorizar el envío.

Se desactivó por defecto la ganancia automática del navegador, también en la preferencia de la instancia de pruebas del usuario. Las capturas RTC anteriores llegaban cerca de amplitud máxima y distorsionaban palabras. La ganancia acotada de Whisper sigue ayudando a entradas bajas; la opción del navegador permanece disponible. La configuración efectiva aplicada se verifica en los eventos audio_settings.

Whisper recibe contexto de español rioplatense y un vocabulario equilibrado con confirmaciones, negaciones y correcciones. El recorte sólo elimina silencio exterior, con márgenes de 250 ms, conservando pausas internas y evidencia por segmento. La consola corta localmente la reproducción al comenzar voz humana; mantiene la captura y vuelve a habilitar la salida para una nueva respuesta. El modo de diagnóstico de audio se activa sólo en la prueba con entrada sintética; la instancia del usuario continúa sin guardar grabaciones.

- `test_review_meaning_live.py`: 40 casos; 38 interpretados con DeepSeek real y dos prefijos de datos literales bloqueados antes del modelo. Incluye frases completas, una rectificación propia, variantes plausibles de transcripción, negación, espera, correcciones, condiciones, otro ticket/estado, citas de terceros y frases ininteligibles. Usa una conexión HTTP persistente como el runtime.
- `test_review_meaning.py`: respuestas tardías tras pausa/edición/cambio de cuenta/sesión/vencimiento/nueva generación, incertidumbre y caída del intérprete. Ninguno puede producir un envío.
- `test_audio_cancellation.py`: corte sin resetear captura, cancelación de TTS sin falso fallo, fallo real y recuperación del aviso.
- `test_native_barge_in.py`: ocho respuestas cortas con Whisper e interpretación semántica reales, a volumen normal y al 18 %. Se conservan las transcripciones efectivas, incluidas variantes; las aprobaciones deben entenderse y las negaciones deben conservarse sin autorizar. Luego usa micrófono WAV nativo de Chromium, WebRTC, RNNoise/Silero/Whisper/SmartTurn, DeepSeek, Piper y API/MariaDB. Niega durante una revisión, retoma y confirma dentro de una oración mientras la revisión está hablando. Cada intervención se reproduce una sola vez. Exige un único ticket y mide la salida RTC antes/después del corte. No sustituye getUserMedia, la transcripción ni autoplay.
- UI: corte local, nueva reproducción, micrófono conservado y ausencia de JSON crudo/falso aviso de micrófono ante fallo TTS.

Los resultados finales se registran en `artifacts/gianna-native-barge-in.json`, `gianna-review-meaning-live.jsonl`, los logs asociados y el informe de aceptación. Los intentos rechazados se conservan como tales. La entrada es voz sintética de Daniela: no acredita precisión para todos los hablantes ni eco físico de un micrófono/altavoz humano.
