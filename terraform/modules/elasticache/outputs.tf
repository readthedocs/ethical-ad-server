output "endpoint" {
  value = aws_elasticache_replication_group.main.primary_endpoint_address
}

output "redis_url" {
  description = "Redis URL for Django (with TLS)"
  value       = "rediss://${aws_elasticache_replication_group.main.primary_endpoint_address}:6379/0"
}
