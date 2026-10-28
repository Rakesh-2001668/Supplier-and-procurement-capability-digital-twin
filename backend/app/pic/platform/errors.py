"""RFC 9457 problem+json errors with business codes, rule references and trace ids."""
import uuid
from typing import Any, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError


class Problem(Exception):
    def __init__(self, status: int, code: str, detail: str, rule_ref: Optional[str] = None, **extra: Any):
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.rule_ref = rule_ref
        self.extra = extra


def not_found(object_type: str, ref: Any) -> Problem:
    return Problem(404, "NOT_FOUND", f"{object_type} {ref} not found")


def illegal_transition(object_type: str, ref: str, status: str, command: str) -> Problem:
    return Problem(409, "ILLEGAL_TRANSITION", f"{object_type} {ref} is {status}; '{command}' is not allowed from this state")


def rule_violation(detail: str, rule_ref: str, **extra: Any) -> Problem:
    return Problem(422, "RULE_VIOLATION", detail, rule_ref=rule_ref, **extra)


def _trace_id(request: Request) -> str:
    traceparent = request.headers.get("traceparent", "")
    if traceparent.count("-") >= 2:
        return traceparent.split("-")[1]
    return getattr(request.state, "request_id", None) or uuid.uuid4().hex


def _body(request: Request, status: int, code: str, detail: str, rule_ref: Optional[str] = None, extra: Optional[dict] = None) -> JSONResponse:
    content = {
        "type": f"https://errors.alphahelion.io/pic/{code}",
        "title": code,
        "status": status,
        "detail": detail,
        "code": code,
        "instance": str(request.url.path),
        "traceId": _trace_id(request),
    }
    if rule_ref:
        content["ruleRef"] = rule_ref
    if extra:
        content.update(extra)
    return JSONResponse(status_code=status, content=content, media_type="application/problem+json")


async def problem_handler(request: Request, exc: Problem):
    return _body(request, exc.status, exc.code, exc.detail, exc.rule_ref, exc.extra)


async def stale_handler(request: Request, exc: StaleDataError):
    return _body(request, 412, "STALE_WRITE", "The document was changed by someone else. Reload it and try again.")


async def integrity_handler(request: Request, exc: IntegrityError):
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    return _body(request, 409, "CONSTRAINT_VIOLATION", f"Database constraint {constraint or ''} rejected the change".strip(),
                 rule_ref=constraint)


def install(app) -> None:
    app.add_exception_handler(Problem, problem_handler)
    app.add_exception_handler(StaleDataError, stale_handler)
    app.add_exception_handler(IntegrityError, integrity_handler)
