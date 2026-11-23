terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws     = { source = "hashicorp/aws", version = ">= 5.40, < 7.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.4" }
  }

  # State contains resource metadata — keep it encrypted and locked.
  # S3-native locking (use_lockfile) avoids needing a DynamoDB table.
  backend "s3" {
    bucket       = "REPLACE-tfstate-bucket"
    key          = "msp-triage/dev/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region
  default_tags { tags = local.tags }
}