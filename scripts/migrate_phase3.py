"""
Migration script for Phase 3: Tenant-scoped password reset tokens.

Run this AFTER deploying the Terraform changes. It backfills existing
password reset tokens with tenant_id = 'default'.

Usage:
    python scripts/migrate_phase3.py --profile default --region us-east-1 \\
        --table msp-triage-dev-password-reset-tokens
"""

import argparse
import boto3
from botocore.exceptions import ClientError


def backfill_tenant_id(table_name: str, default_tenant: str = 'default'):
    """Adds tenant_id = default to all existing token records."""
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(table_name)
    
    print(f"Scanning table {table_name} for records without tenant_id...")
    
    scanned = 0
    updated = 0
    
    response = table.scan(
        FilterExpression='attribute_not_exists(tenant_id)',
        ProjectionExpression='#t',
        ExpressionAttributeNames={'#t': 'token'}
    )
    
    items = response.get('Items', [])
    
    while 'LastEvaluatedKey' in response:
        response = table.scan(
            FilterExpression='attribute_not_exists(tenant_id)',
            ProjectionExpression='#t',
            ExpressionAttributeNames={'#t': 'token'},
            ExclusiveStartKey=response['LastEvaluatedKey']
        )
        items.extend(response.get('Items', []))
    
    print(f"Found {len(items)} records to backfill")
    
    for item in items:
        token = item['token']
        try:
            table.update_item(
                Key={'token': token},
                UpdateExpression='SET tenant_id = :tid',
                ExpressionAttributeValues={':tid': default_tenant}
            )
            updated += 1
            if updated % 100 == 0:
                print(f"  Updated {updated}/{len(items)} records...")
        except ClientError as e:
            print(f"  Failed to update token {token[:8]}...: {e}")
        
        scanned += 1
    
    print(f"Backfill complete: {updated}/{scanned} records updated")


def main():
    parser = argparse.ArgumentParser(description='Migrate to Phase 3 tenant-scoped password reset tokens')
    parser.add_argument('--profile', default='default', help='AWS profile')
    parser.add_argument('--region', default='us-east-1', help='AWS region')
    parser.add_argument('--table', required=True, help='Password reset tokens table name')
    parser.add_argument('--default-tenant', default='default', help='Default tenant ID')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without doing it')
    
    args = parser.parse_args()
    
    boto3.setup_default_session(profile_name=args.profile, region_name=args.region)
    
    if args.dry_run:
        print("DRY RUN — no changes will be made")
        print(f"  Would backfill tenant_id='{args.default_tenant}' in {args.table}")
        return
    
    # Backfill tenant_id
    backfill_tenant_id(args.table, args.default_tenant)
    
    print("\nMigration complete!")
    print("Next steps:")
    print("  1. Deploy the updated Lambda code")
    print("  2. Trigger a password reset to verify tenant-scoped tokens")
    print("  3. Check CloudWatch logs for tenant-scoped operations")


if __name__ == '__main__':
    main()