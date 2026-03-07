output "distribution_id" {
  value = aws_cloudfront_distribution.media.id
}

output "distribution_domain_name" {
  value = aws_cloudfront_distribution.media.domain_name
}

output "distribution_arn" {
  value = aws_cloudfront_distribution.media.arn
}
