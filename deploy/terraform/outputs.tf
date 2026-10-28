output "cluster_name" {
  description = "GKE Autopilot cluster name (deploy/k8s/external-secret.yaml clusterName)."
  value       = google_container_cluster.pic.name
}

output "cluster_location" {
  description = "Cluster region (deploy/k8s/external-secret.yaml clusterLocation)."
  value       = google_container_cluster.pic.location
}

output "get_credentials_command" {
  description = "Command to configure kubectl for the cluster."
  value       = "gcloud container clusters get-credentials ${google_container_cluster.pic.name} --region ${google_container_cluster.pic.location} --project ${var.project_id}"
}

output "workload_identity_pool" {
  description = "Workload Identity pool of the cluster."
  value       = local.workload_pool
}

output "eso_gsa_email" {
  description = "Google service account for External Secrets (annotation iam.gke.io/gcp-service-account on KSA pic-external-secrets)."
  value       = google_service_account.eso.email
}

output "secret_ids" {
  description = "Secret Manager secrets to populate out-of-band (gcloud secrets versions add ...)."
  value       = sort([for s in google_secret_manager_secret.pic : s.secret_id])
}

output "ingress_ip_name" {
  description = "Global static IP name (ingress.yaml kubernetes.io/ingress.global-static-ip-name)."
  value       = google_compute_global_address.ingress.name
}

output "ingress_ip_address" {
  description = "Create the DNS A record for var.domain pointing here."
  value       = google_compute_global_address.ingress.address
}

output "domain" {
  description = "Public hostname expected in ingress.yaml (Ingress host + ManagedCertificate)."
  value       = var.domain
}

output "ssl_policy_name" {
  description = "SSL policy name (ingress.yaml FrontendConfig.spec.sslPolicy)."
  value       = google_compute_ssl_policy.web.name
}

output "armor_policy_name" {
  description = "Cloud Armor policy name (ingress.yaml BackendConfig.spec.securityPolicy.name)."
  value       = google_compute_security_policy.web.name
}

output "nat_ip_addresses" {
  description = "Static egress IPs of the cluster (allow-list on Neon / ERP systems)."
  value       = google_compute_address.nat[*].address
}

output "field_kek_id" {
  description = "Cloud KMS key reserved for future PIC_FIELD_KEY envelope encryption."
  value       = google_kms_crypto_key.field_kek.id
}

output "ghcr_mirror_prefix" {
  description = "Image prefix for in-region pulls via the Artifact Registry remote repository (null if disabled)."
  value       = var.enable_ghcr_mirror ? "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.ghcr[0].repository_id}/${var.github_owner}" : null
}

output "dr_region" {
  description = "DR region reserved for the secondary stack (not provisioned by this configuration)."
  value       = var.dr_region
}
