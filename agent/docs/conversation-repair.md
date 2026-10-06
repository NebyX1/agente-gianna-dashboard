# Diagnóstico y reparación de conversación · 5 de octubre de 2026

## Qué falló

La conversación real quedó en los eventos locales. El primer relato contenía el origen Sociales y el pedido de cambiar hojas de las impresoras, pero el modelo pidió otra vez el origen. Al recibir «Te acabo de decir la oficina de servicios sociales», consultó el catálogo y eligió correctamente origen 4, destino 1 y tipo 2. Tres intentos de preparar el ticket fallaron: la herramienta exigía que la descripción fuera una subcadena de esa última aclaración, excluyendo el relato anterior. Además, el esquema ofrecía IDs en create y su implementación los prohibía. El cuarto límite de ronda terminó en una respuesta genérica que ocultaba la causa.

La preparación también reanalizaba datos mediante otros modelos de intención, menciones y clasificación. Una llamada exitosa que leía la revisión terminaba antes de guardar su intercambio en el historial. El resultado era un modelo con contexto incompleto, herramientas contradictorias y demasiadas interpretaciones del mismo dato.

La validación de este arranque comprobó procesos, login, micrófono y recepción de paquetes. Eso no acredita usabilidad conversacional. Las pruebas anteriores tenían casos muy guiados, relatos de un solo turno, una oficina/categoría preponderantes y aserciones que identificaban frases esperadas. No cubrían el caso de un relato anterior seguido de una aclaración, ni la combinación de create con IDs que su esquema ofrecía. Sus resultados eran regresiones acotadas, no garantía de comprensión general. Declarar la aplicación lista para usar a partir del arranque fue incorrecto.

La nueva prueba completa también encontró que «Confirmo, marcalo como resuelto» no se reconocía. El modelo podía anunciar el comprobante anterior aunque el borrador nuevo siguiera sin guardar. Se corrigió la gramática de esa confirmación y el contexto separa el comprobante anterior del trabajo pendiente. La prueba exige leer el estado final y el motivo en la API; una frase de éxito no la aprueba.

## Qué cambió

- Una sola ruta de conversación y preparación mediante herramientas nativas de DeepSeek.
- Catálogos con orígenes y destinos separados; cualquier área puede solicitar aunque no reciba tickets.
- Descripciones basadas en hechos del historial, sin una restricción de cita literal del último turno.
- Preparación estructurada directa, IDs validados y una revisión completa antes de escribir.
- Correcciones, selecciones sin cambios y motivos ya suministrados conservan el contexto apropiado.
- Historial con llamadas/resultados exitosos y fallidos, y diagnóstico de cada fallo de turno.
- Revisiones de cambios con el código público del ticket y confirmaciones correspondientes al estado revisado.

El backend de tickets, autenticación, idempotencia, comprobantes y audio se conservan porque el fallo demostrado estaba en la coordinación conversacional. No era necesario borrar esos componentes ni sustituir DeepSeek/Ollama. La comparación con Hermes se documenta en [arquitectura](architecture.md).

## Evidencia y límites

La suite `tests/unit` y `tests/contracts` comprueba invariantes con dobles de transporte/modelo; no acredita semántica. `tests/integration/test_cloud_harness.py` usa DeepSeek real con catálogos y lecturas de tickets simulados explícitamente, incluidos el relato exacto, aclaraciones, paráfrasis, otras categorías y correcciones. Sus resultados se guardan en `artifacts/gianna-harness-repair-cloud.json/.log`.

`tests/e2e/test_conversation_repair.py` reproduce los mensajes de las capturas desde la interfaz real, con login y delegación normales, DeepSeek, Flask y MariaDB del proyecto aislado `idl-tickets-design-check`. Comprueba creación, repetición sin duplicado, corrección, pausa/reanudación, En curso, resolución con motivo ya indicado y lectura del resultado e historial. Evidencia en `artifacts/gianna-conversation-repair-ui.json/.png` y `gianna-repair-e2e.log`.

`tests/e2e/test_harness_voice.py` usa audio sintético de Daniela como micrófono nativo de Chromium, WebRTC, Whisper, DeepSeek, Piper, interfaz y API reales. No sustituye transcripciones ni llama a submit directamente. Conserva los eventos y comprueba un ticket con confirmación. No mide eco físico ni precisión con hablantes humanos independientes.

Los logs de intentos fallidos se preservan; no cuentan como aprobados. Ninguna suite garantiza entender cualquier frase futura. Las pruebas de escritura usan la base aislada, no los tickets de la demo del usuario. Los resultados finales de esta revisión se registran en [aceptación](acceptance-report.md).
