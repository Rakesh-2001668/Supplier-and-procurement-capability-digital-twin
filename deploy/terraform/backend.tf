# Remote state. Create the bucket once (versioned, uniform access, in-region), then uncomment and run
# `terraform init -migrate-state`:
#
#   gcloud storage buckets create gs://<project-id>-pic-tfstate \
#     --project=<project-id> --location=asia-south1 --uniform-bucket-level-access --public-access-prevention
#   gcloud storage buckets update gs://<project-id>-pic-tfstate --versioning
#
# terraform {
#   backend "gcs" {
#     bucket = "<project-id>-pic-tfstate"
#     prefix = "pic/prod"
#   }
# }
