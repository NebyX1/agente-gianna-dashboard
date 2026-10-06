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
HUNDREDS = {
    "doscientos": 200,
    "trescientos": 300,
    "cuatrocientos": 400,
    "quinientos": 500,
    "seiscientos": 600,
    "setecientos": 700,
    "ochocientos": 800,
    "novecientos": 900,
}
NUMBER_WORDS = {*SMALL, *TENS, *HUNDREDS, "cien", "ciento", "mil", "un", "y"}


def spoken_integer(text):
    words = normalize(text).split()
    if len(words) == 1 and words[0].isdecimal():
        return int(words[0])
    if len(words) <= 10 and words and all(w in ONES for w in words):
        return int("".join(str(ONES[w]) for w in words))
    if words.count("mil") == 1:
        before, after = " ".join(words).split("mil")
        thousands = 1 if before.strip() in {"", "un"} else spoken_integer(before)
        remainder = spoken_integer(after) if after.strip() else 0
        if (
            thousands is not None
            and 1 <= thousands <= 999
            and remainder is not None
            and 0 <= remainder <= 999
        ):
            return thousands * 1000 + remainder
        return None
    if words and words[0] in HUNDREDS | {"ciento": 100}:
        remainder = spoken_integer(" ".join(words[1:])) if len(words) > 1 else 0
        if remainder is not None and 0 <= remainder < 100 and (words[0] != "ciento" or remainder):
            return (HUNDREDS | {"ciento": 100})[words[0]] + remainder
        return None
    if words == ["cien"]:
        return 100
    if len(words) == 1:
        return SMALL.get(words[0], TENS.get(words[0]))
    if len(words) == 3 and words[0] in TENS and words[1] == "y" and words[2] in ONES:
        return TENS[words[0]] + ONES[words[2]]
    return None


def ticket_references(text):
    """Explicit public numbers; None records an ambiguous or malformed reference."""
    n = normalize(text)
    codes = re.findall(r"\b(?:idl[ -]?ti[ -]?)(\d{1,10})\b", n)
    label = r"(?:ticket|pedido)(?:\s+(?:numero|(?:con\s+)?terminacion))?|terminacion(?:\s+numero)?|numero"
    token = "|".join(sorted(NUMBER_WORDS | {"o"}, key=len, reverse=True))
    sequence = rf"(?:{token})(?:\s+(?:{token})){{0,9}}"
    matches = re.findall(rf"\b(?:{label})\s+(\d{{1,10}}\b|{sequence}(?!\w|\s+(?:{token})\b))", n)
    if re.search(rf"\b(?:{label})\s+\d+\s+(?:o|y)\s+(?:\d+|{token})\b", n):
        return {None}
    return {int(code) for code in codes} | {spoken_integer(m.removesuffix(" y")) for m in matches}


def ticket_number(text):
    values = ticket_references(text)
    return (
        next(iter(values)) if len(values) == 1 and None not in values and 0 not in values else None
    )
