# ---------------------------------------------------------------------------
# Security Groups
# ---------------------------------------------------------------------------

# ALB - accepts HTTP/HTTPS from the internet
resource "aws_security_group" "alb" {
  name_prefix = "${var.project}-${var.environment}-alb-"
  description = "ALB - HTTP/HTTPS from internet"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project}-${var.environment}-alb-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# ECS Tasks - accepts traffic from ALB only
resource "aws_security_group" "ecs" {
  name_prefix = "${var.project}-${var.environment}-ecs-"
  description = "ECS tasks - traffic from ALB"
  vpc_id      = var.vpc_id

  ingress {
    description     = "HTTP from ALB"
    from_port       = 5000
    to_port         = 5000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project}-${var.environment}-ecs-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# RDS - accepts traffic from ECS tasks only
resource "aws_security_group" "rds" {
  name_prefix = "${var.project}-${var.environment}-rds-"
  description = "RDS - traffic from ECS"
  vpc_id      = var.vpc_id

  ingress {
    description     = "PostgreSQL from ECS"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project}-${var.environment}-rds-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Redis - accepts traffic from ECS tasks only
resource "aws_security_group" "redis" {
  name_prefix = "${var.project}-${var.environment}-redis-"
  description = "Redis - traffic from ECS"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Redis from ECS"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project}-${var.environment}-redis-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}
