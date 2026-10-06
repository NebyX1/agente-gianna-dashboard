from flask import g, jsonify


class APIError(Exception):
    def __init__(self, code, message, status=422, errors=None, details=None):
        self.code, self.message, self.status = code, message, status
        self.errors, self.details = errors or {}, details


def success(data, status=200):
    return jsonify(ok=True, data=data, meta={"request_id": g.request_id}), status


def failure(error):
    result = {"code": error.code, "message": error.message, "errors": error.errors}
    if error.details is not None:
        result["details"] = error.details
    return jsonify(ok=False, error=result, meta={"request_id": g.request_id}), error.status


def iso(value):
    return value.isoformat().replace("+00:00", "Z") if value else None
