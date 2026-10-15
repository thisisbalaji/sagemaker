import boto3
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from moto import mock_aws

from app.config import Settings
from app.main import create_app
from app.services import Portal
from app.store import Store

DOMAIN = "d-test123"
OTHER_DOMAIN = "d-other456"
TABLE = "test-ml-portal"


def create_table(dynamodb):
    dynamodb.create_table(
        TableName=TABLE,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": n, "AttributeType": "S"}
                              for n in ("pk", "sk", "gsi1pk", "gsi1sk", "gsi2pk", "gsi2sk")],
        GlobalSecondaryIndexes=[
            {"IndexName": "gsi1", "Projection": {"ProjectionType": "ALL"},
             "KeySchema": [{"AttributeName": "gsi1pk", "KeyType": "HASH"}, {"AttributeName": "gsi1sk", "KeyType": "RANGE"}]},
            {"IndexName": "gsi2", "Projection": {"ProjectionType": "ALL"},
             "KeySchema": [{"AttributeName": "gsi2pk", "KeyType": "HASH"}, {"AttributeName": "gsi2sk", "KeyType": "RANGE"}]},
        ],
    )


def _err(code, msg, op):
    return ClientError({"Error": {"Code": code, "Message": msg}}, op)


class FakeSageMaker:
    def __init__(self):
        self.domains = {DOMAIN: ("team-domain", "IAM"), OTHER_DOMAIN: ("other-domain", "IAM")}
        self.profiles = {}
        self.role_not_ready = 0  # number of create_user_profile calls to reject as "role not assumable"
        self.fail_create = None
        self.presign_calls = []

    def get_paginator(self, name):
        assert name == "list_domains"
        fake = self

        class P:
            def paginate(self):
                yield {"Domains": [{"DomainId": d, "DomainName": n, "Status": "InService"}
                                   for d, (n, _) in fake.domains.items()]}
        return P()

    def describe_domain(self, DomainId):
        return {"DomainId": DomainId, "AuthMode": self.domains[DomainId][1]}

    def create_user_profile(self, DomainId, UserProfileName, UserSettings, Tags):
        if self.role_not_ready:
            self.role_not_ready -= 1
            raise _err("ValidationException", "The execution role cannot be assumed", "CreateUserProfile")
        if self.fail_create:
            raise _err(self.fail_create, "boom", "CreateUserProfile")
        if (DomainId, UserProfileName) in self.profiles:
            raise _err("ResourceInUse", "exists", "CreateUserProfile")
        self.profiles[(DomainId, UserProfileName)] = {"Status": "InService", "UserSettings": UserSettings, "Tags": Tags}

    def describe_user_profile(self, DomainId, UserProfileName):
        p = self.profiles.get((DomainId, UserProfileName))
        if not p:
            raise _err("ResourceNotFound", "nope", "DescribeUserProfile")
        return {"Status": p["Status"]}

    def create_presigned_domain_url(self, **kwargs):
        self.presign_calls.append(kwargs)
        return {"AuthorizedUrl": f"https://{kwargs['DomainId']}.studio.us-east-1.sagemaker.aws/auth?token=x"}


@pytest.fixture
def env(monkeypatch):
    for k, v in {"AWS_DEFAULT_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "testing",
                 "AWS_SECRET_ACCESS_KEY": "testing", "MOTO_IAM_LOAD_MANAGED_POLICIES": "true"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with mock_aws():
        create_table(boto3.client("dynamodb"))
        settings = Settings(table_name=TABLE, session_secret="test-secret", mock_auth=True,
                            profile_create_retry_delay=0)
        store = Store(boto3.resource("dynamodb").Table(TABLE))
        store.put_user("alice", "Alice", "alice@example.com")
        store.put_user("bob", "Bob", "bob@example.com")
        store.put_user("dana", "Dana", "dana@example.com", [DOMAIN])
        store.put_user("olga", "Olga", "olga@example.com", [OTHER_DOMAIN])
        sm = FakeSageMaker()
        iam = boto3.client("iam")
        portal = Portal(settings, store, sm, iam, sleep=lambda s: None)
        app = create_app(settings, portal)

        def client(user_id=None):
            c = TestClient(app)
            if user_id:
                assert c.post("/api/auth/login", json={"user_id": user_id}).status_code == 200
            return c

        yield type("Env", (), {"client": staticmethod(client), "sm": sm, "iam": iam, "store": store, "portal": portal})
