"""Helpers shared by the launch and mint Lambdas."""

import base64
import hashlib
import os
import re

import boto3

# secrets.token_urlsafe(32) -> 43 URL-safe characters (256 bits).
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")

STATUS_ISSUED = "ISSUED"
STATUS_USED = "USED"
STATUS_FAILED = "FAILED"
STATUS_REVOKED = "REVOKED"

_table = None
_sagemaker = None


def table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _table


def sagemaker():
    global _sagemaker
    if _sagemaker is None:
        _sagemaker = boto3.client("sagemaker")
    return _sagemaker


def hash_token(token):
    """Only the hash is stored, so a table leak does not leak usable tokens."""
    return hashlib.sha256(token.encode()).hexdigest()


def valid_token_format(token):
    return bool(token) and bool(TOKEN_RE.match(token))


def decode_body(event):
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode()
    return body


def env_list(name):
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]
