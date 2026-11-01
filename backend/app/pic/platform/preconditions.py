"""ETag / If-Match for every mutable document (Technical Document §10.1, API-3).

Every tenant table has ``row_version`` (the ORM's version_id_col, bumped by each update). The HTTP layer opens a
``RequestState`` per /v1 request; a mapper ``load`` listener finds the *primary document* of the request (the first loaded row
whose number, code or id equals a path parameter) and

- on a GET of a document's own URL, ``etag`` becomes the ``ETag`` response header (``"<row_version>"``);
- on a write, an ``If-Match`` header is compared with the primary document's version the moment it is loaded (after the
  service has taken its row lock), and a mismatch is 412 STALE_WRITE: nobody overwrites a document they have not seen;
- routes in ``REQUIRED`` refuse a write without ``If-Match`` (428 PRECONDITION_REQUIRED) when PIC_REQUIRE_IF_MATCH is on
  (default: production). Elsewhere the header is optional, so scripts and tests keep working.

The older per-route ``core.check_if_match`` calls remain and agree with this check.
"""
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import event

from app.pic.config import get_settings
from app.pic.db import Base
from app.pic.platform.errors import Problem

# (method, route template) of commands that overwrite a document and therefore need If-Match when enforcement is on.
REQUIRED = {
    ("PATCH", "/v1/requisitions/{ref}/lines/{line_no}"),
    ("PUT", "/v1/purchase-orders/{ref}/lines/{line_no}/schedule"),
    ("POST", "/v1/purchase-orders/{ref}/versions"),
    ("POST", "/v1/purchase-orders/{ref}/resubmit"),
    ("PUT", "/v1/process-definitions/{key}/versions/{version}"),
    # M07 contract commands that change a signed-off document: nobody acts on a contract version they have not seen
    ("POST", "/v1/contracts/{ref}/submit"),
    ("POST", "/v1/contracts/{ref}/activate"),
    ("POST", "/v1/contracts/{ref}/terminate"),
    ("POST", "/v1/contracts/{ref}/index-resets"),
    ("POST", "/v1/contracts/{ref}/amendments"),
}
DETAIL_ROUTE = re.compile(r"^/v1/[a-z0-9-]+/\{[a-z_]+\}$")  # /v1/<collection>/{ref}: the document's own URL
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

STATE: ContextVar[Optional["RequestState"]] = ContextVar("pic_request_preconditions", default=None)


@dataclass
class RequestState:
    method: str
    scope: dict  # the ASGI scope: path_params and route are filled in once the router has matched
    if_match: Optional[str] = None
    version: Optional[int] = None
    seen: bool = False
    _checked: bool = field(default=False, repr=False)

    def params(self) -> tuple:
        return tuple(str(v) for v in (self.scope.get("path_params") or {}).values())

    def template(self) -> str:
        return getattr(self.scope.get("route"), "path", "") or ""

    @property
    def etag(self) -> Optional[str]:
        return f'"{self.version}"' if self.version is not None else None

    def is_detail_get(self) -> bool:
        return self.method == "GET" and bool(DETAIL_ROUTE.match(self.template()))


def parse(header: str) -> list[str]:
    """The entity tags of an If-Match header (``*`` stays ``*``); weak prefixes and quotes removed."""
    tags = []
    for part in header.split(","):
        part = part.strip()
        if part == "*":
            tags.append("*")
        elif part:
            tags.append(part.removeprefix("W/").strip().strip('"'))
    return tags


def _loaded(target, _context) -> None:
    state = STATE.get()
    if state is None or state.seen:
        return
    values = target.__dict__
    version = values.get("row_version")
    if version is None:
        return
    params = state.params()
    if not params:
        return
    ident = values.get("number") or values.get("code")
    if str(values.get("id")) not in params and (ident is None or str(ident) not in params):
        return
    state.seen = True
    state.version = version
    if state.method not in WRITE_METHODS:
        return
    if state.if_match is None:
        if (state.method, state.template()) in REQUIRED and get_settings().if_match_required:
            raise Problem(428, "PRECONDITION_REQUIRED",
                          f"Send 'If-Match: \"{version}\"' with the version you loaded (ETag of the document's GET)")
        return
    tags = parse(state.if_match)
    if "*" not in tags and str(version) not in tags:
        raise Problem(412, "STALE_WRITE",
                      f"The document is at version {version}; your If-Match is {', '.join(tags) or 'empty'}. Reload it and retry.")


_installed = False


def install() -> None:
    """Register the mapper listener once (idempotent)."""
    global _installed
    if not _installed:
        event.listen(Base, "load", _loaded, propagate=True)
        _installed = True


def open_request(method: str, scope: dict, if_match: Optional[str]) -> RequestState:
    install()
    return RequestState(method=method, scope=scope, if_match=if_match)
