"""Compose an instruction from address, consent, action and literal data.

This parser supplies meaning, never authority. The supervisor still checks the
current review, actor, resource, revision and receipt. Every word in an approval
must be accounted for; an unknown clause cannot be silently discarded.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from gianna.dialogue.activation import WAKE, normalize


def literal_input(text: str) -> bool:
    return any(c in text for c in '"“”') or bool(
        re.match(r"^\s*(?:descripci[oó]n|motivo|nota)\s*[:.]", text, re.I)
    )


def control_text(text: str) -> str:
    """Canonical form for instructions only; never store this as dictation."""
    value = normalize(WAKE.sub(" ", text))
    value = re.sub(r"[.,!¿?¡;:]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"^(?:(?:hola|che|bueno|buenas|oye|por favor) )+", "", value)
    value = re.sub(r" (?:por favor|si podes|si puedes)$", "", value)
    return value


def data_text(text: str) -> str:
    """Only remove an explicit leading vocative, retaining names in content."""
    if re.match(r"^\s*(?:descripci[oó]n|motivo|nota)\s*[:.]", text, re.I):
        return text
    return re.sub(
        rf"^\s*(?:(?:hola|buenas)\s*[,;:]?\s*)?{WAKE.pattern}\s*[,;:]\s*",
        "",
        text,
        count=1,
        flags=re.I,
    ).strip()


@dataclass(frozen=True)
class CreationRequest:
    content: str


def discard_request(text: str) -> bool:
    if literal_input(text):
        return False
    return bool(
        re.fullmatch(
            r"(?:(?:quiero|necesito|podemos|podes|puedes) (?:que )?)?"
            r"(?:descartar|descarta|descartes|eliminar|elimina|elimines|borrar|borra|borres) "
            r"(?:(?:el|este) )?borrador(?: de (?:este|el) pedido)?",
            control_text(text),
        )
    )


def creation_request(text: str) -> CreationRequest | None:
    """Split an anchored create instruction from its unchanged incident text."""
    value = data_text(text)
    prefix = re.match(
        r"^[¿¡]?\s*(?:(?:hola|buenas(?: tardes| noches)?|buenos d[ií]as|buen d[ií]a)[,;:. ]+)?(?:por favor[, ]+)?(?:yo\s+)?"
        r"(?:(?:quiero|necesito|preciso|quisiera|me gustar[ií]a|podemos|pod[eé]s|puedes|podr[ií]as)\s+"
        r"(?:que\s+)?(?:me\s+)?(?:ayudes?\s+a\s+|tu ayuda para\s+)?|ayudame a\s+)?"
        r"(?:registr[aá]r?|registres|cre[aá]r?|crees|abr[ií]r?|abras|hacer|hac[eé]|redactar|redact[aá]|redactes|escribir|escrib[ií]|escribas|anotar|anot[aá](?:me)?|anotes|ingresar|ingres[aá]|ingreses)\s+"
        r"(?:un[ao]?\s+|el\s+|la\s+|otr[oa]\s+)?(?:nuev[oa]\s+)?(?:ticket|pedido|solicitud|incidencia)"
        r"(?:\s+nuev[oa])?\b(?:\s+(?:por|para) m[ií])?(?:\s*[,;]?\s+por favor)?\s*[,;:.!?¿]*\s*(?:porque\s+|que es (?:un pedido|una solicitud)\s+)?",
        value,
        re.I,
    )
    return CreationRequest(value[prefix.end() :].strip()) if prefix else None


class Reply(StrEnum):
    APPROVE = "approve_review"
    CORRECT = "correct_review"
    DECLINE = "decline_review"
    HOLD = "hold_review"
    UNKNOWN = "unknown_review_reply"


@dataclass(frozen=True)
class ReviewReply:
    kind: Reply
    correction: str | None = None


_EDIT = re.compile(r"\b(?:correg[ií]|corrige|cambi[aá]|agreg[aá])\b", re.I)
_CORRECTION_PREFIX = re.compile(
    r"(?:(?:si|no|confirmo|dale|listo|eso es todo|registra|guardalo|envialo) )?"
    r"(?:(?:pero|aunque|antes|primero|mejor|en realidad)(?: primero)? )?"
)
_HOLD = re.compile(
    r"(?:no (?:lo )?(?:envies|mandes|guardes|registres|borres|ocultes)|"
    r"no (?:modifiques|cambies|toques) (?:nada|el borrador)(?: todavia)?|"
    r"(?:espera|esperame|aguarda|pausa)(?: un (?:momento|minuto|segundo))?|"
    r"(?:eso|esto) era para (?:la persona del telefono|otra persona))"
)

# These are composable clauses, rather than a whitelist of complete sentences.
# Weak acknowledgments alone never authorize a write.
_CLAUSES = [
    (
        r"(?:si|confirmo|confirmar|confirmamos|confirmado|autorizo|te confirmo)(?: (?:el pedido|el ticket|el cambio|(?:esta|la) operacion))?(?: que)?",
        "consent",
    ),
    (
        r"(?:eso|esto) (?:es|era) todo|no (?:tengo|hay) (?:nada mas|mas (?:datos|detalles))",
        "complete",
    ),
    (
        r"(?:todo )?(?:esta|quedo) (?:correcto|bien)(?: asi)?|esta revision es correcta|los datos (?:son|estan) correctos",
        "consent",
    ),
    (r"(?:dale|listo|perfecto|de acuerdo|bien|ahora|adelante)", "ack"),
    (r"(?:y|entonces)", "join"),
    (r"(?:por favor|si podes|si puedes)", "polite"),
]
_ACTION_PREFIX = r"(?:(?:podes|puedes|pod[eé]s|quiero que|te pido que) )?"
_ACTION_OBJECT = r"(?: (?:el|este|ese) (?:pedido|ticket|borrador|cambio))?"
_ACTIONS = {
    "tickets.create.v1": [r"registra(?:r)?(?:lo)?", r"crea(?:r)?(?:lo)?"],
    "tickets.update.v1": [r"actualiza(?:r)?(?:lo)?"],
    "tickets.archive.v1": [r"oculta(?:r)?(?:lo)?"],
    "tickets.restore.v1": [r"restaura(?:r)?(?:lo)?"],
}
_SUBJUNCTIVE = {
    "tickets.create.v1": ["registres", "crees"],
    "tickets.update.v1": ["actualices"],
    "tickets.archive.v1": ["ocultes"],
    "tickets.restore.v1": ["restaures"],
}


def review_reply(text: str, *, tool: str | None = None, status: str | None = None) -> ReviewReply:
    """Understand a response in the context of the operation being reviewed.

    Negation, uncertainty, a different action or leftover words block approval.
    Explicit corrections take priority over any affirmative preamble.
    """
    if literal_input(text):
        return ReviewReply(Reply.UNKNOWN)
    value = control_text(text)
    edit = _EDIT.search(text)
    if edit:
        prefix = control_text(text[: edit.start()])
        if not prefix or _CORRECTION_PREFIX.fullmatch(prefix + " "):
            remaining = text[edit.end() :].strip(" ,:.")
            if re.fullmatch(
                r"(?:la descripci[oó]n|(?:el )?(?:origen|destino|tipo)(?: a| por| es)?|que)?",
                remaining,
                re.I,
            ):
                return ReviewReply(Reply.DECLINE)
            return ReviewReply(Reply.CORRECT, text[edit.start() :].strip())
    field = re.search(
        r"\b(?:el )?(origen|destino|tipo)\s+(?:es|debe ser|tiene que ser)\s+(.+)", text, re.I
    )
    if field:
        prefix = control_text(text[: field.start()])
        if not prefix or _CORRECTION_PREFIX.fullmatch(prefix + " "):
            return ReviewReply(Reply.CORRECT, f"Cambiá el {field[1].lower()} a {field[2]}")
    if _HOLD.fullmatch(value) or re.fullmatch(
        r"(?:si|no|confirmo) (?:pero )?" + _HOLD.pattern, value
    ):
        return ReviewReply(Reply.HOLD)
    if re.fullmatch(
        r"no(?: es todo| todavia(?: no)?)?|todavia no|aun no|falta (?:algo|un dato|un detalle)",
        value,
    ):
        return ReviewReply(Reply.DECLINE)
    # Keep accent/punctuation: 'Si está correcto...' is a condition;
    # 'Sí, está correcto' answers the current question.
    if re.search(r"\bsi\s+(?:est[aá]|est[aá]n|es|son|queda|qued[oó])\b", WAKE.sub(" ", text), re.I):
        return ReviewReply(Reply.UNKNOWN)
    actions = list(_ACTIONS.get(tool, []))
    if tool is not None:
        actions += [
            r"guarda(?:r)?(?:lo)?",
            r"envia(?:r)?(?:lo)?",
            r"manda(?:r)?(?:lo)?",
            r"procede",
            r"hace(?:r)?(?:lo)?",
        ]
    if tool == "tickets.status.v1":
        labels = {
            "new": "nuevo",
            "in_progress": "en curso",
            "waiting": "en espera",
            "resolved": "resuelto",
            "cancelled": "cancelado",
        }
        if status in labels:
            actions.append(r"marca(?:r)?(?:lo)? (?:como |en )?" + labels[status])
        actions += (
            [
                r"resuelve(?:lo)?",
                r"resolve(?:r)?(?:lo)?",
                r"finaliza(?:lo)?",
                r"termina(?:lo)?",
                r"cerra(?:lo)?",
                r"cierra(?:lo)?",
            ]
            if status == "resolved"
            else [r"cancela(?:lo)?"]
            if status == "cancelled"
            else []
        )
    clauses = [(re.compile("(?:" + p + r")(?: |$)"), kind) for p, kind in _CLAUSES]
    clauses += [
        (re.compile(_ACTION_PREFIX + p + _ACTION_OBJECT + r"(?: |$)"), "action") for p in actions
    ]
    subjunctive = list(_SUBJUNCTIVE.get(tool, []))
    if tool:
        subjunctive += ["guardes", "envies", "mandes", "hagas", "procedas"]
    if tool == "tickets.status.v1":
        if status == "resolved":
            subjunctive += ["resuelvas", "finalices", "termines", "cierres"]
        elif status == "cancelled":
            subjunctive += ["canceles"]
    clauses += [
        (
            re.compile(r"(?:quiero que|te pido que) (?:lo )?" + p + _ACTION_OBJECT + r"(?: |$)"),
            "action",
        )
        for p in subjunctive
    ]
    kinds = []
    rest = value
    while rest:
        found = next(((p.match(rest), kind) for p, kind in clauses if p.match(rest)), None)
        if not found:
            return ReviewReply(Reply.UNKNOWN)
        match, kind = found
        kinds.append(kind)
        rest = rest[match.end() :].lstrip()
    if kinds and kinds[-1] == "join":
        return ReviewReply(Reply.UNKNOWN)
    if (
        "consent" in kinds
        or "action" in kinds
        or ("complete" in kinds and tool == "tickets.create.v1")
    ):
        return ReviewReply(Reply.APPROVE)
    return ReviewReply(Reply.UNKNOWN)
