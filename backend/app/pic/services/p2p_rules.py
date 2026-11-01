"""Access to the wave 1 procure-to-pay rules (platform/p2p_defaults.py).

A tenant bootstrapped by an earlier release has no row for these keys until ``reference.ensure_extensions`` runs; ``rule`` then
answers the built-in body as version ``builtin`` so the controls behave the same on every tenant. A tenant-edited rule always wins."""
import copy
from typing import Optional

from sqlalchemy.orm import Session

from app.pic.platform import p2p_defaults, rules
from app.pic.platform.errors import Problem


def rule(session: Session, key: str, **scope: Optional[str]) -> rules.Rule:
    try:
        return rules.resolve(session, key, **scope)
    except Problem as exc:
        if exc.code != "RULE_SET_MISSING" or key not in p2p_defaults.BODIES:
            raise
        return rules.Rule(key, "builtin", copy.deepcopy(p2p_defaults.BODIES[key][0]))
