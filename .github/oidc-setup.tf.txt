# =============================================================================
# GitHub Actions OIDC Federation
# Allows GitHub Actions to assume AWS roles without long-lived credentials
# =============================================================================

data "aws_caller_identity" "current" {}

locals {
  github_repo = "your-org/msp-triage-infra"  # Replace with your repo
  environments = ["dev", "staging", "prod"]
}

resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
  
  client_id_list = ["sts.amazonaws.com"]
  
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1"  # GitHub's OIDC thumbprint
  ]
}

resource "aws_iam_role" "github_actions" {
  for_each = toset(local.environments)
  name     = "github-actions-${each.value}"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${local.github_repo}:environment:${each.value}"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "github_actions_admin" {
  for_each   = toset(local.environments)
  role       = aws_iam_role.github_actions[each.value].name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
  # ⚠️  In production, replace with a custom policy with least privilege
}

output "github_role_arns" {
  value = { for env, role in aws_iam_role.github_actions : env => role.arn }
}