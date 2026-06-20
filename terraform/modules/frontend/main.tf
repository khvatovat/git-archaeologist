locals {
  bucket_name = "${var.project}-${var.env}-frontend"
}

resource "aws_s3_bucket" "frontend" {
  bucket        = local.bucket_name
  force_destroy = true

  tags = {
    Project     = var.project
    Environment = var.env
  }
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_website_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  index_document { suffix = "index.html" }
  error_document { key = "index.html" }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  depends_on = [aws_s3_bucket_public_access_block.frontend]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "PublicRead"
      Effect    = "Allow"
      Principal = "*"
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
    }]
  })
}

resource "aws_s3_object" "config_js" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "config.js"
  content_type = "application/javascript"
  content      = "window.API_BASE = 'http://${var.alb_dns_name}';\n"

  depends_on = [aws_s3_bucket_policy.frontend]
}

resource "aws_s3_object" "index_html" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "index.html"
  source       = "${path.root}/../../../frontend/index.html"
  content_type = "text/html"
  etag         = filemd5("${path.root}/../../../frontend/index.html")

  depends_on = [aws_s3_bucket_policy.frontend]
}

resource "aws_s3_object" "history_html" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "history.html"
  source       = "${path.root}/../../../frontend/history.html"
  content_type = "text/html"
  etag         = filemd5("${path.root}/../../../frontend/history.html")

  depends_on = [aws_s3_bucket_policy.frontend]
}
