"""Stable failure codes and actionable local responses; never imply a business commit."""

from enum import StrEnum


class ErrorCode(StrEnum):
    AUDIO = "audio_unavailable"
    STT = "stt_unavailable"
    TTS = "tts_unavailable"
    DECISION = "decision_unavailable"
    CLARIFICATION = "clarification_required"
    AUTH = "authentication_required"
    PERMISSION = "permission_denied"
    VALIDATION = "validation_error"
    VERSION = "version_conflict"
    IDEMPOTENCY = "idempotency_conflict"
    RATE = "rate_limited"
    UI = "ui_contract_changed"
    DEADLINE = "deadline_exceeded"
    UNKNOWN = "commit_outcome_unknown"
    UNSUPPORTED = "unsupported_capability"
    API = "tickets_unavailable"


MESSAGES = {
    ErrorCode.AUDIO: "Se interrumpió el audio. Conservé el borrador; reconectá el micrófono.",
    ErrorCode.STT: "Falló el reconocimiento local. Conservé el borrador; revisá Whisper en el diagnóstico y reiniciá Gianna.",
    ErrorCode.TTS: "No pude reproducir esa respuesta. Podés seguir hablando o leyendo el chat; tu pedido se conserva.",
    ErrorCode.DECISION: "No pude interpretar esa orden con el motor local. Repetila de forma más concreta.",
    ErrorCode.CLARIFICATION: "Necesito que aclares el dato antes de seguir.",
    ErrorCode.AUTH: "La sesión venció o cambió. Iniciá sesión en tickets con tu código de verificación.",
    ErrorCode.PERMISSION: "Tu cuenta no tiene permiso para esa acción. Conservé el borrador sin enviarlo.",
    ErrorCode.VALIDATION: "Hay datos que no cumplen el contrato. Revisá el borrador; no lo envié.",
    ErrorCode.VERSION: "El ticket cambió. Hay que leer la versión actual y revisar el cambio antes de otro envío.",
    ErrorCode.IDEMPOTENCY: "La identidad del intento entró en conflicto. Conservé el borrador y el comprobante; no envié otra operación.",
    ErrorCode.RATE: "El sistema limitó las solicitudes. Conservé el borrador; esperá y pedime revisarlo de nuevo.",
    ErrorCode.UI: "La pantalla de tickets cambió o se cerró. Revisá el navegador; conservé el borrador.",
    ErrorCode.DEADLINE: "La consulta excedió su plazo. Conservé el borrador; podés repetir la consulta.",
    ErrorCode.UNKNOWN: "No tengo un resultado confirmado. Voy a comprobar el recibo antes de cualquier otro envío.",
    ErrorCode.UNSUPPORTED: "No hay una herramienta disponible para esa acción en este perfil.",
    ErrorCode.API: "No pude conectar con el sistema de tickets. Conservé el borrador; revisá su conexión.",
}


def classify(exc):
    import httpx
    from jsonschema import ValidationError
    from gianna.adapters.tickets_http import TicketError
    from gianna.adapters.playwright_browser import BrowserContractError

    if isinstance(exc, TicketError):
        if exc.status == 409:
            return (
                ErrorCode.IDEMPOTENCY
                if "idempot" in exc.code or "operation" in exc.code
                else ErrorCode.VERSION
            )
        return {
            401: ErrorCode.AUTH,
            403: ErrorCode.PERMISSION,
            422: ErrorCode.VALIDATION,
            429: ErrorCode.RATE,
        }.get(exc.status, ErrorCode.API)
    if isinstance(exc, BrowserContractError):
        return ErrorCode.UI
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return ErrorCode.DEADLINE
    if isinstance(exc, httpx.HTTPError):
        return ErrorCode.API
    if isinstance(exc, ValidationError):
        return ErrorCode.VALIDATION
    return {
        "permission_denied": ErrorCode.PERMISSION,
        "tool_unavailable": ErrorCode.UNSUPPORTED,
        "tool_not_in_profile": ErrorCode.UNSUPPORTED,
        "tool_budget_exhausted": ErrorCode.DEADLINE,
        "outcome_unknown": ErrorCode.UNKNOWN,
        "invalid_receipt": ErrorCode.UNKNOWN,
        "invalid_receipt_schema": ErrorCode.UNKNOWN,
    }.get(str(exc), ErrorCode.VALIDATION)
