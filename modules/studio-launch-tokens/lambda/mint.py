"""POST /tokens (IAM-authenticated): create a one-time Studio launch link.

Request:  {"domainId": "d-...", "userProfileName": "...", "ttlMinutes": 15, "issuedTo": "a@b.com"}
Response: {"launchUrl": "https://.../launch?token=...", "expiresAt": "...", ...}
"""

import json
import os
import secrets
import time
from datetime import datetime, timezone

from botocore.exceptions import ClientError

from common import STATUS_ISSUED, decode_body, env_list, hash_token, sagemaker, table


def handler(event, context):
    caller = (event["requestContext"].get("authorizer") or {}).get("iam", {}).get("userArn", "unknown")

    try:
        body = json.loads(decode_body(event) or "{}")
    except ValueError:
        return respond(400, {"error": "Body must be JSON"})
    if not isinstance(body, dict):
        return respond(400, {"error": "Body must be a JSON object"})

    domain_id = str(body.get("domainId") or "").strip()
    profile = str(body.get("userProfileName") or "").strip()
    if not domain_id or not profile:
        return respond(400, {"error": "domainId and userProfileName are required"})
    if domain_id not in env_list("DOMAIN_IDS"):
        return respond(403, {"error": f"Domain {domain_id} is not enabled for launch links"})

    max_ttl = int(os.environ.get("MAX_TTL_MINUTES", "60"))
    raw_ttl = body.get("ttlMinutes")
    if raw_ttl is None:
        raw_ttl = os.environ.get("DEFAULT_TTL_MINUTES", "15")
    try:
        ttl_minutes = int(raw_ttl)
    except (TypeError, ValueError):
        return respond(400, {"error": "ttlMinutes must be a whole number"})
    if not 1 <= ttl_minutes <= max_ttl:
        return respond(400, {"error": f"ttlMinutes must be between 1 and {max_ttl}"})

    try:
        sagemaker().describe_user_profile(DomainId=domain_id, UserProfileName=profile)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("ResourceNotFound", "ValidationException"):
            return respond(404, {"error": f"User profile {profile} not found in {domain_id}"})
        raise

    token = secrets.token_urlsafe(32)
    now = int(time.time())
    expires_at = now + ttl_minutes * 60
    audit_days = int(os.environ.get("AUDIT_RETENTION_DAYS", "90"))
    table().put_item(
        Item={
            "token_hash": hash_token(token),
            "domain_id": domain_id,
            "user_profile_name": profile,
            "issued_to": str(body.get("issuedTo") or profile)[:256],
            "issued_by": caller,
            "created_at": now,
            "expires_at": expires_at,
            # DynamoDB TTL deletes on purge_at, not expires_at, so used rows stay for auditing.
            "purge_at": expires_at + audit_days * 86400,
            "status": STATUS_ISSUED,
        },
        ConditionExpression="attribute_not_exists(token_hash)",
    )

    domain_name = event["requestContext"]["domainName"]
    return respond(201, {
        "launchUrl": f"https://{domain_name}/launch?token={token}",
        "expiresAt": datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
        "domainId": domain_id,
        "userProfileName": profile,
    })


def respond(status, data):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(data),
    }
