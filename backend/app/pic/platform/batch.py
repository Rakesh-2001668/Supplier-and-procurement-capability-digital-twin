"""Per-call read cache for batch operations (payment proposal and run over hundreds of invoices).

Inside ``with batch.reading(session):`` the hot read-only lookups that every invoice repeats (the effective rule set of a key and scope,
the user's ABAC attributes, the SoD rules and what the actor already did) are answered once and remembered until the block ends. Nothing
outside the block is cached, and ``forget`` drops one entry when the block itself changes it (a recorded SoD action). The cache lives in
``session.info``, so it is private to one request/transaction.
"""
from contextlib import contextmanager
from typing import Any, Callable

KEY = "batch_memo"


@contextmanager
def reading(session):
    outer = session.info.get(KEY)
    if outer is None:
        session.info[KEY] = {}
    try:
        yield
    finally:
        if outer is None:
            session.info.pop(KEY, None)


def _cache(session):
    info = getattr(session, "info", None)   # a stand-in session of a unit test has none
    return None if info is None else info.get(KEY)


def active(session) -> bool:
    return _cache(session) is not None


def memo(session, key: Any, make: Callable[[], Any]) -> Any:
    cache = _cache(session)
    if cache is None:
        return make()
    if key not in cache:
        cache[key] = make()
    return cache[key]


def peek(session, key: Any) -> Any:
    cache = _cache(session)
    return None if cache is None else cache.get(key)


def forget(session, key: Any) -> None:
    cache = _cache(session)
    if cache is not None:
        cache.pop(key, None)
