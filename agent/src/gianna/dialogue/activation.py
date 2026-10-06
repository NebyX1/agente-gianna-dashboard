import re
import unicodedata

# Whisper renders the name in many ways: Gianna, Giana, Yana, Yanna, Jiana, Iana...
WAKE = re.compile(r"\b(?:gi+an+a|[yj]i?an+a|s?ian+a)\b", re.I)
# The name must be a vocative: at the start or the end of the utterance.
EDGE_CHARS = 28

ACTIVATION_CRITERIA = {
    "invoke": "La persona le habla directamente a Gianna: la saluda, pregunta si esta ahi o le pide algo",
    "mention": "Habla SOBRE Gianna con otra persona, sin hablarle a Gianna",
    "ignore": "Conversacion ajena, no llama a la asistente",
    "clarify": "No esta claro a quien le habla",
}


def normalize(text):
    return "".join(
        c for c in unicodedata.normalize("NFD", text.casefold()) if unicodedata.category(c) != "Mn"
    )


def candidate(text):
    matches = list(WAKE.finditer(text))
    match = next(
        (m for m in matches if m.start() <= EDGE_CHARS or len(text) - m.end() <= EDGE_CHARS), None
    )
    if not match:
        return None
    # Reject descriptive mentions deterministically before consulting the model.
    prefix = normalize(text[: match.start()])
    if re.search(
        r"(?:se llama|nombre(?: de [^,.]{1,40})? es|llamada|dijo|me dijeron|mencionaron|hablo de|"
        r"(?:decile|dile|avisale|avisa) a|(?:hablando|hablabas?|hable) con|la usuaria|la operadora)\s*$",
        prefix,
    ):
        return None
    return text[: match.start()] + text[match.end() :]
