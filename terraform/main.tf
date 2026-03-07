# EthicalAds AWS Infrastructure
#
# This Terraform configuration provisions the AWS infrastructure
# needed to run the EthicalAds Django application, migrating from Azure.
#
# Components:
#   - VPC with public/private subnets across 2 AZs
#   - RDS PostgreSQL (replaces Azure Database for PostgreSQL)
#   - ElastiCache Redis (replaces Azure Cache for Redis)
#   - S3 + CloudFront (replaces Azure Blob Storage + CDN)
#   - ECS Fargate (replaces Azure VM Scale Sets)
#   - ALB with HTTPS (replaces Azure Load Balancer)
#   - ECR for Docker images

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Configure remote state storage in S3
  # Uncomment and configure before first apply
  # backend "s3" {
  #   bucket         = "ethicalads-terraform-state"
  #   key            = "production/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "ethicalads-terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "ethicalads"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# Secondary provider for CloudFront ACM certificates (must be us-east-1)
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = {
      Project     = "ethicalads"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------
data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# VPC
# ---------------------------------------------------------------------------
module "vpc" {
  source = "./modules/vpc"

  project     = var.project
  environment = var.environment
  vpc_cidr    = var.vpc_cidr
  azs         = slice(data.aws_availability_zones.available.names, 0, 2)
}

# ---------------------------------------------------------------------------
# Security Groups
# ---------------------------------------------------------------------------
module "security_groups" {
  source = "./modules/security-groups"

  project     = var.project
  environment = var.environment
  vpc_id      = module.vpc.vpc_id
}

# ---------------------------------------------------------------------------
# ECR - Docker image repository
# ---------------------------------------------------------------------------
module "ecr" {
  source = "./modules/ecr"

  project     = var.project
  environment = var.environment
}

# ---------------------------------------------------------------------------
# RDS PostgreSQL
# ---------------------------------------------------------------------------
module "rds" {
  source = "./modules/rds"

  project            = var.project
  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  subnet_ids         = module.vpc.private_subnet_ids
  security_group_ids = [module.security_groups.rds_sg_id]

  db_instance_class    = var.db_instance_class
  db_allocated_storage = var.db_allocated_storage
  db_name              = var.db_name
  db_username          = var.db_username
  db_password          = var.db_password
  db_multi_az          = var.db_multi_az

  # Optional read replica
  create_replica = var.db_create_replica
}

# ---------------------------------------------------------------------------
# ElastiCache Redis
# ---------------------------------------------------------------------------
module "elasticache" {
  source = "./modules/elasticache"

  project            = var.project
  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  subnet_ids         = module.vpc.private_subnet_ids
  security_group_ids = [module.security_groups.redis_sg_id]

  node_type       = var.redis_node_type
  num_cache_nodes = var.redis_num_cache_nodes
}

# ---------------------------------------------------------------------------
# S3 - Media storage (replaces Azure Blob Storage)
# ---------------------------------------------------------------------------
module "s3" {
  source = "./modules/s3"

  project     = var.project
  environment = var.environment
}

# ---------------------------------------------------------------------------
# CloudFront CDN for media files
# ---------------------------------------------------------------------------
module "cloudfront" {
  source = "./modules/cloudfront"

  providers = {
    aws = aws.us_east_1
  }

  project              = var.project
  environment          = var.environment
  media_bucket_id      = module.s3.media_bucket_id
  media_bucket_arn     = module.s3.media_bucket_arn
  media_domain_name    = module.s3.media_bucket_regional_domain_name
  cloudfront_domain    = var.media_domain
  acm_certificate_arn  = var.media_acm_certificate_arn
}

# ---------------------------------------------------------------------------
# ALB - Application Load Balancer
# ---------------------------------------------------------------------------
module "alb" {
  source = "./modules/alb"

  project            = var.project
  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  subnet_ids         = module.vpc.public_subnet_ids
  security_group_ids = [module.security_groups.alb_sg_id]
  acm_certificate_arn = var.app_acm_certificate_arn
}

# ---------------------------------------------------------------------------
# ECS Fargate - Django, Celery Worker, Celery Beat
# ---------------------------------------------------------------------------
module "ecs" {
  source = "./modules/ecs"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region
  account_id  = data.aws_caller_identity.current.account_id

  # Networking
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  security_group_ids = [module.security_groups.ecs_sg_id]

  # Load balancer
  alb_target_group_arn = module.alb.target_group_arn

  # Container image
  ecr_repository_url = module.ecr.repository_url
  image_tag          = var.image_tag

  # Service scaling
  django_desired_count = var.django_desired_count
  django_cpu           = var.django_cpu
  django_memory        = var.django_memory
  celery_worker_desired_count = var.celery_worker_desired_count
  celery_worker_cpu    = var.celery_worker_cpu
  celery_worker_memory = var.celery_worker_memory

  # Environment variables for the Django application
  app_environment = merge(
    {
      DJANGO_SETTINGS_MODULE = "config.settings.production"
      DATABASE_URL           = module.rds.database_url
      REDIS_URL              = module.elasticache.redis_url
      CELERY_BROKER_URL      = module.elasticache.redis_url
      ALLOWED_HOSTS          = var.allowed_hosts
      ADSERVER_HTTPS         = "True"
      MEDIA_URL              = "https://${var.media_domain}/"

      # S3 storage backend (replaces Azure Blob Storage)
      DEFAULT_FILE_STORAGE            = "storages.backends.s3boto3.S3Boto3Storage"
      AWS_STORAGE_BUCKET_NAME         = module.s3.media_bucket_id
      AWS_S3_REGION_NAME              = var.aws_region
      AWS_S3_CUSTOM_DOMAIN            = var.media_domain
      AWS_DEFAULT_ACL                 = null
      AWS_QUERYSTRING_AUTH            = "False"
      BACKUPS_STORAGE                 = "config.storage.S3BackupsStorage"
      AWS_BACKUPS_STORAGE_BUCKET_NAME = module.s3.backups_bucket_id
    },
    var.app_secrets,
  )
}
