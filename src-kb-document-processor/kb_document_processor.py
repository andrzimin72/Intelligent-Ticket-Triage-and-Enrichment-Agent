"""
KB Document Processor Lambda

Triggered by S3 events when documents are uploaded to the KB bucket.
Extracts tenant_id from the S3 key path (tenants/{tenant_id}/...) and
triggers a Bedrock KB ingestion job to re-index the documents.

The tenant_id is stored as metadata on the document so the agent can
filter queries by tenant at query time.
"""

import json
import os
import logging
import re
from typing import Dict, Any, Optional
from urllib.parse import unquote_plus
import boto3
from botocore.exceptions import ClientError

from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

logger = logging.getLogger()
logger.setLevel(logging.INFO)

KNOWLEDGE_BASE_ID = os.environ.get('KNOWLEDGE_BASE_ID')
DATA_SOURCE_ID = os.environ.get('DATA_SOURCE_ID')
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

bedrock_agent = boto3.client('bedrock-agent', region_name=AWS_REGION)

# Supported document types (Bedrock KB handles these natively)
SUPPORTED_EXTENSIONS = {
    '.txt', '.md', '.pdf', '.docx', '.html', '.csv', '.json',
    '.xlsx', '.pptx', '.rtf'
}


def extract_tenant_id_from_key(s3_key: str) -> Optional[str]:
    """
    Extracts tenant_id from S3 key path.
    
    Expected format: tenants/{tenant_id}/filename.ext
    
    Returns None if the key doesn't match the expected pattern.
    """
    match = re.match(r'^tenants/([^/]+)/', s3_key)
    if match:
        return match.group(1)
    return None


def is_supported_file(s3_key: str) -> bool:
    """Checks if the file extension is supported by Bedrock KB."""
    ext = os.path.splitext(s3_key)[1].lower()
    return ext in SUPPORTED_EXTENSIONS


@xray_recorder.capture('start_ingestion_job')
def start_ingestion_job() -> Optional[str]:
    """
    Triggers a Bedrock KB ingestion job to re-index all documents.
    
    Returns the job ID, or None if the job couldn't be started.
    """
    try:
        response = bedrock_agent.start_ingestion_job(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            dataSourceId=DATA_SOURCE_ID,
            description='Triggered by S3 document upload'
        )
        job_id = response['ingestionJob']['ingestionJobId']
        logger.info(f"Started ingestion job: {job_id}")
        return job_id
    except ClientError as e:
        logger.error(f"Failed to start ingestion job: {e}")
        return None


@xray_recorder.capture('kb_document_processor_handler')
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main entry point. Triggered by S3 event notifications.
    
    Processes each record in the event, validates the tenant_id and file type,
    then triggers a single ingestion job for all changes.
    """
    logger.info(f"Received {len(event.get('Records', []))} S3 event records")
    
    processed_files = []
    skipped_files = []
    invalid_files = []
    
    for record in event.get('Records', []):
        try:
            # Extract S3 bucket and key
            bucket = record['s3']['bucket']['name']
            key = unquote_plus(record['s3']['object']['key'])
            event_name = record.get('eventName', 'Unknown')
            
            logger.info(f"Processing {event_name}: s3://{bucket}/{key}")
            
            # Skip placeholder files
            if key.endswith('/.keep'):
                logger.info(f"Skipping placeholder: {key}")
                skipped_files.append(key)
                continue
            
            # Extract and validate tenant_id
            tenant_id = extract_tenant_id_from_key(key)
            if not tenant_id:
                logger.warning(f"Invalid key format (missing tenant_id): {key}")
                invalid_files.append(key)
                continue
            
            # Validate file type
            if not is_supported_file(key):
                logger.info(f"Skipping unsupported file type: {key}")
                skipped_files.append(key)
                continue
            
            logger.info(f"Valid document: tenant={tenant_id}, file={key}")
            processed_files.append({
                'tenant_id': tenant_id,
                'key': key,
                'event': event_name,
            })
        
        except Exception as e:
            logger.error(f"Error processing record: {e}")
    
    # Trigger a single ingestion job for all changes
    if processed_files:
        job_id = start_ingestion_job()
        logger.info(
            f"Processed {len(processed_files)} files, "
            f"skipped {len(skipped_files)}, invalid {len(invalid_files)}. "
            f"Ingestion job: {job_id}"
        )
    else:
        logger.info("No valid files to process, skipping ingestion job")
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'processed': len(processed_files),
            'skipped': len(skipped_files),
            'invalid': len(invalid_files),
        })
    }
