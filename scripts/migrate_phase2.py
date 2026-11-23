"""
Migration script for Phase 2: Tenant-scoped agent feedback.

Run this AFTER deploying the Terraform changes but BEFORE enabling the
new code paths. It does three things:

1. Backfills existing feedback records with tenant_id = 'default'
2. Moves agent-examples.json to tenants/default/agent-examples.json
3. Deletes the orphaned global agent-examples.json

Usage:
    python scripts/migrate_phase2.py --profile default --region us-east-1 \\
        --table msp-triage-dev-agent-feedback \\
        --bucket msp-triage-dev-agent-schemas-123456789012
"""

import argparse
import json
import boto3
from botocore.exceptions import ClientError


def backfill_tenant_id(table_name: str, default_tenant: str = 'default'):
    """Adds tenant_id = default to all existing feedback records."""
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(table_name)
    
    print(f"Scanning table {table_name} for records without tenant_id...")
    
    scanned = 0
    updated = 0
    
    response = table.scan(
        FilterExpression='attribute_not_exists(tenant_id)',
        ProjectionExpression='feedback_id'
    )
    
    items = response.get('Items', [])
    
    while 'LastEvaluatedKey' in response:
        response = table.scan(
            FilterExpression='attribute_not_exists(tenant_id)',
            ProjectionExpression='feedback_id',
            ExclusiveStartKey=response['LastEvaluatedKey']
        )
        items.extend(response.get('Items', []))
    
    print(f"Found {len(items)} records to backfill")
    
    for item in items:
        feedback_id = item['feedback_id']
        try:
            table.update_item(
                Key={'feedback_id': feedback_id},
                UpdateExpression='SET tenant_id = :tid',
                ExpressionAttributeValues={':tid': default_tenant}
            )
            updated += 1
            if updated % 100 == 0:
                print(f"  Updated {updated}/{len(items)} records...")
        except ClientError as e:
            print(f"  Failed to update {feedback_id}: {e}")
        
        scanned += 1
    
    print(f"Backfill complete: {updated}/{scanned} records updated")


def move_s3_file(bucket: str, old_key: str, new_key: str):
    """Moves an S3 object from old_key to new_key."""
    s3 = boto3.client('s3')
    
    print(f"Moving s3://{bucket}/{old_key} → s3://{bucket}/{new_key}")
    
    try:
        # Copy to new location
        s3.copy_object(
            Bucket=bucket,
            CopySource={'Bucket': bucket, 'Key': old_key},
            Key=new_key,
        )
        print(f"  Copied successfully")
        
        # Delete old location
        s3.delete_object(Bucket=bucket, Key=old_key)
        print(f"  Deleted old file")
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            print(f"  Old file doesn't exist — nothing to move")
        else:
            print(f"  Failed: {e}")
            raise


def main():
    parser = argparse.ArgumentParser(description='Migrate to Phase 2 tenant-scoped feedback')
    parser.add_argument('--profile', default='default', help='AWS profile')
    parser.add_argument('--region', default='us-east-1', help='AWS region')
    parser.add_argument('--table', required=True, help='Agent feedback table name')
    parser.add_argument('--bucket', required=True, help='Agent schemas bucket name')
    parser.add_argument('--default-tenant', default='default', help='Default tenant ID')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without doing it')
    
    args = parser.parse_args()
    
    boto3.setup_default_session(profile_name=args.profile, region_name=args.region)
    
    if args.dry_run:
        print("DRY RUN — no changes will be made")
        print(f"  Would backfill tenant_id='{args.default_tenant}' in {args.table}")
        print(f"  Would move {args.bucket}/agent-examples.json → {args.bucket}/tenants/{args.default_tenant}/agent-examples.json")
        return
    
    # Step 1: Backfill tenant_id
    backfill_tenant_id(args.table, args.default_tenant)
    
    # Step 2: Move S3 file
    old_key = 'agent-examples.json'
    new_key = f'tenants/{args.default_tenant}/agent-examples.json'
    move_s3_file(args.bucket, old_key, new_key)
    
    print("\nMigration complete!")
    print("Next steps:")
    print("  1. Deploy the updated Lambda code")
    print("  2. Trigger agent_feedback_sync to verify it works")
    print("  3. Check CloudWatch logs for tenant-scoped operations")


if __name__ == '__main__':
    main()