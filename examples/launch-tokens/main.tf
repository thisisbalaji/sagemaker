terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0"
    }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "domain_ids" {
  type = list(string)
}

variable "allowed_cidrs" {
  description = "Client IPs allowed to use links. Empty allows any IP."
  type        = list(string)
  default     = []
}

module "studio_launch" {
  source = "../../modules/studio-launch-tokens"

  domain_ids    = var.domain_ids
  allowed_cidrs = var.allowed_cidrs

  tags = {
    Project = "smai"
  }
}

output "mint_url" {
  value = module.studio_launch.mint_url
}

output "tokens_table_name" {
  value = module.studio_launch.tokens_table_name
}

output "minter_policy_arn" {
  value = module.studio_launch.minter_policy_arn
}
