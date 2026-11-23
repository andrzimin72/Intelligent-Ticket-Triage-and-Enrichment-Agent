import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from moto import mock_aws
import boto3


@pytest.fixture
def authorizer_env():
    with patch.dict(os.environ, {
        "AWS_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "WEBHOOK_SECRET_NAME": "test/msp/webhook/token",
        "HEADER_NAME": "x-psa-token",
    }):
        yield


@pytest.fixture
def authorizer_module(authorizer_env):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src_authorizer'))
    with mock_aws():
        sm = boto3.client("secretsmanager", region_name="us-east-1")
        sm.create_secret(Name="test/msp/webhook/token", SecretString=json.dumps({"TOKEN": "valid-token"}))

        import importlib
        import authorizer
        importlib.reload(authorizer)
        yield authorizer


def test_valid_token(authorizer_module):
    event = {"headers": {"x-psa-token": "valid-token"}}
    result = authorizer_module.lambda_handler(event, None)
    assert result["isAuthorized"] is True


def test_invalid_token(authorizer_module):
    event = {"headers": {"x-psa-token": "wrong-token"}}
    result = authorizer_module.lambda_handler(event, None)
    assert result["isAuthorized"] is False


def test_missing_header(authorizer_module):
    event = {"headers": {}}
    result = authorizer_module.lambda_handler(event, None)
    assert result["isAuthorized"] is False


def test_empty_token(authorizer_module):
    event = {"headers": {"x-psa-token": ""}}
    result = authorizer_module.lambda_handler(event, None)
    assert result["isAuthorized"] is False