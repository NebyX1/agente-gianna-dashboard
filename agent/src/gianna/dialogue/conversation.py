"""Local conversation policy, separate from ticket dictation and write authority.

Match complete utterances only. Words quoted inside an incident description are
content, never commands. Voice activation still belongs to the wake/Tev gate.
"""

import re
from enum import StrEnum

from gianna.dialogue.activation import normalize
from gianna.dialogue.numbers import NUMBER_WORDS


class Intent(StrEnum):
    PRESENCE = "presence"
    GREETING = "greeting"
    WELLBEING = "wellbeing"
    HELP = "help"
    THANKS = "thanks"
    APOLOGY = "apology"
    REPEAT = "repeat"
    SLOWER = "slower"
    NEXT = "next"
    PROGRESS = "progress"
    PAUSE = "pause"
    RESUME = "resume"
    RESUME_PREVIOUS = "resume_previous"
    END = "end_conversation"
    FINISH = "clarify_finish"
    CREATE = "start_request"
    BOARD = "open_board"
    HANDOFF = "manual_control"
    ACK = "acknowledgment"


PATTERNS = {
    Intent.RESUME_PREVIOUS: (
        r"(?:retoma|retomemos|continua|sigamos con) (?:el )?(?:borrador|pedido) anterior",
    ),
    Intent.CREATE: (
        r"(?:(?:quiero|necesito|podemos|podes|puedes) )?(?:registrar|registra|crear|crea|hacer|hace|redactar|redacta) (?:un |otro |el )?(?:nuevo )?(?:ticket|pedido)(?: nuevo)?",
        r"(?:nuevo|otro) (?:ticket|pedido)",
    ),
    Intent.BOARD: (r"(?:abrir|abre|abri|mostra|mostrame|muestra|muestrame) (?:el )?tablero",),
    Intent.HANDOFF: (r"(?:tomar|tomo) el control(?: manual)?|yo continuo|lo hago yo",),
    Intent.END: (
        r"(?:(?:muchas )?gracias(?: por (?:todo|tu ayuda|la ayuda))? )?"
        r"(?:chau|chao|adios|hasta luego|hasta manana|nos vemos|eso (?:es|era) todo|"
        r"no necesito (?:nada|mas)|no necesito nada mas|terminamos(?: por hoy)?|"
        r"(?:termina|finaliza|cerra|cierra|cerrar|finalizar|terminar) (?:la |esta )?"
        r"(?:conversacion|charla|sesion)|dejemoslo (?:aca|por hoy))",
    ),
    Intent.PAUSE: (
        r"(?:para|parate|detenete|detente|cancelar|cancela|pausa|pausar|"
        r"(?:espera|esperame|aguarda|aguardame)(?: (?:un (?:momento|segundo|minuto)|un poquito))?|"
        r"dame un (?:momento|segundo|minuto)|estoy (?:al telefono|el telefono|en el telefono|en una llamada|hablando por telefono|atendiendo una llamada)|"
        r"(?:pausa|paremos|paramos) (?:la conversacion|un momento)|"
        r"(?:cancela|no envies|no mandes|no registres|no guardes) (?:el |este )?(?:envio|pedido|ticket)|"
        r"no lo (?:envies|mandes|guardes|borres|ocultes))",
    ),
    Intent.RESUME: (
        r"(?:retomar|retoma|retomemos|continua|continuar|continuemos|continuamos|seguimos|segui|sigamos|"
        r"podemos (?:seguir|continuar|retomar)|volvi|ya volvi|"
        r"(?:retoma|retomemos|continua|sigamos con) (?:el |este )?(?:borrador|pedido|ticket))",
    ),
    Intent.PRESENCE: (
        r"(?:(?:hola|buenas|hey|ey) )?(?:estas (?:ahi|aca|por ahi|disponible|escuchando)|"
        r"seguis ahi|estas aqui|hay alguien(?: ahi)?|me (?:escuchas|ois)|(?:podes|puedes) (?:oirme|escucharme)|"
        r"(?:te puedo|puedo) hablar|estas)",
    ),
    Intent.GREETING: (
        r"(?:hola|hola de nuevo|buenas|buen dia|buenos dias|buenas tardes|buenas noches|hey|ey)",
    ),
    Intent.WELLBEING: (r"(?:(?:hola|buenas) )?(?:como (?:estas|andas|te va)|que tal|todo bien)",),
    Intent.HELP: (
        r"(?:ayuda|ayudame|necesito (?:tu )?ayuda|(?:podes|puedes) ayudarme(?: con algo)?|"
        r"que (?:podes|puedes|sabes) hacer(?: por mi)?|en que (?:me )?(?:podes|puedes) ayudar|"
        r"que opciones (?:hay|tengo|tenes)|(?:mostrame|decime|explicame) (?:las )?opciones|"
        r"como (?:funcionas|se usa esto|te uso|hago (?:un|para crear un) ticket)|"
        r"(?:que|cuales) (?:son )?tus (?:funciones|capacidades)|necesito orientacion)",
    ),
    Intent.THANKS: (r"(?:muchas )?gracias(?: por (?:todo|tu ayuda|la ayuda))?|te agradezco",),
    Intent.APOLOGY: (r"(?:perdon|disculpa|disculpame|perdoname)(?: me equivoque)?|me equivoque",),
    Intent.ACK: (
        r"(?:lo |ya |ahora )?entendi|entendido|perfecto|bien|dale|ok|okay|de acuerdo|claro|buenisimo",
    ),
    Intent.REPEAT: (
        r"(?:repeti|repite|repetir|(?:podes|puedes) repetir(?:lo)?|"
        r"no (?:entendi|te entendi|escuche|te escuche)|que dijiste|como dijiste|otra vez)",
        r"(?:(?:podes|puedes) )?(?:repeti|repite|repetir) (?:la pregunta|las preguntas|la revision|las instrucciones|las opciones|eso|lo ultimo|lo que dijiste)",
    ),
    Intent.SLOWER: (
        r"(?:mas (?:despacio|lento)|(?:habla|hablame|podes hablar) mas (?:despacio|lento))",
    ),
    Intent.NEXT: (
        r"(?:que (?:te )?falta(?: para (?:terminar|enviar|registrar))?|"
        r"que (?:tengo que|debo) (?:decir|hacer)|que sigue|cual es el siguiente paso|"
        r"que necesitas(?: de mi)?|como seguimos)",
    ),
    Intent.PROGRESS: (
        r"(?:ya (?:lo )?(?:guardaste|enviaste|registraste|terminaste)|"
        r"(?:se )?(?:guardo|envio|registro)|como (?:va|vamos)|"
        r"que (?:paso|estas haciendo)|(?:cual es|decime) el resultado|"
        r"esta (?:guardado|enviado|registrado)|quedo (?:guardado|registrado))",
    ),
    Intent.FINISH: (
        r"(?:listo|ya esta|termine|termina|terminar|finaliza|finalizar|cerra|cierra|cerrar|"
        r"(?:termina|finaliza|cerra|cierra) (?:eso|todo|lo pendiente)|"
        r"(?:quiero|podemos) (?:terminar|finalizar|cerrar))",
    ),
}


def conversational_intent(text: str) -> Intent | None:
    # Explicit dictation prefixes/quotes remain untouched by this policy.
    if any(c in text for c in '"“”') or re.match(
        r"^(?:descripcion|motivo|nota|(?:correg[ií]|agreg[aá]|cambi[aá])\b)", text, re.I
    ):
        return None
    value = re.sub(r"[.,!¿?¡;:]+", " ", normalize(text))
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"^(?:(?:por favor|che|bueno) )+", "", value)
    value = re.sub(r" (?:por favor|si podes)$", "", value)
    values = [
        value,
        re.sub(r"^(?:hola|buenas|buenos dias|buenas tardes|buenas noches) ", "", value),
    ]
    for intent, patterns in PATTERNS.items():
        if any(re.fullmatch(pattern, v) for pattern in patterns for v in values):
            return intent
    return None


def terminal_ticket_request(text: str) -> bool:
    """An explicit, whole ticket instruction may switch from a saved draft.

    A verb inside a description cannot match. Resource-number ambiguity is still
    decided by the bounded number parser; this function never selects a ticket.
    """
    value = normalize(text).strip(" .,!¿?¡")
    words = "|".join([*NUMBER_WORDS, "o", "ticket", "numero", "terminacion"])
    number = rf"(?:idl[ -]?ti[ -]?\d{{1,6}}|\d{{1,6}}(?:\s+(?:y|o)\s+\d{{1,6}})?|(?:{words})(?:\s+(?:{words}|\d{{1,6}})){{0,8}})"
    return bool(
        re.fullmatch(
            rf"(?:por favor )?(?:(?:podes|puedes|quiero|necesito) )?"
            rf"(?:finaliza|finalizar|termina|terminar|cerra|cierra|cerrar|resuelve|resolve|resolver|soluciona|cancela|cancelar|marca|marcar) "
            rf"(?:el |este )?(?:ticket|pedido)(?: (?:numero|terminacion))?(?: {number})?(?: (?:como |a |en )?(?:resuelto|cancelado))?(?: por favor)?",
            value,
        )
    )


FIELD_PROMPTS = {
    "origin_unit_id": "¿De qué oficina, área o municipio viene el pedido?",
    "destination_unit_id": "¿Qué área debe recibir el pedido?",
    "problem_type_id": "¿Qué tipo de problema es?",
    "description": "Contame qué pasó y qué necesita el equipo.",
    "status": "¿A qué estado querés pasarlo?",
    "note": "Contame el motivo del cambio de estado; después te lo leo para confirmar.",
    "reason": "Contame el motivo; después te lo leo para confirmar.",
}


def missing_field(draft) -> str | None:
    if not draft or draft.transferred or draft.owner != "agent":
        return None
    p = draft.payload
    if draft.tool in {"tickets.create.v1", "tickets.update.v1"}:
        for field in ("origin_unit_id", "destination_unit_id", "problem_type_id", "description"):
            if not p.get(field) or (field == "description" and len(p[field]) < 10):
                return field
    elif draft.tool == "tickets.status.v1":
        return "status" if not p.get("status") else "note" if not p.get("note") else None
    elif draft.tool in {"tickets.archive.v1", "tickets.restore.v1"} and not p.get("reason"):
        return "reason"
    return None
