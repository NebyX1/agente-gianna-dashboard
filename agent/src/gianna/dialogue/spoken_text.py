import re


TICKET_CODE = re.compile(r"\bIDL-TI-(\d{6,10})\b", re.I)


def code_number(code):
    """Public number, never a database resource ID."""
    match = TICKET_CODE.fullmatch(code)
    return int(match[1]) if match and int(match[1]) > 0 else None


def spoken_code(code):
    number = code_number(code)
    return f"número {number}" if number is not None else code


def accessible_ticket_text(text):
    """Use the same short reference in generated replies and workflow speech."""
    return TICKET_CODE.sub(lambda match: spoken_code(match[0]), text)


def review(draft, catalogs):
    def name(key, collection):
        return next(
            (r["name"] for r in catalogs[collection] if r["id"] == draft.payload.get(key)),
            "sin elegir",
        )

    p = draft.payload
    incident = ""
    if p.get("occurred_at"):
        from datetime import datetime

        date = datetime.fromisoformat(p["occurred_at"])
        offset = date.strftime("%z")
        incident = (
            f" Fecha del incidente: {date.day}/{date.month}/{date.year}, "
            f"a las {date.hour}:{date.minute:02d}, zona UTC {offset[:3]}:{offset[3:]}."
        )
    if draft.tool == "tickets.create.v1":
        return (
            f"Voy a registrar un pedido de {name('origin_unit_id', 'org_units')} para "
            f"{name('destination_unit_id', 'org_units')}. Tipo: {name('problem_type_id', 'problem_types')}. "
            f"Descripción: {p.get('description', '').rstrip('. ')}.{incident} ¿Confirmás que lo registre así?"
        )
    note = p.get("note") or p.get("reason") or p.get("description", "")
    action = {
        "update": "cambiar la descripción",
        "status": "cambiar el estado",
        "archive": "ocultar",
        "restore": "restaurar",
    }.get(draft.tool.split(".")[1], "actualizar")
    status = next((s["label"] for s in catalogs["statuses"] if s["code"] == p.get("status")), "")
    ticket = (
        "el ticket " + spoken_code(draft.display_code)
        if draft.display_code
        else "el ticket seleccionado"
    )
    operation = (
        f"pasar {ticket} a {status}"
        if status
        else f"{action} de {ticket}"
        if draft.tool == "tickets.update.v1"
        else f"{action} {ticket}"
    )
    preservation = (
        " Su registro e historia se conservan." if draft.tool == "tickets.archive.v1" else ""
    )
    detail = f" {note.rstrip('. ')}." if note else ""
    return f"Voy a {operation}.{detail}{incident}{preservation} ¿Confirmás esta operación?"
