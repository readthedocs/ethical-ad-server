# ---------------------------------------------------------------------------
# RDS PostgreSQL (replaces Azure Database for PostgreSQL)
# ---------------------------------------------------------------------------

resource "aws_db_subnet_group" "main" {
  name       = "${var.project}-${var.environment}"
  subnet_ids = var.subnet_ids

  tags = {
    Name = "${var.project}-${var.environment}"
  }
}

resource "aws_db_parameter_group" "main" {
  name_prefix = "${var.project}-${var.environment}-"
  family      = "postgres16"
  description = "EthicalAds PostgreSQL parameters"

  # Optimize for the ad server workload
  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "main" {
  identifier = "${var.project}-${var.environment}"

  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_allocated_storage * 2
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  multi_az               = var.db_multi_az
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = var.security_group_ids
  parameter_group_name   = aws_db_parameter_group.main.name

  backup_retention_period = 14
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:30-sun:05:30"

  # Enable Performance Insights (free tier for 7 days retention)
  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.project}-${var.environment}-final"

  tags = {
    Name = "${var.project}-${var.environment}"
  }
}

# Optional read replica for reporting queries
resource "aws_db_instance" "replica" {
  count = var.create_replica ? 1 : 0

  identifier          = "${var.project}-${var.environment}-replica"
  replicate_source_db = aws_db_instance.main.identifier

  instance_class = var.db_instance_class
  storage_type   = "gp3"

  vpc_security_group_ids = var.security_group_ids
  parameter_group_name   = aws_db_parameter_group.main.name

  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  skip_final_snapshot = true

  tags = {
    Name = "${var.project}-${var.environment}-replica"
  }
}
