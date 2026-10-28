# PIC on GCP - primary region stack (DD-11: asia-south1 Mumbai). The DR stack in var.dr_region (asia-south2
# Delhi) is not provisioned here yet; reuse this configuration with region = dr_region when DR is approved.

locals {
  labels = merge({
    app         = "pic"
    environment = var.environment
    managed-by  = "terraform"
  }, var.labels)

  name_prefix = "pic-${var.environment}"

  # Secret Manager secret ids consumed by deploy/k8s/external-secret.yaml.
  pic_secret_ids = toset([
    "pic-database-url",
    "pic-jwt-secret",
    "pic-field-key",
    "pic-metrics-token",
  ])

  # Cloud Armor preconfigured WAF rules (OWASP CRS 3.3) -> rule priority.
  waf_rules = {
    "sqli-v33-stable"              = 1000
    "xss-v33-stable"               = 1010
    "lfi-v33-stable"               = 1020
    "rfi-v33-stable"               = 1030
    "rce-v33-stable"               = 1040
    "methodenforcement-v33-stable" = 1050
    "scannerdetection-v33-stable"  = 1060
    "protocolattack-v33-stable"    = 1070
    "sessionfixation-v33-stable"   = 1080
    "nodejs-v33-stable"            = 1090
  }

  workload_pool = "${var.project_id}.svc.id.goog"
}

data "google_project" "this" {
  project_id = var.project_id
}

# ---- APIs ------------------------------------------------------------------------------------------------------

resource "google_project_service" "apis" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "cloudkms.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "container.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "secretmanager.googleapis.com",
    "sts.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ---- Network: dedicated VPC, private nodes, Cloud NAT with static egress IPs --------------------------------------

resource "google_compute_network" "pic" {
  name                    = local.name_prefix
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"

  depends_on = [google_project_service.apis]
}

resource "google_compute_subnetwork" "gke" {
  name                     = "${local.name_prefix}-gke"
  region                   = var.region
  network                  = google_compute_network.pic.id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = var.pods_cidr
  }

  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = var.services_cidr
  }

  log_config {
    aggregation_interval = "INTERVAL_5_MIN"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

resource "google_compute_router" "nat" {
  name    = "${local.name_prefix}-router"
  region  = var.region
  network = google_compute_network.pic.id
}

# Static egress IPs: private nodes reach Neon, GHCR and ERP endpoints only through these addresses, so they can
# be put on the Neon IP allow-list and on ERP firewalls.
resource "google_compute_address" "nat" {
  count = var.nat_ip_count

  name         = "${local.name_prefix}-nat-${count.index}"
  region       = var.region
  address_type = "EXTERNAL"

  depends_on = [google_project_service.apis]
}

resource "google_compute_router_nat" "nat" {
  name                               = "${local.name_prefix}-nat"
  router                             = google_compute_router.nat.name
  region                             = var.region
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = google_compute_address.nat[*].self_link
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  enable_dynamic_port_allocation      = true
  enable_endpoint_independent_mapping = false
  min_ports_per_vm                    = 64
  max_ports_per_vm                    = 4096

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# ---- Cloud KMS -------------------------------------------------------------------------------------------------
# Key rings and keys cannot be deleted in GCP (only their versions destroyed); prevent_destroy guards against
# accidental `terraform destroy` attempts that would orphan encrypted data.

resource "google_kms_key_ring" "pic" {
  name     = local.name_prefix
  location = var.region

  depends_on = [google_project_service.apis]
}

# KEK for future envelope encryption of PIC_FIELD_KEY (today PIC_FIELD_KEY is a static secret in Secret Manager;
# NEVER rotate it without re-encrypting existing field data).
resource "google_kms_crypto_key" "field_kek" {
  name            = "pic-field-kek"
  key_ring        = google_kms_key_ring.pic.id
  purpose         = "ENCRYPT_DECRYPT"
  rotation_period = "7776000s" # 90 days

  version_template {
    algorithm        = "GOOGLE_SYMMETRIC_ENCRYPTION"
    protection_level = "SOFTWARE" # HSM if required by policy
  }

  lifecycle {
    prevent_destroy = true
  }
}

# Application-layer encryption of Kubernetes Secrets in etcd (pic-secrets synced by External Secrets).
resource "google_kms_crypto_key" "gke_secrets" {
  name            = "gke-secrets"
  key_ring        = google_kms_key_ring.pic.id
  purpose         = "ENCRYPT_DECRYPT"
  rotation_period = "7776000s"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_kms_crypto_key_iam_member" "gke_secrets" {
  crypto_key_id = google_kms_crypto_key.gke_secrets.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.this.number}@container-engine-robot.iam.gserviceaccount.com"
}

# ---- Artifact Registry -----------------------------------------------------------------------------------------
# CI (.github/workflows/release.yml) pushes images to GHCR today. This optional REMOTE repository proxies ghcr.io
# so nodes pull from asia-south1 (cached, no GHCR rate limits, survives GHCR outages for cached tags).
# Image path: <region>-docker.pkg.dev/<project>/ghcr/<github_owner>/pic-api:<tag> (output ghcr_mirror_prefix).
# Private GHCR packages: store a GitHub PAT (read:packages) in Secret Manager, grant the Artifact Registry service
# agent (service-<project-number>@gcp-sa-artifactregistry.iam.gserviceaccount.com) secretAccessor on it, and set
# ghcr_username + ghcr_credentials_secret_version.

resource "google_artifact_registry_repository" "ghcr" {
  count = var.enable_ghcr_mirror ? 1 : 0

  location      = var.region
  repository_id = "ghcr"
  format        = "DOCKER"
  mode          = "REMOTE_REPOSITORY"
  description   = "Pull-through cache of ghcr.io/${var.github_owner} PIC images"

  remote_repository_config {
    description = "ghcr.io"

    docker_repository {
      custom_repository {
        uri = "https://ghcr.io"
      }
    }

    dynamic "upstream_credentials" {
      for_each = var.ghcr_credentials_secret_version == null ? [] : [1]
      content {
        username_password_credentials {
          username                = var.ghcr_username
          password_secret_version = var.ghcr_credentials_secret_version
        }
      }
    }
  }

  depends_on = [google_project_service.apis]
}

# ---- GKE Autopilot (regional, private nodes, Workload Identity) ---------------------------------------------------

resource "google_service_account" "gke_nodes" {
  account_id   = "${local.name_prefix}-gke-nodes"
  display_name = "PIC ${var.environment} GKE node service account (least privilege)"
}

resource "google_project_iam_member" "gke_nodes_default" {
  project = var.project_id
  role    = "roles/container.defaultNodeServiceAccount"
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}

resource "google_artifact_registry_repository_iam_member" "gke_nodes_ghcr" {
  count = var.enable_ghcr_mirror ? 1 : 0

  location   = google_artifact_registry_repository.ghcr[0].location
  repository = google_artifact_registry_repository.ghcr[0].name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.gke_nodes.email}"
}

resource "google_container_cluster" "pic" {
  name     = var.cluster_name
  location = var.region # regional = control plane and nodes across the region's zones

  enable_autopilot    = true
  deletion_protection = true

  network    = google_compute_network.pic.id
  subnetwork = google_compute_subnetwork.gke.id

  release_channel {
    channel = "REGULAR"
  }

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = var.enable_private_endpoint
    master_ipv4_cidr_block  = var.master_ipv4_cidr_block
  }

  # Empty list = no internet CIDR may reach the control plane (only the VPC). Add office/CI/bastion ranges.
  master_authorized_networks_config {
    gcp_public_cidrs_access_enabled = false

    dynamic "cidr_blocks" {
      for_each = var.master_authorized_networks
      content {
        cidr_block   = cidr_blocks.value.cidr_block
        display_name = cidr_blocks.value.display_name
      }
    }
  }

  # Always on in Autopilot; declared so the pool is explicit and referenced by the IAM binding below.
  workload_identity_config {
    workload_pool = local.workload_pool
  }

  database_encryption {
    state    = "ENCRYPTED"
    key_name = google_kms_crypto_key.gke_secrets.id
  }

  cluster_autoscaling {
    auto_provisioning_defaults {
      service_account = google_service_account.gke_nodes.email
      oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    }
  }

  # Weekend nights IST (Sat/Sun 02:00-08:00 IST = 20:30-02:30 UTC). GKE needs >= 48 h of windows per 32 days.
  maintenance_policy {
    recurring_window {
      start_time = "2026-01-02T20:30:00Z"
      end_time   = "2026-01-03T02:30:00Z"
      recurrence = "FREQ=WEEKLY;BYDAY=FR,SA"
    }
  }

  depends_on = [
    google_project_service.apis,
    google_kms_crypto_key_iam_member.gke_secrets,
    google_project_iam_member.gke_nodes_default,
  ]
}

# ---- Secret Manager (values are added out-of-band, never by Terraform) -----------------------------------------
# Replicated ONLY in var.region (India data residency). No google_secret_manager_secret_version resources on
# purpose: secret values must never land in Terraform state. Add each value once, e.g.
#   printf '%s' "$VALUE" | gcloud secrets versions add pic-database-url --project=<project-id> --data-file=-
# (read the value from a password manager / prompt; do not put it in shell history).

resource "google_secret_manager_secret" "pic" {
  for_each = local.pic_secret_ids

  secret_id = each.value

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.apis]
}

# ---- External Secrets Operator identity (Workload Identity) -------------------------------------------------------

resource "google_service_account" "eso" {
  account_id   = "pic-eso-${var.environment}"
  display_name = "PIC ${var.environment} External Secrets reader"
}

resource "google_secret_manager_secret_iam_member" "eso" {
  for_each = google_secret_manager_secret.pic

  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.eso.email}"
}

# KSA <namespace>/<eso_ksa_name> (deploy/k8s/external-secret.yaml) may act as the GSA above.
resource "google_service_account_iam_member" "eso_workload_identity" {
  service_account_id = google_service_account.eso.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${local.workload_pool}[${var.k8s_namespace}/${var.eso_ksa_name}]"

  depends_on = [google_container_cluster.pic] # the workload pool exists once the cluster does
}

# ---- Edge: static IP, TLS policy, Cloud Armor ---------------------------------------------------------------------

resource "google_compute_global_address" "ingress" {
  name         = var.ingress_ip_name
  address_type = "EXTERNAL"
  ip_version   = "IPV4"

  depends_on = [google_project_service.apis]
}

resource "google_compute_ssl_policy" "web" {
  name            = var.ssl_policy_name
  profile         = "MODERN"
  min_tls_version = "TLS_1_2"

  depends_on = [google_project_service.apis]
}

# Global edge protection for the public web. The app's PIC_RATE_LIMIT_* limits are in-memory per API replica;
# this policy is the cluster-wide per-IP limit.
resource "google_compute_security_policy" "web" {
  name        = var.armor_policy_name
  description = "PIC ${var.environment} web: per-IP rate-based ban + OWASP CRS"
  type        = "CLOUD_ARMOR"

  advanced_options_config {
    json_parsing = "STANDARD"
    log_level    = "NORMAL"
  }

  dynamic "adaptive_protection_config" {
    for_each = var.armor_adaptive_protection ? [1] : []
    content {
      layer_7_ddos_defense_config {
        enable = true
      }
    }
  }

  # Throttle each client IP above armor_rate_limit_per_minute (HTTP 429); an IP that keeps sending over-limit
  # requests (another full minute's budget within 10 min) is banned for armor_ban_duration_sec.
  rule {
    action      = "rate_based_ban"
    priority    = 100
    description = "Per-IP rate limit and ban"

    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }

    rate_limit_options {
      conform_action   = "allow"
      exceed_action    = "deny(429)"
      enforce_on_key   = "IP"
      ban_duration_sec = var.armor_ban_duration_sec

      rate_limit_threshold {
        count        = var.armor_rate_limit_per_minute
        interval_sec = 60
      }

      ban_threshold {
        count        = var.armor_rate_limit_per_minute
        interval_sec = 600
      }
    }
  }

  # OWASP CRS 3.3, sensitivity 1. Preview (log-only) by default: review "previewSecurityPolicy" entries in the
  # load balancer logs, add exclusions for false positives, then set armor_waf_preview = false.
  dynamic "rule" {
    for_each = local.waf_rules
    content {
      action      = "deny(403)"
      priority    = rule.value
      preview     = var.armor_waf_preview
      description = "OWASP CRS ${rule.key}"

      match {
        expr {
          expression = "evaluatePreconfiguredWaf('${rule.key}', {'sensitivity': 1})"
        }
      }
    }
  }

  rule {
    action      = "allow"
    priority    = 2147483647
    description = "Default allow"

    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
  }

  depends_on = [google_project_service.apis]
}
