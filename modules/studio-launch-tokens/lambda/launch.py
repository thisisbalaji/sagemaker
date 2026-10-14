"""GET /launch shows an "Open Studio" button; POST /launch burns the token and redirects.

The GET never touches the token, so link scanners and chat previews that
prefetch URLs cannot use it up. Only the button's POST consumes it.
"""

import html
import ipaddress
import json
import logging
import os
import time
from urllib.parse import parse_qs, urlparse

from botocore.exceptions import BotoCoreError, ClientError

from common import (
    STATUS_FAILED,
    STATUS_ISSUED,
    STATUS_USED,
    decode_body,
    env_list,
    hash_token,
    sagemaker,
    table,
    valid_token_format,
)

log = logging.getLogger()
log.setLevel(logging.INFO)

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
}

GONE_MESSAGE = "This link is invalid, has already been used, or has expired. Ask for a new link."


def handler(event, context):
    method = event["requestContext"]["http"]["method"]
    if method == "GET":
        return show_button(event)
    if method == "POST":
        return launch(event)
    return page(405, "Not allowed", "Unsupported request.")


def show_button(event):
    token = (event.get("queryStringParameters") or {}).get("token", "")
    if not valid_token_format(token):
        return page(400, "Link not valid", GONE_MESSAGE)
    action = html.escape(event.get("rawPath") or "/launch", quote=True)
    body = (
        "<p>Click the button to open SageMaker AI Studio. This link works once.</p>"
        f'<form method="post" action="{action}">'
        f'<input type="hidden" name="token" value="{html.escape(token, quote=True)}">'
        '<button type="submit">Open Studio</button></form>'
    )
    return page(200, "Open SageMaker AI Studio", body, raw_html=True)


def launch(event):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    source_ip = event["requestContext"]["http"].get("sourceIp", "")
    user_agent = (headers.get("user-agent") or "")[:256]

    origin = headers.get("origin")
    host = headers.get("host") or event["requestContext"].get("domainName")
    if origin and origin != "null" and urlparse(origin).netloc != host:
        audit("blocked_origin", ip=source_ip, origin=origin)
        return page(403, "Not allowed", "This request came from another site.")

    if not ip_allowed(source_ip):
        # Checked before burning, so a user off-network can retry once on VPN.
        audit("blocked_ip", ip=source_ip)
        return page(403, "Not allowed", "Studio can only be opened from the company network.")

    token = (parse_qs(decode_body(event)).get("token") or [""])[0]
    if not valid_token_format(token):
        audit("bad_format", ip=source_ip)
        return page(410, "Link not valid", GONE_MESSAGE)

    token_hash = hash_token(token)
    now = int(time.time())
    try:
        item = table().update_item(
            Key={"token_hash": token_hash},
            UpdateExpression="SET #s = :used, used_at = :now, used_ip = :ip, used_ua = :ua",
            # Fails for unknown, used, revoked, failed and expired tokens alike.
            ConditionExpression="#s = :issued AND expires_at > :now",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":used": STATUS_USED,
                ":issued": STATUS_ISSUED,
                ":now": now,
                ":ip": source_ip,
                ":ua": user_agent,
            },
            ReturnValues="ALL_NEW",
        )["Attributes"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            audit("rejected", token_hash=token_hash, ip=source_ip)
            return page(410, "Link not valid", GONE_MESSAGE)
        raise

    domain_id, profile = item["domain_id"], item["user_profile_name"]
    try:
        url = sagemaker().create_presigned_domain_url(
            DomainId=domain_id,
            UserProfileName=profile,
            ExpiresInSeconds=int(os.environ.get("PRESIGN_EXPIRES_SECONDS", "15")),
            SessionExpirationDurationInSeconds=int(os.environ.get("SESSION_EXPIRATION_SECONDS", "43200")),
        )["AuthorizedUrl"]
    except (ClientError, BotoCoreError) as e:
        mark_failed(token_hash, str(e))
        audit("presign_failed", token_hash=token_hash, domain_id=domain_id, profile=profile, ip=source_ip, error=str(e))
        return page(502, "Could not open Studio", "Something went wrong opening Studio. Ask for a new link.")

    audit("launched", token_hash=token_hash, domain_id=domain_id, profile=profile, ip=source_ip)
    return {"statusCode": 302, "headers": {**SECURITY_HEADERS, "Location": url}, "body": ""}


def ip_allowed(source_ip):
    cidrs = env_list("ALLOWED_CIDRS")
    if not cidrs:
        return True
    try:
        ip = ipaddress.ip_address(source_ip)
    except ValueError:
        return False
    return any(ip in ipaddress.ip_network(c) for c in cidrs)


def mark_failed(token_hash, error):
    try:
        table().update_item(
            Key={"token_hash": token_hash},
            UpdateExpression="SET #s = :failed, failure = :err",
            ConditionExpression="#s = :used",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":failed": STATUS_FAILED, ":used": STATUS_USED, ":err": error[:500]},
        )
    except ClientError:
        log.exception("Could not mark token as failed")


def audit(outcome, token_hash=None, **fields):
    # Never log the raw token; a hash prefix is enough to find the DynamoDB row.
    if token_hash:
        fields["token_hash_prefix"] = token_hash[:12]
    log.info(json.dumps({"event": "studio_launch", "outcome": outcome, **fields}))


def page(status, title, message, raw_html=False):
    content = message if raw_html else f"<p>{html.escape(message)}</p>"
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body{{font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:520px;margin:64px auto;padding:0 16px;color:#1b1f24;background:#f6f7f9}}
button{{font:inherit;font-weight:600;padding:10px 20px;border:0;border-radius:6px;background:#1f6feb;color:#fff;cursor:pointer}}
@media(prefers-color-scheme:dark){{body{{background:#0f1216;color:#e6e9ee}}button{{background:#4c8dff;color:#0b0d10}}}}
</style></head>
<body><h1>{html.escape(title)}</h1>{content}</body></html>"""
    return {
        "statusCode": status,
        "headers": {**SECURITY_HEADERS, "Content-Type": "text/html; charset=utf-8"},
        "body": body,
    }
