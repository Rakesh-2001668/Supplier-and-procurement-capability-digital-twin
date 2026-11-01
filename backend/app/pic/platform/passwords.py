"""Password policy (OWASP ASVS 2.1): length, complexity and an offline breached/common-password check.

Used for supplier self-registration (services/invitations.py) and password change (POST /v1/me/password). The list in
``common_passwords.txt`` is bundled with the code: nothing is sent to a third party, and an operator can extend it by appending
lines. A password is refused when, after lower-casing and undoing the usual substitutions (@ -> a, 0 -> o, 1 -> l, 3 -> e, 5 -> s,
$ -> s, 7 -> t), it is a listed password, a listed password plus trailing digits/symbols ("Password2026!"), or a keyboard/
sequence/repeat pattern.
"""
import re
from functools import lru_cache
from pathlib import Path

MIN_LENGTH = 12
MAX_LENGTH = 128
LEET = str.maketrans({"@": "a", "0": "o", "1": "l", "3": "e", "5": "s", "$": "s", "7": "t", "4": "a", "!": "i"})
SEQUENCES = ("abcdefghijklmnopqrstuvwxyz", "0123456789", "qwertyuiopasdfghjklzxcvbnm", "qazwsxedcrfvtgbyhnujmikolp")


@lru_cache(maxsize=1)
def common() -> frozenset:
    words = set()
    for line in Path(__file__).with_name("common_passwords.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#"):
            words.add(line)
            words.add(line.translate(LEET))
    return frozenset(words)


def _stems(password: str) -> set:
    lowered = password.lower()
    forms = {lowered, lowered.translate(LEET)}
    for form in list(forms):
        forms.add(re.sub(r"[^a-z]+$", "", form))                 # trailing digits / symbols
        forms.add(re.sub(r"^[^a-z]{1,2}", "", form))             # one or two leading digits / symbols
        forms.add(re.sub(r"^[^a-z]{1,2}|[^a-z]+$", "", form))
    return {f for f in forms if len(f) >= 4}


def is_common(password: str) -> bool:
    words = common()
    return any(form in words for form in _stems(password))


def _pattern(password: str) -> bool:
    lowered = password.lower()
    if len(set(lowered)) <= 2:
        return True  # "aaaaaaaaaaaa", "abababababab"
    for sequence in SEQUENCES:
        for chunk in (sequence, sequence[::-1]):
            if lowered in chunk or (len(lowered) >= 8 and any(lowered[i:i + 8] in chunk for i in range(len(lowered) - 7))
                                    and len(set(lowered)) <= 12):
                return True
    return False


def check(password: str, *, email: str = "", names: tuple = ()) -> list:
    """Reasons the password is refused (empty list: acceptable). ``names`` are words the password must not contain (the user's
    name, the company)."""
    password = password or ""
    problems = []
    if len(password) < MIN_LENGTH:
        problems.append(f"password must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        problems.append(f"password must be at most {MAX_LENGTH} characters")
    classes = sum(bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
    if classes < 3:
        problems.append("password must mix at least three of: lower-case, upper-case, digits, symbols")
    lowered = password.lower()
    local = email.split("@", 1)[0].lower()
    if len(local) >= 4 and local in lowered:
        problems.append("password must not contain your e-mail name")
    words = [w for name in names for w in re.split(r"[^a-z0-9]+", (name or "").lower()) if len(w) >= 4 and w not in ("private", "limited", "india")]
    if any(w in lowered for w in words):
        problems.append("password must not contain your name or company name")
    if is_common(password):
        problems.append("password is too common or appears in known breaches")
    elif _pattern(password):
        problems.append("password is a keyboard sequence or repeated characters")
    return problems
