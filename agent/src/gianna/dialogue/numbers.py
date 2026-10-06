"""Bounded Spanish number/code parser. Never infer an ID from free dictation."""

import re
from gianna.dialogue.activation import normalize

ONES = {
    "cero": 0,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
}
SMALL = {
    **ONES,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "veintiuno": 21,
    "veintidos": 22,
    "veintitres": 23,
    "veinticuatro": 24,
    "veinticinco": 25,
    "veintiseis": 26,
    "veintisiete": 27,
    "veintiocho": 28,
    "veintinueve": 29,
}
TENS = {
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
}


def spoken_integer(text):
    words = normalize(text).split()
    if len(words) <= 6 and words and all(w in ONES for w in words):
        return int("".join(str(ONES[w]) for w in words))
    if len(words) == 1:
        return SMALL.get(words[0], TENS.get(words[0]))
    if len(words) == 3 and words[0] in TENS and words[1] == "y" and words[2] in ONES:
        return TENS[words[0]] + ONES[words[2]]
    return None


def ticket_number(text):
    n = normalize(text)
    explicit = re.findall(r"\b(?:idl[ -]?ti[ -]?|(?:ticket|pedido)(?:\s+numero)?\s+)(\d{1,6})\b", n)
    if len(set(explicit)) > 1 or re.search(
        r"\b(?:ticket|pedido)(?:\s+numero)?\s+\d+\s+(?:o|y)\s+\d+\b", n
    ):
        return None
    code = re.search(r"\b(?:idl[ -]?ti[ -]?)(\d{1,6})\b", n)
    if code:
        return int(code[1]) or None
    match = re.search(r"\b(?:ticket|pedido)(?:\s+numero)?\s+(\d{1,6})\b", n)
    if match:
        return int(match[1]) or None
    token = "|".join([*SMALL, *TENS, "y"])
    sequence = rf"(?:{token})(?:\s+(?:{token})){{0,5}}"
    matches = re.findall(
        rf"\b(?:ticket|pedido)(?:\s+numero)?\s+({sequence})(?!\w|\s+(?:{token})\b)", n
    )
    values = {spoken_integer(m) for m in matches}
    return (
        next(iter(values)) if len(values) == 1 and None not in values and 0 not in values else None
    )
