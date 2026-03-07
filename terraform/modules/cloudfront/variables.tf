variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "media_bucket_id" {
  type = string
}

variable "media_bucket_arn" {
  type = string
}

variable "media_domain_name" {
  description = "S3 bucket regional domain name"
  type        = string
}

variable "cloudfront_domain" {
  description = "Custom domain for the CloudFront distribution"
  type        = string
  default     = ""
}

variable "acm_certificate_arn" {
  description = "ACM certificate ARN (must be in us-east-1)"
  type        = string
  default     = ""
}
