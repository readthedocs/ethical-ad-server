output "cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "cluster_arn" {
  value = aws_ecs_cluster.main.arn
}

output "django_service_name" {
  value = aws_ecs_service.django.name
}

output "celery_worker_service_name" {
  value = aws_ecs_service.celery_worker.name
}

output "celery_beat_service_name" {
  value = aws_ecs_service.celery_beat.name
}
