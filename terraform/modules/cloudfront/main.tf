# ---------------------------------------------------------------------------
# CloudFront CDN for media files (replaces Azure CDN)
# ---------------------------------------------------------------------------

resource "aws_cloudfront_origin_access_control" "media" {
  name                              = "${var.project}-${var.environment}-media"
  description                       = "OAC for media S3 bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "media" {
  origin {
    domain_name              = var.media_domain_name
    origin_id                = "S3-media"
    origin_access_control_id = aws_cloudfront_origin_access_control.media.id
  }

  enabled         = true
  is_ipv6_enabled = true
  comment         = "EthicalAds media CDN"

  aliases = var.cloudfront_domain != "" ? [var.cloudfront_domain] : []

  default_cache_behavior {
    allowed_methods  = ["GET", "HEAD", "OPTIONS"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "S3-media"

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    viewer_protocol_policy = "redirect-to-https"
    min_ttl                = 0
    default_ttl            = 86400    # 1 day
    max_ttl                = 31536000 # 1 year
    compress               = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    # Use custom cert if provided, otherwise use default CloudFront cert
    cloudfront_default_certificate = var.acm_certificate_arn == "" ? true : false
    acm_certificate_arn            = var.acm_certificate_arn != "" ? var.acm_certificate_arn : null
    ssl_support_method             = var.acm_certificate_arn != "" ? "sni-only" : null
    minimum_protocol_version       = "TLSv1.2_2021"
  }

  tags = {
    Name = "${var.project}-${var.environment}-media"
  }
}

# S3 bucket policy to allow CloudFront OAC access
resource "aws_s3_bucket_policy" "media" {
  bucket = var.media_bucket_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontServicePrincipal"
        Effect    = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action   = "s3:GetObject"
        Resource = "${var.media_bucket_arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.media.arn
          }
        }
      }
    ]
  })
}
