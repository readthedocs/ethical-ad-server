# EthicalAds AWS Infrastructure (Terraform)

This directory contains Terraform configurations to provision
the AWS infrastructure for EthicalAds, migrating from Azure.

## Architecture

```
                    ┌─────────────────────────────────────────────────────┐
                    │                      VPC                           │
                    │                                                     │
   Internet ──────►│  ┌─────────┐    ┌──────────────────────────┐        │
                    │  │   ALB   │───►│  ECS Fargate (private)   │        │
                    │  │ (public)│    │  ┌────────┐ ┌──────────┐ │        │
                    │  └─────────┘    │  │ Django │ │ Celery   │ │        │
                    │                 │  │ (x2+)  │ │ Worker   │ │        │
                    │                 │  └───┬────┘ │ (x2+)    │ │        │
                    │                 │      │      └────┬─────┘ │        │
                    │                 │  ┌───┴──┐ ┌──────┴─────┐ │        │
                    │                 │  │  RDS │ │ElastiCache │ │        │
                    │                 │  │Postgr│ │   Redis    │ │        │
                    │                 │  └──────┘ └────────────┘ │        │
                    │                 │  ┌──────────┐            │        │
                    │                 │  │ Celery   │            │        │
                    │                 │  │ Beat (1) │            │        │
                    │                 │  └──────────┘            │        │
                    │                 └──────────────────────────┘        │
                    └─────────────────────────────────────────────────────┘

   CloudFront CDN ──► S3 (media)     S3 (backups)
```

## Azure → AWS Mapping

| Azure Resource | AWS Equivalent | Terraform Module |
|---|---|---|
| VM Scale Sets (disk images) | ECS Fargate | `modules/ecs` |
| Azure Database for PostgreSQL | RDS PostgreSQL 16 | `modules/rds` |
| Azure Cache for Redis | ElastiCache Redis 7.1 | `modules/elasticache` |
| Azure Blob Storage (media) | S3 + CloudFront | `modules/s3`, `modules/cloudfront` |
| Azure Blob Storage (backups) | S3 (with Glacier lifecycle) | `modules/s3` |
| Azure Load Balancer | ALB | `modules/alb` |
| Azure Container Registry | ECR | `modules/ecr` |
| VNet | VPC | `modules/vpc` |
| NSGs | Security Groups | `modules/security-groups` |

## Modules

| Module | Description |
|---|---|
| `vpc` | VPC with public/private subnets across 2 AZs, NAT gateway |
| `security-groups` | Security groups for ALB, ECS, RDS, Redis |
| `ecr` | Docker image repository with lifecycle policy |
| `rds` | PostgreSQL 16 with optional read replica |
| `elasticache` | Redis 7.1 with TLS |
| `s3` | Media and backups buckets with encryption and lifecycle |
| `cloudfront` | CDN for media files with OAC |
| `alb` | Application Load Balancer with HTTPS |
| `ecs` | ECS cluster with Django, Celery worker, and Celery beat services |

## Prerequisites

1. [Install Terraform](https://developer.hashicorp.com/terraform/install) >= 1.5
2. Configure AWS credentials (`aws configure` or env vars)
3. Create ACM certificates for your domains (app + media CDN)

## Quick Start

```bash
cd terraform

# Initialize Terraform
terraform init

# Copy and fill in the variables
cp production.tfvars.example production.tfvars
# Edit production.tfvars with your values

# Preview changes
terraform plan -var-file=production.tfvars

# Apply
terraform apply -var-file=production.tfvars
```

## Migration Steps

### 1. Provision AWS Infrastructure

```bash
terraform apply -var-file=production.tfvars
```

This creates: VPC, RDS, ElastiCache, S3 buckets, CloudFront, ALB, ECS cluster, ECR.

### 2. Build and Push Docker Image

```bash
# Get the ECR repository URL from Terraform output
ECR_URL=$(terraform output -raw ecr_repository_url)

# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $ECR_URL

# Build and push
docker build -t $ECR_URL:latest .
docker push $ECR_URL:latest
```

### 3. Migrate the Database

```bash
# Export from Azure PostgreSQL
pg_dump -h <azure-host> -U <user> -d ethicaladserver -Fc > backup.dump

# Get the RDS endpoint
RDS_ENDPOINT=$(terraform output -raw rds_endpoint)

# Import to AWS RDS
pg_restore -h $RDS_ENDPOINT -U ethicalads -d ethicaladserver backup.dump
```

### 4. Migrate Media Files (Azure Blob → S3)

```bash
# Option A: Use azcopy + aws s3 sync
azcopy copy "https://<account>.blob.core.windows.net/<container>/*" ./media-files --recursive
aws s3 sync ./media-files s3://ethicalads-production-media/

# Option B: Use rclone for direct cloud-to-cloud transfer
rclone sync azure:media s3:ethicalads-production-media
```

### 5. Update DNS

Point your domain's CNAME to the ALB DNS name:

```bash
terraform output alb_dns_name
```

Point your media domain's CNAME to the CloudFront distribution:

```bash
terraform output cloudfront_domain
```

### 6. Configure GitHub Actions

Add these secrets to your GitHub repository:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION` (e.g., `us-east-1`)
- `ECR_REPOSITORY` (from `terraform output ecr_repository_url`)
- `ECS_CLUSTER` (from `terraform output ecs_cluster_name`)

### 7. Django Environment Variables

Key environment variable changes for the migration:

```bash
# Storage backend: change from Azure to S3
DEFAULT_FILE_STORAGE=storages.backends.s3boto3.S3Boto3Storage
BACKUPS_STORAGE=config.storage.S3BackupsStorage

# Remove Azure-specific vars:
# AZURE_ACCOUNT_NAME, AZURE_ACCOUNT_KEY, AZURE_CONTAINER

# Add AWS vars (or use IAM role, which is configured by Terraform):
AWS_STORAGE_BUCKET_NAME=ethicalads-production-media
AWS_BACKUPS_STORAGE_BUCKET_NAME=ethicalads-production-backups
AWS_S3_CUSTOM_DOMAIN=media.ethicalads.io
MEDIA_URL=https://media.ethicalads.io/

# Redis URL changes (TLS enabled on ElastiCache):
REDIS_URL=rediss://<elasticache-endpoint>:6379/0
REDIS_SSL=True
```

## Remote State (Recommended)

Uncomment the `backend "s3"` block in `main.tf` and create the resources:

```bash
# Create state bucket
aws s3api create-bucket --bucket ethicalads-terraform-state --region us-east-1

# Enable versioning
aws s3api put-bucket-versioning --bucket ethicalads-terraform-state \
  --versioning-configuration Status=Enabled

# Create lock table
aws dynamodb create-table \
  --table-name ethicalads-terraform-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

# Re-initialize with the new backend
terraform init -migrate-state
```

## Cost Estimation

Approximate monthly costs (us-east-1, as of 2025):

| Resource | Specification | ~Monthly Cost |
|---|---|---|
| ECS Fargate (Django x2) | 1 vCPU, 2 GB each | ~$60 |
| ECS Fargate (Celery x2) | 1 vCPU, 2 GB each | ~$60 |
| ECS Fargate (Beat x1) | 0.25 vCPU, 0.5 GB | ~$8 |
| RDS PostgreSQL | db.r6g.large, Multi-AZ | ~$380 |
| ElastiCache Redis | cache.r6g.large | ~$200 |
| ALB | Standard | ~$25 |
| NAT Gateway | Single AZ | ~$35 |
| S3 + CloudFront | Variable | ~$10-50 |
| **Total** | | **~$780-830** |

Costs scale with usage. ECS auto-scaling is configured for Django web tasks.
