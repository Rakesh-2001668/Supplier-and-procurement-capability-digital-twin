"""OpenID Connect single sign-on (authorization code + PKCE) against the tenant's identity provider (§14).

Configuration per tenant code (upper case), falling back to a generic set used by every tenant:
    PIC_OIDC_<TENANT>_ISSUER         e.g. https://login.microsoftonline.com/<tenant-id>/v2.0 or https://idp.example/realms/axion
    PIC_OIDC_<TENANT>_CLIENT_ID
    PIC_OIDC_<TENANT>_CLIENT_SECRET  optional (confidential client, sent as client_secret_post)
    PIC_OIDC_<TENANT>_REDIRECT_URI   the web app callback, e.g. https://pic.example.com/api/auth/oidc/callback
    PIC_OIDC_<TENANT>_SCOPES         optional, default "openid email profile"
    PIC_OIDC_ISSUER, PIC_OIDC_CLIENT_ID, ...  the same keys without a tenant code apply to all tenants

Flow: ``start`` returns the authorization URL. ``state`` is a short-lived signed value carrying the tenant and the nonce; the
PKCE verifier is derived from it with a server key, so it never leaves the platform. ``callback`` exchanges the code, validates the
ID token (RS256 signature against the provider's JWKS, iss, aud/azp, exp, iat, nonce), maps the verified e-mail to an active user of
that tenant (no auto-provisioning) and issues the normal PIC token. MFA performed at the identity provider (amr claim) counts.
"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.pic.config import get_settings
from app.pic.platform.auth import issue_challenge, read_challenge
from app.pic.platform.errors import Problem

STATE_PURPOSE = "oidc-state"
STATE_TTL_SECONDS = 600
CACHE_SECONDS = 3600
CLOCK_SKEW_SECONDS = 60
MFA_AMR = {"mfa", "otp", "hwk", "swk", "sc", "fpt", "face", "iris", "retina", "vbm", "sms", "tel", "pop"}
_cache: dict[str, tuple[float, dict]] = {}


@dataclass
class OidcConfig:
    issuer: str
    client_id: str
    client_secret: Optional[str]
    redirect_uri: str
    scopes: str


def config(tenant_code: str) -> Optional[OidcConfig]:
    code = "".join(ch for ch in (tenant_code or "").upper() if ch.isalnum() or ch == "_")

    def env(key: str) -> Optional[str]:
        return (os.environ.get(f"PIC_OIDC_{code}_{key}") if code else None) or os.environ.get(f"PIC_OIDC_{key}") or None

    issuer, client_id, redirect_uri = env("ISSUER"), env("CLIENT_ID"), env("REDIRECT_URI")
    if not (issuer and client_id and redirect_uri):
        return None
    return OidcConfig(issuer=issuer.rstrip("/"), client_id=client_id, client_secret=env("CLIENT_SECRET"), redirect_uri=redirect_uri,
                      scopes=env("SCOPES") or "openid email profile")


def require_config(tenant_code: str) -> OidcConfig:
    cfg = config(tenant_code)
    if cfg is None:
        raise Problem(404, "OIDC_NOT_CONFIGURED", f"Single sign-on is not configured for organisation {tenant_code}")
    return cfg


# ---------------------------------------------------------------- HTTP (tests replace _http)
def _http(method: str, url: str, data: Optional[dict] = None, headers: Optional[dict] = None) -> dict:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers={"accept": "application/json", **(headers or {})})
    if body is not None:
        request.add_header("content-type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - URLs come from operator configuration
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode() or "{}")
        except ValueError:
            detail = {}
        raise Problem(502, "OIDC_PROVIDER_ERROR", f"Identity provider answered {exc.code}: "
                      f"{detail.get('error_description') or detail.get('error') or exc.reason}")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise Problem(502, "OIDC_PROVIDER_UNREACHABLE", f"Identity provider not reachable: {exc}")


def _cached(url: str, refresh: bool = False) -> dict:
    hit = _cache.get(url)
    if hit and not refresh and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = _http("GET", url)
    _cache[url] = (time.time(), value)
    return value


def discovery(cfg: OidcConfig) -> dict:
    doc = _cached(f"{cfg.issuer}/.well-known/openid-configuration")
    if doc.get("issuer", "").rstrip("/") != cfg.issuer:
        raise Problem(502, "OIDC_DISCOVERY_MISMATCH", "The discovery document belongs to a different issuer")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not doc.get(key):
            raise Problem(502, "OIDC_DISCOVERY_INCOMPLETE", f"The discovery document has no {key}")
    return doc


# ---------------------------------------------------------------- helpers
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _verifier(jti: str) -> str:
    """PKCE code verifier (RFC 7636, 43 chars) derived from the state id with a server key."""
    return _b64url(hmac.new(get_settings().jwt_secret.encode(), f"pkce:{jti}".encode(), hashlib.sha256).digest())


def _challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode()).digest())


# ---------------------------------------------------------------- flow
def start(tenant) -> dict:
    cfg = require_config(tenant.code)
    doc = discovery(cfg)
    nonce = _b64url(os.urandom(18))
    state = issue_challenge(STATE_PURPOSE, {"tid": str(tenant.id), "tcode": tenant.code, "nonce": nonce}, STATE_TTL_SECONDS)
    jti = read_challenge(state, STATE_PURPOSE)["jti"]
    params = {"response_type": "code", "client_id": cfg.client_id, "redirect_uri": cfg.redirect_uri, "scope": cfg.scopes,
              "state": state, "nonce": nonce, "code_challenge": _challenge(_verifier(jti)), "code_challenge_method": "S256"}
    sep = "&" if "?" in doc["authorization_endpoint"] else "?"
    return {"authorizationUrl": f"{doc['authorization_endpoint']}{sep}{urllib.parse.urlencode(params)}", "state": state,
            "expiresIn": STATE_TTL_SECONDS}


def read_state(state: str) -> dict:
    return read_challenge(state, STATE_PURPOSE, code="OIDC_STATE_INVALID")


def _rsa_key(jwk: dict) -> rsa.RSAPublicKey:
    if jwk.get("kty") != "RSA":
        raise Problem(401, "OIDC_TOKEN_INVALID", "The signing key is not an RSA key")
    n = int.from_bytes(_b64url_decode(jwk["n"]), "big")
    e = int.from_bytes(_b64url_decode(jwk["e"]), "big")
    return rsa.RSAPublicNumbers(e, n).public_key()


def _signing_key(doc: dict, kid: Optional[str]) -> rsa.RSAPublicKey:
    for refresh in (False, True):  # unknown kid: the provider may have rotated keys, refetch once
        keys = [k for k in _cached(doc["jwks_uri"], refresh=refresh).get("keys", []) if k.get("use", "sig") == "sig"]
        match = [k for k in keys if kid is None or k.get("kid") == kid]
        if match:
            return _rsa_key(match[0])
    raise Problem(401, "OIDC_TOKEN_INVALID", "The ID token was signed with an unknown key")


def validate_id_token(cfg: OidcConfig, doc: dict, id_token: str, nonce: str, now: Optional[float] = None) -> dict:
    try:
        header_b64, payload_b64, signature_b64 = id_token.split(".")
        header = json.loads(_b64url_decode(header_b64))
        claims = json.loads(_b64url_decode(payload_b64))
        signature = _b64url_decode(signature_b64)
    except (ValueError, AttributeError):
        raise Problem(401, "OIDC_TOKEN_INVALID", "The ID token is malformed")
    if header.get("alg") != "RS256":
        raise Problem(401, "OIDC_TOKEN_INVALID", f"Unsupported ID token algorithm {header.get('alg')}; RS256 is required")
    key = _signing_key(doc, header.get("kid"))
    try:
        key.verify(signature, f"{header_b64}.{payload_b64}".encode(), padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        raise Problem(401, "OIDC_TOKEN_INVALID", "The ID token signature is not valid")
    now = time.time() if now is None else now
    if str(claims.get("iss", "")).rstrip("/") != cfg.issuer:
        raise Problem(401, "OIDC_TOKEN_INVALID", "The ID token was issued by a different provider")
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if cfg.client_id not in audiences:
        raise Problem(401, "OIDC_TOKEN_INVALID", "The ID token is not intended for this application (aud)")
    if len(audiences) > 1 and claims.get("azp") not in (None, cfg.client_id):
        raise Problem(401, "OIDC_TOKEN_INVALID", "The ID token authorised party (azp) is not this application")
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] + CLOCK_SKEW_SECONDS < now:
        raise Problem(401, "OIDC_TOKEN_EXPIRED", "The ID token has expired")
    if isinstance(claims.get("iat"), (int, float)) and claims["iat"] - CLOCK_SKEW_SECONDS > now:
        raise Problem(401, "OIDC_TOKEN_INVALID", "The ID token was issued in the future")
    if not nonce or not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise Problem(401, "OIDC_TOKEN_INVALID", "The ID token nonce does not match this sign-in")
    return claims


def exchange(tenant_code: str, code: str, state_claims: dict) -> dict:
    """Code → tokens → validated ID-token claims (with ``email`` and ``amr``)."""
    cfg = require_config(tenant_code)
    doc = discovery(cfg)
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": cfg.redirect_uri, "client_id": cfg.client_id,
            "code_verifier": _verifier(state_claims["jti"])}
    if cfg.client_secret:
        form["client_secret"] = cfg.client_secret
    tokens = _http("POST", doc["token_endpoint"], data=form)
    if not tokens.get("id_token"):
        raise Problem(502, "OIDC_PROVIDER_ERROR", "The identity provider returned no ID token")
    claims = validate_id_token(cfg, doc, tokens["id_token"], state_claims.get("nonce", ""))
    email = (claims.get("email") or claims.get("preferred_username") or claims.get("upn") or "").strip().lower()
    if "@" not in email:
        raise Problem(401, "OIDC_NO_EMAIL", "The identity provider did not return an e-mail address (scope email)")
    if claims.get("email_verified") is False:
        raise Problem(401, "OIDC_EMAIL_UNVERIFIED", "The e-mail address is not verified at the identity provider")
    amr = claims.get("amr") or []
    amr = [str(a) for a in (amr if isinstance(amr, list) else [amr])]
    return {"email": email, "subject": claims.get("sub"), "amr": amr, "mfa": bool(MFA_AMR & {a.lower() for a in amr}),
            "issuer": cfg.issuer}
