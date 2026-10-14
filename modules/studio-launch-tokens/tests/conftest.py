import base64
import json
import os
import sys
import threading
from pathlib import Path
from urllib.parse import urlencode

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambda"))

import common  # noqa: E402

TABLE = "test-studio-launch-tokens"
DOMAIN = "d-test123"
PROFILE = "data-scientist-1"
API_HOST = "abc123.execute-api.us-east-1.amazonaws.com"
PRESIGNED = f"https://{DOMAIN}.studio.us-east-1.sagemaker.aws/auth?token=presigned"


class FakeSageMaker:
    def __init__(self):
        self.profiles = {(DOMAIN, PROFILE)}
        self.fail_presign = False
        self.presign_calls = []
        self._lock = threading.Lock()

    def describe_user_profile(self, DomainId, UserProfileName):
        if (DomainId, UserProfileName) not in self.profiles:
            raise ClientError({"Error": {"Code": "ResourceNotFound", "Message": "nope"}}, "DescribeUserProfile")
        return {"DomainId": DomainId, "UserProfileName": UserProfileName}

    def create_presigned_domain_url(self, **kwargs):
        with self._lock:
            self.presign_calls.append(kwargs)
        if self.fail_presign:
            raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "CreatePresignedDomainUrl")
        return {"AuthorizedUrl": PRESIGNED}


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.setenv("DOMAIN_IDS", DOMAIN)
    monkeypatch.setenv("PRESIGN_EXPIRES_SECONDS", "15")
    monkeypatch.setenv("SESSION_EXPIRATION_SECONDS", "43200")
    monkeypatch.delenv("ALLOWED_CIDRS", raising=False)
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "token_hash", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "token_hash", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        fake = FakeSageMaker()
        common._table = None
        common._sagemaker = fake
        yield fake
        common._table = None
        common._sagemaker = None


def http_event(method, path, query=None, body=None, headers=None, ip="203.0.113.10", b64=False, iam_arn=None):
    hdrs = {"host": API_HOST, "user-agent": "pytest-browser"}
    hdrs.update(headers or {})
    if body is not None and b64:
        body = base64.b64encode(body.encode()).decode()
    ctx = {"domainName": API_HOST, "http": {"method": method, "path": path, "sourceIp": ip}}
    if iam_arn:
        ctx["authorizer"] = {"iam": {"userArn": iam_arn}}
    return {
        "rawPath": path,
        "queryStringParameters": query,
        "headers": hdrs,
        "body": body,
        "isBase64Encoded": b64,
        "requestContext": ctx,
    }


def mint_event(payload, iam_arn="arn:aws:iam::111122223333:user/admin"):
    return http_event("POST", "/tokens", body=json.dumps(payload), iam_arn=iam_arn)


def launch_post(token, **kw):
    return http_event("POST", "/launch", body=urlencode({"token": token}),
                      headers={"content-type": "application/x-www-form-urlencoded", **kw.pop("headers", {})}, **kw)
