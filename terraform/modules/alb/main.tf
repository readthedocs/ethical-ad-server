# ---------------------------------------------------------------------------
# Application Load Balancer
# ---------------------------------------------------------------------------

resource "aws_lb" "main" {
  name               = "${var.project}-${var.environment}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = var.security_group_ids
  subnets            = var.subnet_ids

  enable_deletion_protection = true

  tags = {
    Name = "${var.project}-${var.environment}"
  }
}

# Target group for Django (Gunicorn on port 5000)
resource "aws_lb_target_group" "django" {
  name        = "${var.project}-${var.environment}-django"
  port        = 5000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 30
    matcher             = "200"
    path                = "/"
    port                = "traffic-port"
    timeout             = 10
    unhealthy_threshold = 3
  }

  # Allow time for in-flight requests to complete during deploys
  deregistration_delay = 30

  tags = {
    Name = "${var.project}-${var.environment}-django"
  }
}

# HTTPS listener (primary)
resource "aws_lb_listener" "https" {
  count = var.acm_certificate_arn != "" ? 1 : 0

  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.django.arn
  }
}

# HTTP listener - redirect to HTTPS
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = var.acm_certificate_arn != "" ? "redirect" : "forward"

    # When we have a cert, redirect HTTP -> HTTPS
    dynamic "redirect" {
      for_each = var.acm_certificate_arn != "" ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }

    # When no cert yet, forward directly (initial setup)
    target_group_arn = var.acm_certificate_arn == "" ? aws_lb_target_group.django.arn : null
  }
}
