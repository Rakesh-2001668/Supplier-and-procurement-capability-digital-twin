# PIC – Setting up e-mail sending and the public web address

Procedure for the two settings that organisation registration (phase 3 of the unified platform) needs before it can be switched on:
e-mail sending for verification, activation and decision e-mails, and the public web address used in the links of those e-mails.

Date: 11 November 2026. Written for: the AlphaHelion administrator who manages the `alphahelion.ai` domain, Microsoft 365 and Vercel.

Until both are set, registration stays switched off and nothing is sent. The platform already reads these settings; no code change is
needed when you add them.

## What the platform needs

| Setting (Vercel project `pic-api`, Production) | Example | Purpose |
|---|---|---|
| `PIC_SMTP_HOST` | `smtp-relay.brevo.com` or `smtp.office365.com` | Mail server that sends the e-mails |
| `PIC_SMTP_PORT` | `587` | Submission port (STARTTLS) |
| `PIC_SMTP_USER` | the SMTP login from the provider | |
| `PIC_SMTP_PASSWORD` | the SMTP key or app password | **Secret.** Enter it only in Vercel, never in chat, e-mail or the repository |
| `PIC_SMTP_FROM` | `AlphaHelion PIC <no-reply@alphahelion.ai>` | Sender shown to the recipient |
| `PIC_SMTP_STARTTLS` | `true` (default) | Encrypts the connection |
| `PIC_WEB_URL` | `https://app.alphahelion.ai` | Start of every link in the e-mails (activation, verification) |

## 1. E-mail sending

The `alphahelion.ai` domain receives its mail in **Microsoft 365** and its SPF record ends with `-all`: mail from any server not listed in
it is rejected as forged. So whichever way you choose, the sending server must be added to SPF, and DKIM must be set up for it.

### Option A (recommended): a transactional e-mail service

Verification and activation e-mails must arrive quickly and reliably, and are sent by a program, not a person. Services built for this
(Brevo, Amazon SES, SendGrid, Postmark, Zoho ZeptoMail) give delivery reports and do not depend on a user mailbox. Steps, shown for Brevo;
the others are equivalent:

1. Create an account for AlphaHelion at the service, with a company e-mail address.
2. **Add the sender domain** `alphahelion.ai` (Brevo: Senders, Domains & Dedicated IPs → Domains → Add a domain).
3. The service shows DNS records. Add them at your DNS provider (where `alphahelion.ai` is managed):
   - **DKIM**: usually one or two `CNAME` or `TXT` records such as `brevo1._domainkey.alphahelion.ai`.
   - **SPF**: change the existing TXT record, do not add a second one. It becomes
     `v=spf1 include:spf.protection.outlook.com include:spf.brevo.com -all`
     (the service tells you its exact `include:` value).
   - **DMARC** (if you have none yet): TXT record `_dmarc.alphahelion.ai` with `v=DMARC1; p=quarantine; rua=mailto:dmarc@alphahelion.ai`.
4. Wait until the service shows the domain as **authenticated** (minutes to a few hours after the DNS change).
5. Create the **sender** `no-reply@alphahelion.ai` with display name "AlphaHelion PIC".
6. Create an **SMTP key** (Brevo: SMTP & API → SMTP → Generate a new SMTP key). Note the server, port and login shown on that page.
7. Put the values into Vercel (section 3). The key is shown once; paste it straight into Vercel.

### Option B: a Microsoft 365 mailbox

Possible only if your Microsoft 365 administrator can allow password-based SMTP sending (SMTP AUTH) for one mailbox. Microsoft has been
retiring this kind of sign-in for Exchange Online, and tenants with "security defaults" block it, so check with your administrator first.
If it is not available, use option A.

1. In the Microsoft 365 admin centre create a mailbox (or shared mailbox with a licence) `no-reply@alphahelion.ai`.
2. Exchange admin centre → Recipients → Mailboxes → the mailbox → Manage e-mail apps → turn on **Authenticated SMTP**.
3. Make sure the organisation-wide setting allows SMTP AUTH for this mailbox and no conditional-access policy blocks it.
4. If the mailbox has multi-factor sign-in, create an **app password** for it; otherwise use its password.
5. Settings: host `smtp.office365.com`, port `587`, STARTTLS `true`, user `no-reply@alphahelion.ai`, password as above.
6. SPF already covers Microsoft 365. Turn on **DKIM** for `alphahelion.ai` in Microsoft Defender → E-mail authentication settings → DKIM.

### Check the e-mail settings

After section 3, the administrator invites a test user in the platform (Administration → Users & roles → Invite). The invitation e-mail
must arrive within a minute, show the sender `no-reply@alphahelion.ai`, and its header must show `spf=pass`, `dkim=pass` and `dmarc=pass`
(in Outlook: open the message → … → View → View message details; in Gmail: … → Show original).

## 2. Public web address

This is the address people type to reach the platform, and the start of every link in the e-mails. Use your own domain so the links
look trustworthy; the `vercel.app` address works too but looks like a test site.

1. Choose the address, for example `app.alphahelion.ai` (or `pic.alphahelion.ai`).
2. Vercel → the **web** project (`pic-web`) → Settings → Domains → **Add** → enter the address.
3. Vercel shows one DNS record. At your DNS provider add it, normally a `CNAME` from `app` to `cname.vercel-dns.com`.
4. Wait until Vercel shows the domain as **Valid Configuration** and has issued the certificate (padlock; usually minutes).
5. Open `https://app.alphahelion.ai`: the sign-in page must appear.

## 3. Enter the settings in Vercel

1. Vercel → the **API** project (`pic-api`) → Settings → Environment Variables.
2. Add each variable from the table at the top for the **Production** environment. Tick "Sensitive" for `PIC_SMTP_PASSWORD`.
3. Set `PIC_WEB_URL` to the address from section 2, with `https://` and without a trailing slash.
4. Deployments → the latest production deployment → … → **Redeploy**, so the new values are used.
5. Tell the implementation team "e-mail and web address are set" (no values needed). We then run the check in section 1 and switch
   registration on.

Nothing needs to be added to GitHub for this: the GitHub jobs (tests, Neon migration) do not send e-mail.

## 4. Create the platform operator account

The platform operator reviews registration requests at `https://<web address>/pic/platform/registrations`. The account belongs to the
platform's own organisation (code `AHPLATFORM`, created automatically) and always signs in with two-step verification.

Run once, after release 0030 is on Neon and after section 3, on a computer with the repository and `backend\.env` (the production
connection), from the `backend` folder:

```powershell
.\venv\Scripts\python.exe -m app.pic.tools.tenant_admin create-operator --email appuas@gmail.com --name "Appusamy"
```

The command prints a single-use activation link (valid 72 hours) and, with e-mail set up, also e-mails it to the operator. Give the link
only to the operator. The operator opens it, sets a password, signs in at `/signin` and registers an authenticator app (Microsoft
Authenticator, Google Authenticator or similar) at the first sign-in. More operators: run the command again with their e-mail.

## 5. What is already decided for phase 3

| Item | Decision |
|---|---|
| Platform operator | Appusamy (`appuas@gmail.com`). Gets a platform-operator account with mandatory two-step verification (authenticator app). |
| Organisation e-mail used to register | The company's **shared mailbox** on its **own domain**, for buyers and suppliers, for example `purchase@trichyforge.com`. Accepted mailbox names (rule, can be extended): info, contact, sales, accounts, purchase, procurement, admin, finance, office, enquiry, enquiries, support, operations, business, vendor, supply. Free e-mail domains (gmail.com, outlook.com, yahoo.com and similar) are refused. Verification and decision e-mails go to this mailbox. |
| First administrator | A **named person** with a personal work e-mail on the **same company domain** (for example `rakesh.annamalai@trichyforge.com`). This is the sign-in account: own password, own two-step verification, own audit trail. The shared mailbox is never a sign-in account. |
