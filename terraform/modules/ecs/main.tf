# ---------------------------------------------------------------------------
# ECS Fargate - Django web, Celery worker, Celery beat
# (replaces Azure VM Scale Sets with disk images)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# CloudWatch log group
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.project}-${var.environment}"
  retention_in_days = 30

  tags = {
    Name = "${var.project}-${var.environment}"
  }
}

# ---------------------------------------------------------------------------
# IAM - ECS task execution role (pulling images, writing logs)
# ---------------------------------------------------------------------------
resource "aws_iam_role" "ecs_execution" {
  name = "${var.project}-${var.environment}-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ---------------------------------------------------------------------------
# IAM - ECS task role (what the running container can access)
# ---------------------------------------------------------------------------
resource "aws_iam_role" "ecs_task" {
  name = "${var.project}-${var.environment}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

# Allow ECS tasks to access S3 (media + backups buckets)
resource "aws_iam_role_policy" "ecs_task_s3" {
  name = "${var.project}-${var.environment}-s3-access"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
        ]
        Resource = [
          "arn:aws:s3:::${var.project}-${var.environment}-media",
          "arn:aws:s3:::${var.project}-${var.environment}-media/*",
          "arn:aws:s3:::${var.project}-${var.environment}-backups",
          "arn:aws:s3:::${var.project}-${var.environment}-backups/*",
        ]
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# ECS Cluster
# ---------------------------------------------------------------------------
resource "aws_ecs_cluster" "main" {
  name = "${var.project}-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "${var.project}-${var.environment}"
  }
}

# ---------------------------------------------------------------------------
# Locals: build environment and container definitions
# ---------------------------------------------------------------------------
locals {
  # Convert the app_environment map into ECS-compatible environment list
  environment = [
    for key, value in var.app_environment : {
      name  = key
      value = tostring(value)
    }
  ]

  # Common container settings
  log_configuration = {
    logDriver = "awslogs"
    options = {
      "awslogs-group"         = aws_cloudwatch_log_group.app.name
      "awslogs-region"        = var.aws_region
      "awslogs-stream-prefix" = "ecs"
    }
  }

  image = "${var.ecr_repository_url}:${var.image_tag}"
}

# ---------------------------------------------------------------------------
# Django web service (Gunicorn behind ALB)
# ---------------------------------------------------------------------------
resource "aws_ecs_task_definition" "django" {
  family                   = "${var.project}-${var.environment}-django"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.django_cpu
  memory                   = var.django_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "django"
      image     = local.image
      essential = true
      portMappings = [
        {
          containerPort = 5000
          protocol      = "tcp"
        }
      ]
      command         = ["newrelic-admin", "run-program", "gunicorn", "config.wsgi", "--bind", "0.0.0.0:5000", "--max-requests=10000", "--log-file", "-"]
      environment     = local.environment
      logConfiguration = local.log_configuration
    }
  ])
}

resource "aws_ecs_service" "django" {
  name            = "${var.project}-${var.environment}-django"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.django.arn
  desired_count   = var.django_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.alb_target_group_arn
    container_name   = "django"
    container_port   = 5000
  }

  # Rolling deployment
  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200

  # Ignore desired_count changes from autoscaling
  lifecycle {
    ignore_changes = [desired_count]
  }
}

# Auto-scaling for Django web tasks
resource "aws_appautoscaling_target" "django" {
  max_capacity       = var.django_desired_count * 4
  min_capacity       = var.django_desired_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.django.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "django_cpu" {
  name               = "${var.project}-${var.environment}-django-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.django.resource_id
  scalable_dimension = aws_appautoscaling_target.django.scalable_dimension
  service_namespace  = aws_appautoscaling_target.django.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 65.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# ---------------------------------------------------------------------------
# Celery worker
# ---------------------------------------------------------------------------
resource "aws_ecs_task_definition" "celery_worker" {
  family                   = "${var.project}-${var.environment}-celery-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.celery_worker_cpu
  memory                   = var.celery_worker_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "celery-worker"
      image     = local.image
      essential = true
      command   = ["celery", "worker", "--app=config.celery_app.app", "--loglevel=INFO", "--without-gossip", "--without-mingle", "--without-heartbeat", "--max-tasks-per-child", "1000"]
      environment     = local.environment
      logConfiguration = local.log_configuration
    }
  ])
}

resource "aws_ecs_service" "celery_worker" {
  name            = "${var.project}-${var.environment}-celery-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.celery_worker.arn
  desired_count   = var.celery_worker_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = false
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
}

# ---------------------------------------------------------------------------
# Celery beat (singleton scheduler)
# ---------------------------------------------------------------------------
resource "aws_ecs_task_definition" "celery_beat" {
  family                   = "${var.project}-${var.environment}-celery-beat"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "celery-beat"
      image     = local.image
      essential = true
      command   = ["celery", "beat", "--app=config.celery_app.app", "--loglevel=INFO"]
      environment     = local.environment
      logConfiguration = local.log_configuration
    }
  ])
}

resource "aws_ecs_service" "celery_beat" {
  name            = "${var.project}-${var.environment}-celery-beat"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.celery_beat.arn
  desired_count   = 1 # Only one beat scheduler
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = false
  }

  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
}
