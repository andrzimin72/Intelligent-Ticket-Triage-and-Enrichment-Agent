# 0. Enable model access first: Bedrock console (us-east-1) -> Model access.
#    Then confirm the profile ID and set it in terraform.tfvars.
cat > terraform.tfvars <<'EOF'
aws_region          = "us-east-1"
environment         = "dev"
model_id            = "us.anthropic.claude-sonnet-5-5-v1:0"   # verified value
foundation_model_id = "anthropic.claude-sonnet-5-5-v1:0"      # verified value
alert_email         = "sara@yourmsp.com"
EOF

terraform init
terraform plan -out tfplan
terraform apply tfplan

# 1. Populate secrets out-of-band (never in .tf files)
aws secretsmanager put-secret-value --secret-id dev/msp/psa/api_keys \
  --secret-string '{"BASE_URL":"https://your-psa.example/api","API_TOKEN":"..."}'

aws secretsmanager put-secret-value --secret-id dev/msp/rmm/api_keys \
  --secret-string '{"BASE_URL":"https://your-rmm.example","API_TOKEN":"..."}'

aws secretsmanager put-secret-value --secret-id dev/msp/webhook/token \
  --secret-string "{\"TOKEN\":\"$(openssl rand -hex 32)\"}"

# 2. Smoke test — expect HTTP 200 and a message on the queue
URL=$(terraform output -raw webhook_url)
TOKEN=$(aws secretsmanager get-secret-value --secret-id dev/msp/webhook/token \
        --query SecretString --output text | python3 -c 'import json,sys;print(json.load(sys.stdin)["TOKEN"])')

curl -i -X POST "$URL" -H "x-psa-token: $TOKEN" \
  -H 'content-type: application/json' -d '{"ticket_id":"12345"}'

# 3. Negative test — must be 401
curl -i -X POST "$URL" -H "x-psa-token: wrong" -d '{"ticket_id":"12345"}'

aws logs tail "$(terraform output -raw orchestrator_log_group)" --follow