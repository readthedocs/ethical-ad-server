# ---------------------------------------------------------------------------
# General
# ---------------------------------------------------------------------------
variable "project" {
  description = "Project name used for resource naming"
  type        = string
  default     = "ethicalads"
}

variable "environment" {
  description = "Deployment environment (production, staging)"
  type        = string
  default     = "production"
}

variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------
variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

# ---------------------------------------------------------------------------
# RDS PostgreSQL
# ---------------------------------------------------------------------------
variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.r6g.large"
}

variable "db_allocated_storage" {
  description = "Allocated storage in GB"
  type        = number
  default     = 100
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "ethicaladserver"
}

variable "db_username" {
  description = "Database master username"
  type        = string
  default     = "ethicalads"
  sensitive   = true
}

variable "db_password" {
  description = "Database master password"
  type        = string
  sensitive   = true
}

variable "db_multi_az" {
  description = "Enable Multi-AZ for RDS"
  type        = bool
  default     = true
}

variable "db_create_replica" {
  description = "Create a read replica (used for reporting queries)"
  type        = bool
  default     = false
}

# ---------------------------------------------------------------------------
# ElastiCache Redis
# ---------------------------------------------------------------------------
variable "redis_node_type" {
  description = "ElastiCache node type"
  type        = string
  default     = "cache.r6g.large"
}

variable "redis_num_cache_nodes" {
  description = "Number of cache nodes"
  type        = number
  default     = 1
}

# ---------------------------------------------------------------------------
# ECS / Fargate
# ---------------------------------------------------------------------------
variable "image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
}

variable "django_desired_count" {
  description = "Number of Django web tasks"
  type        = number
  default     = 2
}

variable "django_cpu" {
  description = "CPU units for Django task (1024 = 1 vCPU)"
  type        = number
  default     = 1024
}

variable "django_memory" {
  description = "Memory in MiB for Django task"
  type        = number
  default     = 2048
}

variable "celery_worker_desired_count" {
  description = "Number of Celery worker tasks"
  type        = number
  default     = 2
}

variable "celery_worker_cpu" {
  description = "CPU units for Celery worker task"
  type        = number
  default     = 1024
}

variable "celery_worker_memory" {
  description = "Memory in MiB for Celery worker task"
  type        = number
  default     = 2048
}

# ---------------------------------------------------------------------------
# Domains & Certificates
# ---------------------------------------------------------------------------
variable "allowed_hosts" {
  description = "Comma-separated list of allowed hosts for Django"
  type        = string
  default     = "server.ethicalads.io"
}

variable "media_domain" {
  description = "Custom domain for CloudFront media CDN (e.g. media.ethicalads.io)"
  type        = string
  default     = "media.ethicalads.io"
}

variable "media_acm_certificate_arn" {
  description = "ACM certificate ARN for the media CloudFront distribution (must be in us-east-1)"
  type        = string
  default     = ""
}

variable "app_acm_certificate_arn" {
  description = "ACM certificate ARN for the ALB (must be in the same region)"
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Application Secrets (passed as env vars to ECS tasks)
# ---------------------------------------------------------------------------
variable "app_secrets" {
  description = "Map of secret environment variables for the Django app (SECRET_KEY, SENDGRID_API_KEY, SENTRY_DSN, STRIPE_SECRET_KEY, etc.)"
  type        = map(string)
  default     = {}
  sensitive   = true
}
