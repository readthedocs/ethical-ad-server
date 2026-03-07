variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "account_id" {
  type = string
}

# Networking
variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "security_group_ids" {
  type = list(string)
}

# Load balancer
variable "alb_target_group_arn" {
  type = string
}

# Container image
variable "ecr_repository_url" {
  type = string
}

variable "image_tag" {
  type    = string
  default = "latest"
}

# Django web service
variable "django_desired_count" {
  type    = number
  default = 2
}

variable "django_cpu" {
  type    = number
  default = 1024
}

variable "django_memory" {
  type    = number
  default = 2048
}

# Celery worker
variable "celery_worker_desired_count" {
  type    = number
  default = 2
}

variable "celery_worker_cpu" {
  type    = number
  default = 1024
}

variable "celery_worker_memory" {
  type    = number
  default = 2048
}

# Application environment variables
variable "app_environment" {
  type      = map(string)
  default   = {}
  sensitive = true
}
