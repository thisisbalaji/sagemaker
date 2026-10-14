"""Mint a one-time SageMaker AI Studio launch link.

Calls the IAM-authenticated POST /tokens endpoint, signing the request with your
AWS credentials (SigV4). The caller needs the module's minter policy.

    python scripts/mint_link.py --mint-url https://<api>.execute-api.us-east-1.amazonaws.com/tokens \
        --domain-id d-xxxx --profile data-scientist-1 [--ttl 15] [--issued-to someone@corp.com]
"""

import argparse
import json
import sys
from urllib.parse import urlparse

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.httpsession import URLLib3Session


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mint-url", required=True, help="The module's mint_url output")
    parser.add_argument("--domain-id", required=True)
    parser.add_argument("--profile", required=True, help="SageMaker user profile name")
    parser.add_argument("--ttl", type=int, help="Link lifetime in minutes")
    parser.add_argument("--issued-to", help="Who the link is for (audit only)")
    parser.add_argument("--aws-profile", help="AWS CLI profile to sign with")
    args = parser.parse_args()

    payload = {"domainId": args.domain_id, "userProfileName": args.profile}
    if args.ttl is not None:
        payload["ttlMinutes"] = args.ttl
    if args.issued_to:
        payload["issuedTo"] = args.issued_to
    body = json.dumps(payload)

    session = boto3.Session(profile_name=args.aws_profile)
    region = urlparse(args.mint_url).netloc.split(".")[2]
    request = AWSRequest(method="POST", url=args.mint_url, data=body, headers={"Content-Type": "application/json"})
    SigV4Auth(session.get_credentials().get_frozen_credentials(), "execute-api", region).add_auth(request)

    # botocore's HTTP session uses its bundled CA certificates, so this works even
    # on Python installs that lack a system certificate store.
    resp = URLLib3Session().send(request.prepare())
    if resp.status_code != 201:
        sys.exit(f"Error {resp.status_code}: {resp.text}")
    data = json.loads(resp.content)

    print(data["launchUrl"])
    print(f"Expires {data['expiresAt']} · {data['domainId']} / {data['userProfileName']}", file=sys.stderr)


if __name__ == "__main__":
    main()
