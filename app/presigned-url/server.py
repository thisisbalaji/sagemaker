"""Local server for generating SageMaker AI domain presigned URLs.

Uses the AWS credentials from your environment / ~/.aws (same as the AWS CLI).
Binds to localhost only, since anyone who can reach it can open Studio as any user.

    python3 server.py [--port 8000] [--region us-east-1] [--profile default]
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError

INDEX_HTML = Path(__file__).with_name("index.html")

sagemaker = None


def list_domains():
    domains = []
    for page in sagemaker.get_paginator("list_domains").paginate():
        for d in page["Domains"]:
            domains.append({"id": d["DomainId"], "name": d["DomainName"], "status": d["Status"]})
    return sorted(domains, key=lambda d: d["name"].lower())


def list_user_profiles(domain_id):
    names = []
    paginator = sagemaker.get_paginator("list_user_profiles")
    for page in paginator.paginate(DomainIdEquals=domain_id):
        names.extend(p["UserProfileName"] for p in page["UserProfiles"])
    return sorted(names)


def create_presigned_url(body):
    domain_id = (body.get("domainId") or "").strip()
    profile = (body.get("userProfileName") or "").strip()
    if not domain_id or not profile:
        raise ValueError("domainId and userProfileName are required")

    session_seconds = int(body.get("sessionExpirationSeconds") or 43200)
    expires_seconds = int(body.get("expiresInSeconds") or 300)
    if not 1800 <= session_seconds <= 43200:
        raise ValueError("Session duration must be between 1800 and 43200 seconds")
    if not 5 <= expires_seconds <= 300:
        raise ValueError("URL expiry must be between 5 and 300 seconds")

    resp = sagemaker.create_presigned_domain_url(
        DomainId=domain_id,
        UserProfileName=profile,
        SessionExpirationDurationInSeconds=session_seconds,
        ExpiresInSeconds=expires_seconds,
    )
    return {"url": resp["AuthorizedUrl"], "expiresInSeconds": expires_seconds}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path in ("/", "/index.html"):
                self._send(200, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/domains":
                self._json(200, {"domains": list_domains()})
            elif url.path == "/api/user-profiles":
                domain_id = parse_qs(url.query).get("domainId", [""])[0]
                self._json(200, {"userProfiles": list_user_profiles(domain_id)})
            else:
                self._json(404, {"error": "Not found"})
        except (ClientError, BotoCoreError) as e:
            self._json(502, {"error": str(e)})

    def do_POST(self):
        if urlparse(self.path).path != "/api/presigned-url":
            return self._json(404, {"error": "Not found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            self._json(200, create_presigned_url(body))
        except ValueError as e:
            self._json(400, {"error": str(e)})
        except (ClientError, BotoCoreError) as e:
            self._json(502, {"error": str(e)})

    def _json(self, status, data):
        self._send(status, json.dumps(data).encode(), "application/json")

    def _send(self, status, payload, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)


def main():
    global sagemaker
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--region", default=None, help="Defaults to your AWS config region")
    parser.add_argument("--profile", default=None, help="AWS CLI profile name")
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    sagemaker = session.client("sagemaker")

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Region {session.region_name} — open http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
