terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
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

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

module "sagemaker_domain" {
  source = "../../modules/sagemaker-domain"

  domain_name             = "smai-domain"
  vpc_id                  = var.vpc_id
  subnet_ids              = var.subnet_ids
  app_network_access_type = "PublicInternetOnly"

  user_profiles = {
    "data-scientist-1" = {}
  }

  tags = {
    Project = "smai"
  }
}

output "domain_id" {
  value = module.sagemaker_domain.domain_id
}

output "domain_url" {
  value = module.sagemaker_domain.domain_url
}
