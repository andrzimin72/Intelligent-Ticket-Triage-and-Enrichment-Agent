#!/usr/bin/env python3
"""
Tenant Migration Script: Terraform → API Management (Phase D, Strategy 2)

Migrates existing Terraform-managed tenants to be fully managed by the
onboarding API. This involves:

1. Verifying each tenant's agent is healthy
2. Ensuring the tenant registry has complete metadata
3. Generating Terraform state removal commands
4. Optionally running those commands (with confirmation)

After migration:
- AWS resources (agents, action groups, aliases) continue to run
- Terraform no longer manages them
- The onboarding API becomes the single source of truth

Safety features:
- Dry-run mode (default) shows what would happen without making changes
- Per-tenant verification before migration
- Rollback instructions included in output
- Skips tenants that aren't ready

Usage:
    # Dry run (safe, no changes)
    python scripts/migrate_tenants_to_api.py --profile dev --dry-run

    # Migrate specific tenant
    python scripts/migrate_tenants_to_api.py --profile dev --tenant msp-acme

    # Migrate all ready tenants
    python scripts/migrate_tenants_to_api.py --profile dev --all --confirm

    # Generate Terraform config updates
    python scripts/migrate_tenants_to_api.py --profile dev --generate-tf-config
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import boto3
from botocore.exceptions import ClientError


def get_aws_session(profile: str, region: str) -> boto3.Session:
    """Creates a boto3 session with the specified profile."""
    return boto3.Session(profile_name=profile, region_name=region)


def get_all_terraform_tenants(dynamodb, table_name: str) -> List[Dict[str, Any]]:
    """
    Gets all tenants from the registry.
    
    In hybrid mode, we can't distinguish Terraform vs API tenants by the
    registry alone. This script assumes all existing tenants are Terraform-managed
    unless they have management_mode='api' or 'hybrid'.
    """
    table = dynamodb.Table(table_name)
    response = table.scan()
    tenants = response.get('Items', [])
    
    while 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        tenants.extend(response.get('Items', []))
    
    return tenants


def verify_tenant_ready_for_migration(
    tenant: Dict[str, Any],
    bedrock_agent,
    secrets_client,
    environment: str
) -> Tuple[bool, List[str]]:
    """
    Verifies a tenant is ready for migration.
    
    Returns (is_ready, list_of_issues).
    """
    issues = []
    tenant_id = tenant.get('tenant_id')
    
    # Check 1: Tenant must be active
    if tenant.get('status') != 'active':
        issues.append(f"status={tenant.get('status')} (must be 'active')")
    
    # Check 2: Must have agent_id
    agent_id = tenant.get('agent_id')
    if not agent_id:
        issues.append("missing agent_id")
        return False, issues
    
    # Check 3: Agent must be healthy
    try:
        response = bedrock_agent.get_agent(agentId=agent_id)
        agent_status = response.get('agent', {}).get('agentStatus')
        if agent_status != 'PREPARED':
            issues.append(f"agent_status={agent_status} (must be 'PREPARED')")
    except bedrock_agent.exceptions.ResourceNotFoundException:
        issues.append("agent not found in Bedrock")
    except Exception as e:
        issues.append(f"agent check failed: {str(e)}")
    
    # Check 4: Must have alias
    if not tenant.get('agent_alias_id'):
        issues.append("missing agent_alias_id")
    
    # Check 5: Secrets must be populated
    for secret_type in ['psa', 'rmm', 'graph']:
        secret_name = f"{environment}/tenants/{tenant_id}/{secret_type}"
        try:
            value = secrets_client.get_secret_value(SecretId=secret_name)
            secret_data = json.loads(value['SecretString'])
            if not any(v for v in secret_data.values() if v):
                issues.append(f"secret {secret_type} not populated")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                issues.append(f"secret {secret_type} missing")
            else:
                issues.append(f"secret {secret_type} check failed: {str(e)}")
    
    # Check 6: Not already migrated
    management_mode = tenant.get('management_mode')
    if management_mode == 'api':
        issues.append("already migrated to API management")
    
    return len(issues) == 0, issues


def generate_terraform_state_removal_commands(tenant_id: str, environment: str) -> List[str]:
    """
    Generates the Terraform state removal commands for a tenant.
    
    These commands remove the per-tenant resources from Terraform state
    without destroying the actual AWS resources.
    """
    prefix = f"{environment}-msp-triage"
    resources = [
        f"aws_bedrockagent_agent.it_concierge[\"{tenant_id}\"]",
        f"aws_bedrockagent_agent_alias.latest[\"{tenant_id}\"]",
        f"aws_bedrockagent_agent_action_group.identity_tools[\"{tenant_id}\"]",
        f"aws_bedrockagent_agent_action_group.ticket_tools[\"{tenant_id}\"]",
        f"aws_bedrockagent_agent_action_group.device_tools[\"{tenant_id}\"]",
        f"aws_bedrockagent_agent_action_group.calendar_tools[\"{tenant_id}\"]",
        f"aws_lambda_permission.agent_invoke_identity_tools[\"{tenant_id}\"]",
        f"aws_lambda_permission.agent_invoke_ticket_tools[\"{tenant_id}\"]",
        f"aws_lambda_permission.agent_invoke_device_tools[\"{tenant_id}\"]",
        f"aws_lambda_permission.agent_invoke_calendar_tools[\"{tenant_id}\"]",
    ]
    
    commands = []
    for resource in resources:
        commands.append(f"terraform state rm '{resource}'")
    
    return commands


def generate_updated_tfvars(tenants_to_keep: List[str], original_tfvars_path: str) -> str:
    """
    Generates an updated terraform.tfvars with only the tenants that should
    remain under Terraform management.
    """
    # Read the original tfvars
    with open(original_tfvars_path, 'r') as f:
        content = f.read()
    
    # Parse the tenants block (simplified — assumes well-formatted HCL)
    # In production, you'd use a proper HCL parser
    lines = content.split('\n')
    output_lines = []
    in_tenants_block = False
    current_tenant = None
    tenant_buffer = []
    
    for line in lines:
        if 'tenants = {' in line:
            in_tenants_block = True
            output_lines.append(line)
            continue
        
        if in_tenants_block:
            if line.strip() == '}':
                # End of tenants block
                in_tenants_block = False
                output_lines.append(line)
                continue
            
            # Detect tenant key (e.g., "msp-acme" = {)
            if '= {' in line and not line.strip().startswith('#'):
                tenant_name = line.split('=')[0].strip().strip('"')
                current_tenant = tenant_name
                tenant_buffer = [line]
            elif current_tenant:
                tenant_buffer.append(line)
                if line.strip() == '}':
                    # End of this tenant
                    if current_tenant in tenants_to_keep:
                        output_lines.extend(tenant_buffer)
                    current_tenant = None
                    tenant_buffer = []
            else:
                output_lines.append(line)
        else:
            output_lines.append(line)
    
    return '\n'.join(output_lines)


def main():
    parser = argparse.ArgumentParser(
        description='Migrate Terraform-managed tenants to API management'
    )
    parser.add_argument('--profile', default='default', help='AWS profile')
    parser.add_argument('--region', default='us-east-1', help='AWS region')
    parser.add_argument('--environment', default='dev', help='Environment (dev/staging/prod)')
    parser.add_argument('--table', default=None, help='Tenant registry table name')
    parser.add_argument('--tenant', help='Migrate specific tenant')
    parser.add_argument('--all', action='store_true', help='Migrate all ready tenants')
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help='Show what would happen without making changes (default)')
    parser.add_argument('--confirm', action='store_true',
                       help='Actually execute the migration (with --all)')
    parser.add_argument('--generate-tf-config', action='store_true',
                       help='Generate updated terraform.tfvars')
    parser.add_argument('--tfvars-path', default='terraform.tfvars',
                       help='Path to terraform.tfvars')
    
    args = parser.parse_args()
    
    if not args.tenant and not args.all and not args.generate_tf_config:
        parser.error("Must specify --tenant, --all, or --generate-tf-config")
    
    # Set up AWS session
    session = get_aws_session(args.profile, args.region)
    dynamodb = session.resource('dynamodb')
    bedrock_agent = session.client('bedrock-agent')
    secrets_client = session.client('secretsmanager')
    
    table_name = args.table or f"{args.environment}-msp-triage-tenant-registry"
    
    print(f"\n{'='*70}")
    print(f"Tenant Migration Script: Terraform → API Management")
    print(f"{'='*70}")
    print(f"Environment: {args.environment}")
    print(f"Region:      {args.region}")
    print(f"Table:       {table_name}")
    print(f"Mode:        {'DRY RUN' if args.dry_run else 'LIVE MIGRATION'}")
    print(f"{'='*70}\n")
    
    # Get all tenants
    tenants = get_all_terraform_tenants(dynamodb, table_name)
    print(f"Found {len(tenants)} tenants in registry\n")
    
    # Filter to specific tenant or all
    if args.tenant:
        tenants = [t for t in tenants if t.get('tenant_id') == args.tenant]
        if not tenants:
            print(f"ERROR: Tenant '{args.tenant}' not found")
            sys.exit(1)
    
    # Verify each tenant
    ready_tenants = []
    not_ready_tenants = []
    
    for tenant in tenants:
        tenant_id = tenant.get('tenant_id')
        is_ready, issues = verify_tenant_ready_for_migration(
            tenant, bedrock_agent, secrets_client, args.environment
        )
        
        if is_ready:
            ready_tenants.append(tenant)
        else:
            not_ready_tenants.append((tenant, issues))
    
    print(f"Ready for migration:     {len(ready_tenants)}")
    print(f"Not ready:               {len(not_ready_tenants)}")
    print()
    
    if not_ready_tenants:
        print("Tenants not ready for migration:")
        for tenant, issues in not_ready_tenants:
            print(f"  - {tenant.get('tenant_id')}: {', '.join(issues)}")
        print()
    
    if not ready_tenants:
        print("No tenants ready for migration. Exiting.")
        sys.exit(0)
    
    # Generate migration plan
    print(f"{'='*70}")
    print("MIGRATION PLAN")
    print(f"{'='*70}\n")
    
    all_commands = []
    tenants_to_migrate = []
    
    for tenant in ready_tenants:
        tenant_id = tenant.get('tenant_id')
        tenants_to_migrate.append(tenant_id)
        
        print(f"Tenant: {tenant_id}")
        print(f"  Display Name: {tenant.get('display_name')}")
        print(f"  Agent ID:     {tenant.get('agent_id')}")
        print(f"  Alias ID:     {tenant.get('agent_alias_id')}")
        print(f"  Status:       {tenant.get('status')}")
        print()
        
        commands = generate_terraform_state_removal_commands(tenant_id, args.environment)
        all_commands.extend(commands)
    
    # Show Terraform state removal commands
    print(f"{'='*70}")
    print("TERRAFORM STATE REMOVAL COMMANDS")
    print(f"{'='*70}\n")
    
    for cmd in all_commands:
        print(cmd)
    
    print()
    
    # Generate terraform.tfvars update if requested
    if args.generate_tf_config:
        print(f"{'='*70}")
        print("UPDATED TERRAFORM.TVARS")
        print(f"{'='*70}\n")
        
        # Tenants to keep in Terraform = all tenants minus those being migrated
        all_tenant_ids = [t.get('tenant_id') for t in tenants]
        tenants_to_keep = [t for t in all_tenant_ids if t not in tenants_to_migrate]
        
        new_tfvars = generate_updated_tfvars(tenants_to_keep, args.tfvars_path)
        print(new_tfvars)
        
        output_path = f"{args.tfvars_path}.migrated"
        with open(output_path, 'w') as f:
            f.write(new_tfvars)
        print(f"\nSaved to: {output_path}")
    
    # Execute migration if confirmed
    if not args.dry_run and args.confirm and all_commands:
        print(f"\n{'='*70}")
        print("EXECUTING MIGRATION")
        print(f"{'='*70}\n")
        
        for cmd in all_commands:
            print(f"Running: {cmd}")
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"  ERROR: {result.stderr}")
            else:
                print(f"  OK")
        
        # Update tenant records to mark as API-managed
        print(f"\nUpdating tenant records...")
        table = dynamodb.Table(table_name)
        for tenant_id in tenants_to_migrate:
            try:
                table.update_item(
                    Key={'tenant_id': tenant_id},
                    UpdateExpression='SET management_mode = :mode, migrated_at = :ts',
                    ExpressionAttributeValues={
                        ':mode': 'api',
                        ':ts': datetime.now(timezone.utc).isoformat(),
                    }
                )
                print(f"  ✓ {tenant_id} marked as API-managed")
            except Exception as e:
                print(f"  ✗ {tenant_id} failed: {e}")
        
        print(f"\n{'='*70}")
        print("MIGRATION COMPLETE")
        print(f"{'='*70}")
        print(f"Migrated {len(tenants_to_migrate)} tenants to API management")
        print(f"\nNext steps:")
        print(f"  1. Run 'terraform plan' to verify no unexpected changes")
        print(f"  2. Run 'terraform apply' to clean up any orphaned resources")
        print(f"  3. Test onboarding a new tenant via the API")
        print(f"  4. Verify existing tenants still work via the Teams bot")
    
    elif args.dry_run:
        print(f"\n{'='*70}")
        print("DRY RUN COMPLETE")
        print(f"{'='*70}")
        print(f"\nNo changes were made. To execute the migration:")
        print(f"  1. Review the commands above")
        print(f"  2. Run: python {sys.argv[0]} --profile {args.profile} \\")
        print(f"          --environment {args.environment} --all --confirm")
        print(f"\nRollback procedure (if needed):")
        print(f"  1. Add migrated tenants back to var.tenants in terraform.tfvars")
        print(f"  2. Run 'terraform import' for each resource:")
        for tenant_id in tenants_to_migrate:
            print(f"     # Tenant: {tenant_id}")
            print(f"     terraform import 'aws_bedrockagent_agent.it_concierge[\"{tenant_id}\"]' <agent_id>")
        print(f"\n⚠️  IMPORTANT: Before running the live migration:")
        print(f"  - Back up your Terraform state: terraform state pull > backup.tfstate")
        print(f"  - Test in a non-production environment first")
        print(f"  - Ensure you have a rollback plan")


if __name__ == '__main__':
    main()