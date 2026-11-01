# Single sign-on through an identity broker (SAML and OIDC)

PIC verifies **OpenID Connect** (authorization code with PKCE, signed ID token, nonce, `platform/oidc.py`). It does not parse SAML
assertions itself: a SAML library needs `xmlsec` (a native dependency with a long vulnerability history) and a second signature-validation
path to maintain. Customers whose identity provider speaks only SAML (ADFS, Okta SAML apps, Ping) put **Keycloak** in front as a broker:
Keycloak speaks SAML to the customer's provider and OIDC to PIC.

```
 Employee ──► PIC web ──► Keycloak realm (OIDC provider for PIC) ──SAML──► customer IdP (ADFS / Okta / Entra)
                                  ▲
                                  └── PIC /v1/auth/oidc/callback verifies the Keycloak ID token (RS256, JWKS)
```

## Configuration

1. **Keycloak realm** (one per PIC tenant or one shared with a tenant claim): create realm `pic`.
2. **Identity provider** (Identity providers, Add provider, SAML v2.0): paste the customer IdP metadata; set *Principal type* to
   *Attribute (email)*; map the attributes `email`, `firstName`, `lastName`. Turn *Want AuthnRequests signed* and *Validate signature* on.
3. **Client for PIC** (Clients, Create): `Client ID` = `pic-web`, *Client authentication* on, *Standard flow* on, *PKCE method* `S256`,
   valid redirect URI `https://<pic-host>/api/auth/oidc/callback`, web origin `https://<pic-host>`.
4. **Roles**: PIC maps users by **e-mail** to existing PIC users (a user must exist and be active in the tenant; SSO never creates users or
   roles). Keep authorisation in PIC (Users and roles screen). An unverified e-mail (`email_verified=false`) is refused.
5. **Mappers** on the client: `email` (user attribute `email`), and optionally `amr` so PIC records how the user authenticated
   (`["pwd","otp"]` when the customer IdP did MFA). Set the realm *Access Token Lifespan* to 5 minutes; PIC issues its own session token.
6. **PIC configuration** (environment variables of the API; per tenant with the tenant code, or shared without it):
   `PIC_OIDC_<TENANT>_ISSUER` = `https://<keycloak>/realms/pic`, `PIC_OIDC_<TENANT>_CLIENT_ID` = `pic-web`,
   `PIC_OIDC_<TENANT>_CLIENT_SECRET` (from the secret manager, never in a file), `PIC_OIDC_<TENANT>_REDIRECT_URI` =
   `https://<pic-host>/api/auth/oidc/callback`, optional `PIC_OIDC_<TENANT>_SCOPES` (default `openid email profile`).
7. **Test**: `GET /v1/auth/oidc/<TENANT>` returns the configuration state; `GET /v1/auth/oidc/<TENANT>/start` returns the redirect.

## Operational notes

- Single logout is not propagated; PIC sessions end with their own expiry (`PIC_JWT_TTL_MINUTES`) or when the user is deactivated.
- When the customer provider enforces MFA, leave the PIC MFA rule `enforce` off for SSO users (the `amr` claim is honoured) and on for
  password sign-ins; with `enforce` on, an SSO session without `otp`/`mfa` in `amr` is asked to enrol a PIC authenticator.
- Test with `GET /v1/auth/oidc/<TENANT>` (discovery document) and `GET /v1/auth/oidc/<TENANT>/start`.
- Certificate rotation at the SAML provider is handled in Keycloak (re-import metadata); PIC only needs the Keycloak JWKS, which it
  refetches on key id changes.

## Why not native SAML

| | Native SAML in PIC | Keycloak broker |
|---|---|---|
| New dependency in the API image | `python3-saml` + `xmlsec` + libxml2 (native build) | none |
| Signature validation paths to keep secure | two (JWT and XML-DSig) | one |
| SAML features (artifact binding, encrypted assertions, SLO) | each implemented by us | provided by Keycloak |
| Other protocols later (LDAP, social, Azure AD) | each added | provided by Keycloak |
