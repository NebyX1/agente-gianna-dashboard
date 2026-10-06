import re
from difflib import SequenceMatcher
from gianna.dialogue.activation import normalize


def _names(row, aliases):
    return [row["name"], *aliases.get(row["code"], [])]


def _fuzzy(text, name):
    """Tolerate small speech-recognition slips ('urbanizmo', 'transitto')."""
    target = re.sub(r"\([^)]*\)", " ", normalize(name)).split()
    words = re.findall(r"\w+", text)
    size = len(target)
    if not size or len("".join(target)) < 5:
        return False
    wanted = " ".join(target)
    return any(
        SequenceMatcher(None, " ".join(words[i : i + size]), wanted).ratio() >= 0.86
        for i in range(len(words) - size + 1)
    )


def matches(text, rows, aliases):
    text = normalize(text)
    found = []
    for row in rows:
        names = _names(row, aliases)
        if any(re.search(r"(?<!\w)" + re.escape(normalize(n)) + r"(?!\w)", text) for n in names):
            found.append(row)
    if found:
        return found
    return [row for row in rows if any(_fuzzy(text, n) for n in _names(row, aliases))]


def catalogue_answer(text, rows, aliases):
    """An entire short answer, rather than a catalogue word inside a narrative."""
    value = normalize(text).strip(" .,!¿?¡")
    value = re.sub(r" (?:por favor|si podes)$", "", value)
    value = re.sub(
        r"^(?:(?:es un problema de|el tipo es|el origen es|el destino es|"
        r"viene de|es de|desde|de|es|son) )?(?:(?:la direccion de|el area de|"
        r"la oficina de|la|el|las|los) )?",
        "",
        value,
    )
    return any(
        value == normalize(name)
        or (len(value) >= 5 and SequenceMatcher(None, value, normalize(name)).ratio() >= 0.9)
        for row in rows
        for name in _names(row, aliases)
    )


async def resolve(text, rows, aliases, tev, field):
    found = matches(text, rows, aliases)
    if len(found) == 1:
        return found[0]["id"]
    if len(found) > 1 or len(rows) > 22:
        return None
    candidates = {
        f"id_{r['id']}": r["name"]
        + (
            " (" + ", ".join(aliases.get(r["code"], [])[:4]) + ")"
            if field == "problem_type_id" and aliases.get(r["code"])
            else ""
        )
        for r in rows
    }
    candidates.update(
        {"clarify": "No identifica una opción inequívoca", "ignore": "No hay dato para este campo"}
    )
    context = (
        "Clasificar el tipo de problema por los síntomas del incidente. No exigir que aparezca el nombre exacto de la categoría; puede haber errores de escritura del reconocimiento de voz. Elegir sólo entre las categorías indicadas. Si no hay información o hay más de un problema sin un tipo inequívoco, clarify. No inventar datos."
        if field == "problem_type_id"
        else f"Seleccionar {field} sólo si el texto lo identifica. No inventar."
    )
    choice = await tev.choose(text, candidates, context)
    return int(choice[3:]) if choice in candidates and choice.startswith("id_") else None
