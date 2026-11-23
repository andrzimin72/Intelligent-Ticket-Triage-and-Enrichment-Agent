#!/bin/bash
# Deploy the tenant portal static site to S3

set -e

PORTAL_BUCKET=$(terraform output -raw portal_bucket_name)
COGNITO_USER_POOL_ID=$(terraform output -raw cognito_user_pool_id)
COGNITO_CLIENT_ID=$(terraform output -raw cognito_client_id)
COGNITO_DOMAIN=$(terraform output -raw cognito_domain)
API_URL=$(terraform output -raw portal_api_url)

echo "Deploying portal to s3://$PORTAL_BUCKET..."

# Update config.js with actual values
sed -e "s|__COGNITO_USER_POOL_ID__|$COGNITO_USER_POOL_ID|g" \
    -e "s|__COGNITO_CLIENT_ID__|$COGNITO_CLIENT_ID|g" \
    -e "s|__COGNITO_DOMAIN__|$COGNITO_DOMAIN|g" \
    -e "s|__API_URL__|$API_URL|g" \
    portal-site/config.js > portal-site/config.js.tmp

mv portal-site/config.js.tmp portal-site/config.js

# Upload to S3
aws s3 sync portal-site/ s3://$PORTAL_BUCKET/ \
  --exclude ".git/*" \
  --cache-control "max-age=3600"

# Invalidate CloudFront cache
DISTRIBUTION_ID=$(terraform output -raw cloudfront_distribution_id)
aws cloudfront create-invalidation \
  --distribution-id $DISTRIBUTION_ID \
  --paths "/*"

echo "Portal deployed successfully!"
echo "URL: https://$(terraform output -raw portal_domain_name)"