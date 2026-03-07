# ---------------------------------------------------------------------------
# ElastiCache Redis (replaces Azure Cache for Redis)
# ---------------------------------------------------------------------------

resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.project}-${var.environment}"
  subnet_ids = var.subnet_ids

  tags = {
    Name = "${var.project}-${var.environment}"
  }
}

resource "aws_elasticache_parameter_group" "main" {
  name_prefix = "${var.project}-${var.environment}-"
  family      = "redis7"
  description = "EthicalAds Redis parameters"

  # Match the maxmemory policy that works well for caching + Celery broker
  parameter {
    name  = "maxmemory-policy"
    value = "allkeys-lru"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id = "${var.project}-${var.environment}"
  description          = "EthicalAds Redis cluster"

  engine         = "redis"
  engine_version = "7.1"
  node_type      = var.node_type
  num_cache_clusters = var.num_cache_nodes

  port                   = 6379
  parameter_group_name   = aws_elasticache_parameter_group.main.name
  subnet_group_name      = aws_elasticache_subnet_group.main.name
  security_group_ids     = var.security_group_ids

  # Enable encryption in transit (TLS)
  transit_encryption_enabled = true
  at_rest_encryption_enabled = true

  # Automatic failover requires >= 2 nodes
  automatic_failover_enabled = var.num_cache_nodes > 1

  # Maintenance and snapshots
  maintenance_window       = "sun:05:00-sun:06:00"
  snapshot_retention_limit = 7
  snapshot_window          = "03:00-04:00"

  tags = {
    Name = "${var.project}-${var.environment}"
  }
}
