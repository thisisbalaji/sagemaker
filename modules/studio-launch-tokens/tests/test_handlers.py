import json
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import pytest

import common
import launch
import mint
from conftest import API_HOST, DOMAIN, PRESIGNED, PROFILE, http_event, launch_post, mint_event


def mint_token(**overrides):
    payload = {"domainId": DOMAIN, "userProfileName": PROFILE, **overrides}
    resp = mint.handler(mint_event(payload), None)
    assert resp["statusCode"] == 201, resp
    url = json.loads(resp["body"])["launchUrl"]
    return parse_qs(urlparse(url).query)["token"][0]


def row(token):
    return common.table().get_item(Key={"token_hash": common.hash_token(token)}).get("Item")


# ---------------------------------------------------------------- mint


def test_mint_stores_only_hash_and_returns_launch_url(aws):
    resp = mint.handler(mint_event({"domainId": DOMAIN, "userProfileName": PROFILE, "issuedTo": "a@corp.com"}), None)
    assert resp["statusCode"] == 201
    data = json.loads(resp["body"])
    url = urlparse(data["launchUrl"])
    assert (url.scheme, url.netloc, url.path) == ("https", API_HOST, "/launch")
    token = parse_qs(url.query)["token"][0]
    assert common.valid_token_format(token)

    item = row(token)
    assert item["status"] == "ISSUED"
    assert item["issued_to"] == "a@corp.com"
    assert item["issued_by"] == "arn:aws:iam::111122223333:user/admin"
    assert item["expires_at"] - item["created_at"] == 15 * 60
    assert item["purge_at"] == item["expires_at"] + 90 * 86400
    assert token not in json.dumps(item, default=str), "raw token must never be stored"


@pytest.mark.parametrize("payload, status", [
    ({"userProfileName": PROFILE}, 400),
    ({"domainId": DOMAIN}, 400),
    ({"domainId": "d-other", "userProfileName": PROFILE}, 403),
    ({"domainId": DOMAIN, "userProfileName": "nobody"}, 404),
    ({"domainId": DOMAIN, "userProfileName": PROFILE, "ttlMinutes": 0}, 400),
    ({"domainId": DOMAIN, "userProfileName": PROFILE, "ttlMinutes": 61}, 400),
    ({"domainId": DOMAIN, "userProfileName": PROFILE, "ttlMinutes": "abc"}, 400),
])
def test_mint_rejects_bad_requests(aws, payload, status):
    assert mint.handler(mint_event(payload), None)["statusCode"] == status


def test_mint_rejects_non_json(aws):
    event = http_event("POST", "/tokens", body="not json")
    assert mint.handler(event, None)["statusCode"] == 400


def test_mint_custom_ttl(aws):
    token = mint_token(ttlMinutes=5)
    item = row(token)
    assert item["expires_at"] - item["created_at"] == 5 * 60


# ---------------------------------------------------------------- GET /launch


def test_get_shows_button_and_does_not_burn(aws):
    token = mint_token()
    resp = launch.handler(http_event("GET", "/launch", query={"token": token}), None)
    assert resp["statusCode"] == 200
    assert 'method="post"' in resp["body"] and f'value="{token}"' in resp["body"]
    assert row(token)["status"] == "ISSUED", "a GET (e.g. link scanner) must not use the token"
    assert aws.presign_calls == []


@pytest.mark.parametrize("query", [None, {}, {"token": ""}, {"token": "short"}, {"token": "<script>" + "a" * 35}])
def test_get_rejects_malformed_token(aws, query):
    resp = launch.handler(http_event("GET", "/launch", query=query), None)
    assert resp["statusCode"] == 400
    assert "<script>" not in resp["body"]


# ---------------------------------------------------------------- POST /launch


def test_post_burns_token_and_redirects(aws):
    token = mint_token()
    resp = launch.handler(launch_post(token), None)
    assert resp["statusCode"] == 302
    assert resp["headers"]["Location"] == PRESIGNED
    for header, value in [("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer")]:
        assert resp["headers"][header] == value

    assert aws.presign_calls == [{
        "DomainId": DOMAIN,
        "UserProfileName": PROFILE,
        "ExpiresInSeconds": 15,
        "SessionExpirationDurationInSeconds": 43200,
    }]
    item = row(token)
    assert item["status"] == "USED"
    assert item["used_ip"] == "203.0.113.10"
    assert item["used_ua"] == "pytest-browser"


def test_post_accepts_base64_body(aws):
    token = mint_token()
    resp = launch.handler(launch_post(token, b64=True), None)
    assert resp["statusCode"] == 302


def test_reused_token_is_rejected(aws):
    token = mint_token()
    assert launch.handler(launch_post(token), None)["statusCode"] == 302
    resp = launch.handler(launch_post(token), None)
    assert resp["statusCode"] == 410
    assert len(aws.presign_calls) == 1


def test_expired_token_is_rejected(aws):
    token = mint_token()
    common.table().update_item(
        Key={"token_hash": common.hash_token(token)},
        UpdateExpression="SET expires_at = :t",
        ExpressionAttributeValues={":t": int(time.time()) - 1},
    )
    assert launch.handler(launch_post(token), None)["statusCode"] == 410
    assert aws.presign_calls == []


def test_revoked_token_is_rejected(aws):
    token = mint_token()
    common.table().update_item(
        Key={"token_hash": common.hash_token(token)},
        UpdateExpression="SET #s = :r",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":r": "REVOKED"},
    )
    assert launch.handler(launch_post(token), None)["statusCode"] == 410


def test_unknown_token_gets_same_response_as_used(aws):
    used = mint_token()
    launch.handler(launch_post(used), None)
    unknown = "A" * 43
    r_used = launch.handler(launch_post(used), None)
    r_unknown = launch.handler(launch_post(unknown), None)
    assert r_used["statusCode"] == r_unknown["statusCode"] == 410
    assert r_used["body"] == r_unknown["body"], "responses must not reveal whether a token exists"
    assert row(unknown) is None, "a failed check must not create a row"


def test_presign_failure_marks_failed(aws):
    token = mint_token()
    aws.fail_presign = True
    resp = launch.handler(launch_post(token), None)
    assert resp["statusCode"] == 502
    item = row(token)
    assert item["status"] == "FAILED"
    assert "ThrottlingException" in item["failure"]


def test_cross_site_post_is_blocked_without_burning(aws):
    token = mint_token()
    resp = launch.handler(launch_post(token, headers={"origin": "https://evil.example"}), None)
    assert resp["statusCode"] == 403
    assert row(token)["status"] == "ISSUED"


def test_same_site_origin_is_allowed(aws):
    token = mint_token()
    resp = launch.handler(launch_post(token, headers={"origin": f"https://{API_HOST}"}), None)
    assert resp["statusCode"] == 302


def test_ip_allowlist(aws, monkeypatch):
    monkeypatch.setenv("ALLOWED_CIDRS", "10.0.0.0/8, 198.51.100.0/24")
    token = mint_token()

    blocked = launch.handler(launch_post(token, ip="203.0.113.10"), None)
    assert blocked["statusCode"] == 403
    assert row(token)["status"] == "ISSUED", "off-network attempt must not burn the token"

    allowed = launch.handler(launch_post(token, ip="198.51.100.7"), None)
    assert allowed["statusCode"] == 302


def test_raw_token_never_logged(aws, caplog):
    token = mint_token()
    with caplog.at_level("INFO"):
        launch.handler(launch_post(token), None)
        launch.handler(launch_post(token), None)
    assert "launched" in caplog.text and "rejected" in caplog.text
    assert token not in caplog.text


def test_unsupported_method(aws):
    assert launch.handler(http_event("PUT", "/launch"), None)["statusCode"] == 405


# ---------------------------------------------------------------- concurrency


def test_parallel_clicks_only_one_wins(aws):
    """20 simultaneous POSTs with the same token: exactly one 302.

    moto serialises DynamoDB calls; the real atomicity guarantee comes from
    DynamoDB conditional writes. Re-run this against the deployed API to confirm.
    """
    token = mint_token()
    with ThreadPoolExecutor(max_workers=20) as pool:
        statuses = list(pool.map(lambda _: launch.handler(launch_post(token), None)["statusCode"], range(20)))
    assert statuses.count(302) == 1
    assert statuses.count(410) == 19
    assert len(aws.presign_calls) == 1
