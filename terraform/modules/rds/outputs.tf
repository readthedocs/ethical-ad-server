output "endpoint" {
  value = aws_db_instance.main.endpoint
}

output "replica_endpoint" {
  value = var.create_replica ? aws_db_instance.replica[0].endpoint : ""
}

output "database_url" {
  description = "DATABASE_URL in Django-environ format"
  value       = "postgres://${var.db_username}:${var.db_password}@${aws_db_instance.main.endpoint}/${var.db_name}"
  sensitive   = true
}

output "replica_database_url" {
  description = "REPLICA_DATABASE_URL in Django-environ format"
  value       = var.create_replica ? "postgres://${var.db_username}:${var.db_password}@${aws_db_instance.replica[0].endpoint}/${var.db_name}" : ""
  sensitive   = true
}
