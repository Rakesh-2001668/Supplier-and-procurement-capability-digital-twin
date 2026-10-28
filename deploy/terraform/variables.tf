variable "project_id" {
  description = "GCP project id that hosts PIC (no default on purpose)."
  type        = string
}

variable "region" {
  description = "Primary region (Delivery Plan DD-11: Mumbai). Secrets, KMS and the cluster live here."
  type        = string
  default     = "asia-south1"
}

variable "dr_region" {
  description = "Disaster-recovery region (DD-11: Delhi). Not provisioned by this skeleton yet; reserved for the DR stack."
  type        = string
  default     = "asia-south2"
}

variable "environment" {
  description = "Environment name used in labels and resource names (e.g. prod, staging)."
  type        = string
  default     = "prod"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,15}$", var.environment))
    error_message = "environment must be lowercase letters, digits or dashes (2-16 chars)."
  }
}

variable "github_owner" {
  description = "GitHub owner/org that publishes ghcr.io/<owner>/pic-api and pic-web (lowercase)."
  type        = string
}

variable "cluster_name" {
  description = "GKE Autopilot cluster name. Must match clusterName in deploy/k8s/external-secret.yaml."
  type        = string
  default     = "pic-prod"
}

variable "domain" {
  description = "Public hostname of the web app (e.g. pic.example.com). Must match deploy/k8s/ingress.yaml."
  type        = string
}

variable "k8s_namespace" {
  description = "Kubernetes namespace of the PIC workloads."
  type        = string
  default     = "pic"
}

variable "eso_ksa_name" {
  description = "Kubernetes service account used by External Secrets Operator's SecretStore (external-secret.yaml)."
  type        = string
  default     = "pic-external-secrets"
}

# ---- Network ---------------------------------------------------------------------------------------------------

variable "subnet_cidr" {
  description = "Primary range of the GKE node subnet."
  type        = string
  default     = "10.10.0.0/20"
}

variable "pods_cidr" {
  description = "Secondary range for pods (Autopilot recommends /17 or larger)."
  type        = string
  default     = "10.16.0.0/14"
}

variable "services_cidr" {
  description = "Secondary range for Services."
  type        = string
  default     = "10.20.0.0/20"
}

variable "master_ipv4_cidr_block" {
  description = "Optional /28 for a VPC-peered control plane. null = Private Service Connect control plane (GKE default for new clusters)."
  type        = string
  default     = null
}

variable "enable_private_endpoint" {
  description = "true = control plane reachable only from inside the VPC (needs a bastion/VPN for kubectl and CI)."
  type        = bool
  default     = false
}

variable "master_authorized_networks" {
  description = "CIDRs allowed to reach the GKE control plane (office egress, CI runners, bastion). Empty = none from the internet."
  type = list(object({
    cidr_block   = string
    display_name = string
  }))
  default = []
}

variable "nat_ip_count" {
  description = "Static external IPs for Cloud NAT (egress to Neon/ERP); allow-list these on the Neon/ERP side."
  type        = number
  default     = 2
}

# ---- Edge ------------------------------------------------------------------------------------------------------

variable "ingress_ip_name" {
  description = "Name of the global static IP. Must match kubernetes.io/ingress.global-static-ip-name in ingress.yaml."
  type        = string
  default     = "pic-web-ip"
}

variable "ssl_policy_name" {
  description = "Name of the SSL policy. Must match FrontendConfig.spec.sslPolicy in ingress.yaml."
  type        = string
  default     = "pic-ssl-policy"
}

variable "armor_policy_name" {
  description = "Name of the Cloud Armor policy. Must match BackendConfig.spec.securityPolicy.name in ingress.yaml."
  type        = string
  default     = "pic-web-armor"
}

variable "armor_rate_limit_per_minute" {
  description = "Global per-client-IP request budget per minute at the edge (the app's own limits are per replica)."
  type        = number
  default     = 1200
}

variable "armor_ban_duration_sec" {
  description = "How long an IP that keeps exceeding the rate limit is banned."
  type        = number
  default     = 300
}

variable "armor_waf_preview" {
  description = "Run the OWASP CRS rules in preview (log-only). Set false after reviewing logs for false positives."
  type        = bool
  default     = true
}

variable "armor_adaptive_protection" {
  description = "Enable Cloud Armor Adaptive Protection (L7 DDoS detection)."
  type        = bool
  default     = false
}

# ---- Registry --------------------------------------------------------------------------------------------------

variable "enable_ghcr_mirror" {
  description = "Create an Artifact Registry remote repository that proxies ghcr.io for in-region image pulls."
  type        = bool
  default     = true
}

variable "ghcr_credentials_secret_version" {
  description = "Optional Secret Manager secret version (projects/.../secrets/.../versions/N) holding a GitHub PAT (read:packages) for private GHCR packages. null = public packages."
  type        = string
  default     = null
}

variable "ghcr_username" {
  description = "GitHub username paired with ghcr_credentials_secret_version."
  type        = string
  default     = null
}

variable "labels" {
  description = "Extra labels applied to every resource."
  type        = map(string)
  default     = {}
}
