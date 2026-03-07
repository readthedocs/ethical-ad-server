# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "alb_dns_name" {
  description = "ALB DNS name - point your domain CNAME here"
  value       = module.alb.alb_dns_name
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint"
  value       = module.rds.endpoint
  sensitive   = true
}

output "rds_replica_endpoint" {
  description = "RDS read replica endpoint (if created)"
  value       = module.rds.replica_endpoint
  sensitive   = true
}

output "redis_endpoint" {
  description = "ElastiCache Redis endpoint"
  value       = module.elasticache.endpoint
}

output "ecr_repository_url" {
  description = "ECR repository URL for Docker images"
  value       = module.ecr.repository_url
}

output "media_bucket" {
  description = "S3 bucket for media files"
  value       = module.s3.media_bucket_id
}

output "backups_bucket" {
  description = "S3 bucket for database backups"
  value       = module.s3.backups_bucket_id
}

output "cloudfront_domain" {
  description = "CloudFront distribution domain name"
  value       = module.cloudfront.distribution_domain_name
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = module.ecs.cluster_name
}

output "database_url" {
  description = "Full DATABASE_URL for Django"
  value       = module.rds.database_url
  sensitive   = true
}

output "redis_url" {
  description = "Full REDIS_URL for Django"
  value       = module.elasticache.redis_url
}
