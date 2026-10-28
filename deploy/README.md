# PIC deployment (GCP, GKE Autopilot)

Operator guide for running the Purchasing Intelligence Cloud in production. Hosting follows Delivery Plan
DD-11: GCP **asia-south1 (Mumbai)** primary, **asia-south2 (Delhi)** DR, GKE + Secret Manager + Cloud KMS +
Cloud Armor, managed with Terraform.

```
deploy/
  terraform/   GCP foundation: APIs, VPC + Cloud NAT, GKE Autopilot, Secret Manager, KMS, Artifact Registry,
               static IP, SSL policy, Cloud Armor, External Secrets identity
  k8s/         Kustomize manifests (namespace pic): api, worker, web, config, secrets, network policy, ingress
  k8s/monitoring/servicemonitor.yaml   optional (prometheus-operator)
```

## 1. Architecture

```
 browser ──HTTPS──> Global external Application LB (static IP, Google-managed cert, TLS>=1.2)
                      │  Cloud Armor: per-IP rate-based ban (1200 req/min) + OWASP CRS (preview)
                      ▼
                 pic-web  (Next.js BFF, 2-6 pods, :3000)        ← only public workload
                      │  server-side http://pic-api:8080 (browser never calls the API)
                      ▼
                 pic-api  (FastAPI, 2-10 pods, :8080, ClusterIP) ──TLS :5432──> Neon PostgreSQL
                                                                  ──HTTPS :443──> ERP connectors / OTLP
                 pic-worker (same image, exactly 1 pod, no ports) ──> Neon, ERP
```

- Private nodes; all egress leaves through Cloud NAT with static IPs (`terraform output nat_ip_addresses`) that
  can be allow-listed on Neon and ERP firewalls.
- NetworkPolicy is default-deny (ingress and egress). Allowed: GFE ranges 35.191.0.0/16 and 130.211.0.0/22 →
  web:3000; web → api:8080; monitoring / gmp-system → api:8080; api and worker → 0.0.0.0/0 on 5432 and 443; DNS.
- Secrets live in Secret Manager (replicated in asia-south1 only), synced into the Kubernetes Secret
  `pic-secrets` by External Secrets Operator using Workload Identity. Kubernetes Secrets are additionally
  encrypted in etcd with a Cloud KMS key.
- Schema migrations are applied **only** by `.github/workflows/neon.yml` on `main`. There is no migration Job;
  `/readyz` returns 503 while the schema is behind the code, so new API pods take no traffic until the
  migration has run.
- The app's `PIC_RATE_LIMIT_*` limits are in-memory per API replica. Cloud Armor provides the global limit.

## 2. Why GKE Autopilot and not Cloud Run

| Need | GKE Autopilot | Cloud Run |
|---|---|---|
| Worker is a long-running loop with a heartbeat | Deployment, 1 replica, Recreate | needs CPU always allocated + min-instances 1, or a Cloud Run worker pool |
| `/v1/stream` is a long-lived SSE connection | LB timeout 3600 s, pods not throttled between requests | 60 min request cap; billed per open connection; CPU-throttled unless always-on |
| NetworkPolicy, PodDisruptionBudget, zone spread | native | not available (VPC egress controls only) |
| Ops overhead | nodes managed by Google, pay per pod request | lowest |

Cloud Run mapping if that decision is revisited: `pic-web` = public Cloud Run service behind the same external
LB + Cloud Armor (serverless NEG); `pic-api` = Cloud Run service with ingress "internal" and IAM-authenticated
invocation from the web service; `pic-worker` = Cloud Run worker pool (or a service with CPU always allocated,
min = max instances = 1); secrets via Secret Manager references; Direct VPC egress + Cloud NAT for static IPs.

## 3. Order of operations (first install)

Tools: `gcloud`, `terraform >= 1.6`, `kubectl`, `helm`, optionally `kustomize`.

1. **Terraform** (once per environment)
   ```sh
   cd deploy/terraform
   cp terraform.tfvars.example terraform.tfvars      # fill in project_id, github_owner, domain, CIDRs
   # optional: create the state bucket and uncomment backend.tf
   terraform init && terraform plan -out tfplan && terraform apply tfplan
   terraform output
   ```
2. **DNS**: create an A record for `domain` → `terraform output ingress_ip_address`.
3. **Secret values** (out-of-band; Terraform creates the secrets but never their values):
   ```sh
   for s in pic-database-url pic-jwt-secret pic-field-key pic-metrics-token; do
     read -rsp "$s: " V; echo
     printf '%s' "$V" | gcloud secrets versions add "$s" --project=<project-id> --data-file=-
     unset V
   done
   ```
   - `pic-field-key` and `pic-jwt-secret` must be **the same values** as the GitHub secrets used by `neon.yml`
     (fields encrypted by the migration/seed must be decryptable by the app). Never rotate `PIC_FIELD_KEY`
     without re-encrypting existing data.
   - `pic-database-url`: Neon connection string with `sslmode=require` for the application role. Check that
     max API replicas × pool size + worker stays within the Neon compute's connection limit.
   - `pic-metrics-token`: random, e.g. `openssl rand -hex 32`.
   - Optionally restrict Neon to the Cloud NAT IPs (Neon IP Allow).
4. **Cluster access**: `$(terraform output -raw get_credentials_command)` (your IP must be in
   `master_authorized_networks`, or run from inside the VPC).
5. **External Secrets Operator** (pin a current release; needs API `external-secrets.io/v1`, i.e. >= 0.16):
   ```sh
   helm repo add external-secrets https://charts.external-secrets.io
   helm install external-secrets external-secrets/external-secrets \
     -n external-secrets --create-namespace --version <pinned-version>
   ```
6. **Fill the manifest placeholders** (section 7), set the image tag, then:
   ```sh
   kubectl kustomize deploy/k8s | less            # review
   kubectl apply -k deploy/k8s
   kubectl -n pic get externalsecret pic-secrets  # STATUS SecretSynced
   kubectl -n pic rollout status deploy/pic-api deploy/pic-worker deploy/pic-web
   kubectl -n pic get managedcertificate pic-web  # Active after DNS resolves (15-60 min)
   curl -fsS https://<domain>/api/healthz
   ```
7. **Database**: migrations run from `.github/workflows/neon.yml` on every push to `main` touching `backend/`.
   API pods stay unready (`/readyz` 503) until it has succeeded.
8. **Images**: `.github/workflows/release.yml` builds `ghcr.io/<owner>/pic-api` and `ghcr.io/<owner>/pic-web`
   tagged with the commit SHA and `latest`. Deploy SHA tags (or digests), never `latest`. If GHCR packages are
   private, either make them public, add an `imagePullSecret`, or use the Artifact Registry remote repository
   (`terraform output ghcr_mirror_prefix`) with GHCR credentials.

## 4. Rolling out a new version

Wait until both `neon.yml` (migrations) and `release.yml` (images) have succeeded for the commit, then:

```sh
cd deploy/k8s
kustomize edit set image pic-api=ghcr.io/<owner>/pic-api:<sha>   # API + worker (same image)
kustomize edit set image pic-web=ghcr.io/<owner>/pic-web:<sha>
# without the kustomize binary: edit newTag in kustomization.yaml
git commit -am "deploy <sha>"   # keep git the source of truth
kubectl apply -k .
kubectl -n pic rollout status deploy/pic-api deploy/pic-worker deploy/pic-web
```

Emergency alternative (drifts from git until kustomization.yaml is updated):
```sh
kubectl -n pic set image deploy/pic-api    api=ghcr.io/<owner>/pic-api:<sha>
kubectl -n pic set image deploy/pic-worker worker=ghcr.io/<owner>/pic-api:<sha>
kubectl -n pic set image deploy/pic-web    web=ghcr.io/<owner>/pic-web:<sha>
```

API and web roll with `maxUnavailable: 0`. The worker uses `Recreate` (old pod stops before the new one
starts), a pause of a few seconds by design.

**Rollback**
```sh
kubectl -n pic rollout undo deploy/pic-api
kubectl -n pic rollout undo deploy/pic-worker
kubectl -n pic rollout undo deploy/pic-web
kubectl -n pic rollout history deploy/pic-api      # pick a revision: rollout undo ... --to-revision=N
```
Then set the previous tag in `kustomization.yaml`, otherwise the next `apply -k` re-deploys the bad one.
Rollback does not revert database migrations: migrations must stay backward compatible (expand, then contract)
so the previous image keeps working on the newer schema.

## 5. Operations notes

- **Worker**: exactly one replica. Two concurrent workers (including a RollingUpdate overlap) are not yet
  proven safe for timers and ERP retries. Do not scale it or add an HPA. Liveness runs
  `python -m app.pic.worker --check-heartbeat` (fails if `/tmp/pic-worker.heartbeat` is older than 60 s).
- **PIC_TRUSTED_PROXY_HOPS = 2** (GCLB + web BFF). Re-check if a proxy is added or removed in the chain.
- **Cloud Armor**: OWASP rules start in preview. Review `jsonPayload.previewSecurityPolicy` in the LB logs,
  add exclusions, then set `armor_waf_preview = false`.
- **Metrics**: `/metrics` needs `Authorization: Bearer <PIC_METRICS_TOKEN>`. Use
  `k8s/monitoring/servicemonitor.yaml` (prometheus-operator) or a Google Managed Prometheus `PodMonitoring`
  with the same bearer secret.
- **Filesystem**: all containers run as uid 10001 with a read-only root filesystem; writable emptyDirs are
  `/tmp` (all) and `/app/.next/cache` (web).
- **Pod Security**: namespace `pic` enforces the `restricted` Pod Security Standard.
- **DR**: this skeleton provisions only the primary region. The DR stack (asia-south2) is a second apply of the
  same Terraform with `region = dr_region`, plus a decision on the database's DR story.

## 6. Open decision: data residency (needs a business owner)

The current Neon project runs in **AWS ap-southeast-1 (Singapore)**, outside India. DD-11 places compute in
asia-south1 and Secret Manager / KMS are pinned to India, but **the procurement data itself is stored in
Singapore**. That may conflict with customer contracts or India DPDP Act cross-border transfer restrictions and
also adds about 30-60 ms per database round trip from Mumbai.

Options:
1. Move Neon to **AWS ap-south-1 (Mumbai)** (confirm region availability on your Neon plan): same product and
   workflows, `neon.yml` unchanged, data in India. Cross-cloud (GCP → AWS) traffic over the internet with TLS; requires a new Neon project and a
   one-off migration.
2. Move to **Cloud SQL for PostgreSQL or AlloyDB in asia-south1**: private IP inside the VPC, CMEK with the
   KMS key ring, cross-region replica in asia-south2 for DR. Requires replacing Neon branching in `neon.yml`.
3. Accept Singapore with a documented legal basis (contracts, DPDP assessment).

Until this is decided, treat the deployment as **not compliant with in-India data residency**.

## 7. Placeholders the operator must fill in

| Where | Placeholder | Value |
|---|---|---|
| `terraform/terraform.tfvars` | `project_id`, `github_owner`, `domain` | required, no defaults |
| `terraform/terraform.tfvars` | `master_authorized_networks` | office / CI / bastion CIDRs for kubectl |
| `terraform/backend.tf` | `<project-id>-pic-tfstate` | GCS state bucket (optional but recommended) |
| `k8s/kustomization.yaml` | `your-github-owner`, `replace-with-git-sha` | image owner and SHA tag (or AR mirror path) |
| `k8s/external-secret.yaml` | `your-gcp-project-id` (3x), `pic-eso-prod@...` | project id; `terraform output eso_gsa_email` |
| `k8s/external-secret.yaml` | `clusterName`, `clusterLocation` | `terraform output cluster_name` / `cluster_location` |
| `k8s/ingress.yaml` | `pic.example.com` (2x) | public hostname = `var.domain` |
| `k8s/ingress.yaml` | `pic-web-ip`, `pic-ssl-policy`, `pic-web-armor` | only if renamed in Terraform variables |
| `k8s/networkpolicies.yaml` | `monitoring`, `gmp-system` | namespace(s) of your Prometheus scraper |
| `k8s/monitoring/servicemonitor.yaml` | `release:` label | label your Prometheus selects on |
| `k8s/configmap.yaml` | `OTEL_EXPORTER_OTLP_ENDPOINT` | only when enabling tracing |
| Secret Manager | 4 secret versions | added out-of-band (section 3) |
| Helm | `<pinned-version>` | External Secrets Operator release |
| DNS | A record | `domain` → `ingress_ip_address` |
