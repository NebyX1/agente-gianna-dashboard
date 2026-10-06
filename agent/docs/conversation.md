# Conversar y trabajar con Gianna

Llamar a Gianna («Gianna», «Hola Gianna», «Gianna, ¿estás ahí?») o pulsar **Activar Gianna** sólo recibe la bienvenida «Hola, soy Gianna y ya estoy activada.». Ya activa, «¿Estás ahí?» recibe: «Sí, estoy acá y te escucho. ¿En qué te puedo ayudar? Podés registrar un pedido, consultar un ticket o cambiar su estado». La conversación empieza sin crear un ticket. El borrador se inicia al pedir registrar uno o pulsar **Nuevo ticket**. Si contás un problema sin pedir su registro, ofrece abrir el ticket y espera tu respuesta antes de crear el borrador. Esa respuesta no envía nada: después vienen los datos, la revisión y la confirmación del envío.

Las intervenciones libres pasan por DeepSeek Cloud con el historial de la sesión y herramientas nativas. «¿Qué áreas registradas tenés?» consulta y enumera nombres reales; «la segunda de las que dijiste» puede seleccionar esa opción conservando la descripción. «¿Y los tipos?» continúa la consulta, y «¿qué te pedí?» usa lo que se conversó. Las preguntas durante la revisión conservan el pedido y su confirmación vigente. Las aclaraciones sobre si está escuchando reciben una respuesta de presencia. Lo desconocido pide aclaración; nunca cae automáticamente en dictado. Si falla una consulta se conserva el pedido. **Descartar borrador** lo retira de los pedidos activos sin tocar tickets remotos. **Borrar conversación** limpia el chat, su memoria de herramientas y los borradores locales sin transferir de la cuenta para empezar de cero.

| Situación | Ejemplos | Respuesta y comportamiento |
|---|---|---|
| Presencia | «¿Estás ahí?», «¿Me escuchás?», «¿Estás disponible?» | Confirma disponibilidad y ofrece ayuda. Con un pedido pendiente, recuerda el dato que falta. |
| Saludo | «Hola», «Buenas tardes», «¿Cómo andás?» | Saluda y pregunta en qué ayudar. |
| Orientación | «¿Qué podés hacer?», «Explicame las opciones», «¿Cómo hago un ticket?» | Explica funciones y permisos con el contexto actual. |
| Catálogos | «¿Qué áreas registradas tenés?», «¿Y los tipos?», «¿Qué destinos reciben tickets?» | Consulta datos reales, enumera opciones y permite elegir una de la lista. |
| Agradecimiento o reconocimiento | «Gracias», «Perfecto», «Lo entendí», «Dale» | Responde y conserva el pedido. No autoriza un envío. |
| Corrección | «Perdón, me equivoqué», «Corregí la descripción: …», «Cambiá el origen a Tránsito» | Ofrece corregir; sólo la corrección explícita cambia los datos. |
| Repetición | «No entendí», «Repetí la pregunta», «¿Podés repetir la revisión?» | Repite la pregunta o revisión actual, incluso después de un saludo. |
| Ritmo | «Hablame más despacio» | Reduce la velocidad de Piper y guarda la preferencia para la cuenta. |
| Siguiente paso | «¿Qué falta?», «¿Qué tengo que decir?», «¿Cómo seguimos?» | Explica el dato pendiente o cómo revisar y confirmar. |
| Resultado | «¿Ya lo guardaste?», «¿Qué estás haciendo?» | Distingue borrador, ejecución, resultado incierto y comprobante. Un recibo anterior no acredita el pedido actual. |
| Pausa | «Esperame un minuto», «Estoy al teléfono», «No lo envíes» | Conserva el borrador. Un intento ya enviado se comprueba antes de cualquier otro. |
| Reanudar | «Gianna, seguimos», «Retomemos el borrador», «Ya volví» | Retoma el dato faltante; un borrador completo vuelve a revisarse. |
| Terminar conversación | «Finalizá la conversación», «Gracias, hasta luego», «Terminamos por hoy» | Conserva el borrador sin enviar y mantiene el micrófono listo para la próxima invocación. |
| Finalización ambigua | «Listo», «Finalizá eso», «Terminá todo» | Con un pedido pendiente, aclara qué se quiere terminar. |
| Registrar | «Quiero crear un ticket», «Necesito registrar un pedido» | Pide los detalles del problema, sin usar la orden como descripción. |
| Consultar | «Mostrame el ticket número 10», «Buscá tickets con la palabra impresora», «Historial del ticket 10» | Lee datos reales y muestra la pantalla correspondiente. |
| Completar un ticket | «Resolvé el ticket número 10», «Finalizá el ticket 10», «Marcá el ticket 10 como resuelto» | Identifica un ticket, verifica su estado, pide motivo, lee la revisión y espera confirmación. |
| Cancelar un ticket | «Cancelá el ticket número 10» | Prepara Cancelado, pide motivo y confirmación. |
| Abrir o tomar control | «Abrí el tablero», «Tomar el control manual» | Abre la superficie real; el control manual requiere un borrador y transfiere su propiedad. |

Las transiciones se toman del catálogo del sistema. Un ticket Nuevo debe pasar primero a En curso para quedar Resuelto. Si se pide un cambio no permitido, Gianna explica las alternativas antes de enviar. Si ya está en el estado solicitado, lo informa y evita repetir el cambio.

Resolver otro ticket conserva el borrador anterior y anula su confirmación. Después se puede pedir «retomemos el borrador» para recuperarlo. Gianna no continúa escribiendo en un formulario transferido al usuario.

«Otro ticket» o «Nuevo ticket» empieza un borrador nuevo y conserva el anterior. «Retomemos el borrador anterior» permite volver a él; sólo recupera borradores de la misma cuenta.

Por voz, fuera de una conversación activa, hay que dirigirse a Gianna por su nombre. El filtro de menciones y DeepSeek distinguen hablarle de hablar sobre ella. En modo Cloud no se llama a Qwen ni Tev. En el cuadro de texto se puede preguntar directamente «¿Estás ahí?».

Un reclamo como «Estás entendiendo mal» pregunta qué debe reemplazarse; no responde enumerando capacidades. «Eso está mal, lo que dije es que desde Secretaría General nos pidieron poner nuevas hojas a las impresoras» reemplaza la descripción por el fragmento literal y revisa el origen. Si Secretaría General no figura en el catálogo, retira el origen anterior y pregunta a qué área registrada corresponde; nunca conserva Sociales por defecto. Una oración larga que menciona «impresoras» aporta todos sus datos: sólo un nombre breve de catálogo responde exclusivamente al campo Tipo. Agregar información durante la revisión exige una intención concreta de agregar; un sí ambiguo no cambia el texto ni autoriza el envío.

La interpretación separa la forma de dirigirse a Gianna, el consentimiento, la acción y los datos. Durante una revisión de creación, «Eso es todo, Gianna, registrá», «Listo, guardalo», «Sí, podés registrarlo» y «Confirmo, Gianna» autorizan la operación revisada. Fuera de una revisión lista, esas respuestas no crean ni envían un ticket. La autorización sigue vinculada a actor, sesión, herramienta, recurso y datos; repetirla durante el envío no inicia otra operación.

«Sí, pero el origen es Informática» corrige el origen antes de volver a revisar. «No, todavía no» pide los cambios pendientes. Una corrección sin el dato, como «Corregí la descripción», pregunta qué cambiar y conserva el contenido. Una confirmación mal transcrita no puede reemplazar el pedido por una sugerencia del modelo; conserva la revisión y pide aclaración. «Si está correcto, registralo» es condicional; una frase dudosa no modifica el borrador ni renueva la confirmación por su cuenta.

«Necesito registrar un nuevo ticket. Desde Tránsito…» separa la orden y la descripción, tanto al llamar a Gianna como durante la conversación. Los datos conservan nombres y citas: «La usuaria Gianna no puede imprimir» mantiene el nombre. «La aplicación no permite finalizar la operación» o `Descripción: "¿Estás ahí?" aparece en la pantalla` siguen siendo contenido.

Si no hay coincidencia literal para el tipo de problema, Tev puede clasificar los síntomas entre las categorías reales y sus alias. Por ejemplo, papel atascado y dificultades para imprimir pueden identificar Impresoras aunque la transcripción de esa palabra sea imperfecta. Se conserva el texto original y el tipo se lee en la revisión; una clasificación incierta pregunta el tipo, y una respuesta tardía no modifica un pedido pausado. No se vuelve a clasificar un tipo ya elegido por una frase adicional sin una categoría explícita.

El reconocimiento de audio puede equivocarse. Las pruebas guardan la transcripción efectiva; no convierten «Lo entendí» en «No entendí» ni una afirmación dudosa en confirmación. Motores y herramientas: [voz](voice.md) y [perfiles](profiles.md).

Si hay voz pero los segmentos no pasan el control de confianza, pide repetir o escribir en la consola. Conserva el pedido y el vencimiento original; no convierte un audio rechazado en una orden.
