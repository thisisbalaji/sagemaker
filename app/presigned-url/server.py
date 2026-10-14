"""Local server for generating SageMaker AI domain presigned URLs.

Uses the AWS credentials from your environment / ~/.aws (same as the AWS CLI).
Binds to localhost only, since anyone who can reach it can open Studio as any user.

    python3 server.py [--port 8000] [--region us-east-1] [--profile default]
"""

import argparse
import html
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


def create_presigned_url(form):
    domain_id = form.get("domainId", "").strip()
    profile = form.get("userProfileName", "").strip()
    if not domain_id or not profile:
        raise ValueError("Domain and user profile name are required")

    try:
        session_seconds = round(float(form.get("sessionHours") or 12) * 3600)
    except ValueError:
        raise ValueError("Session length must be a number of hours")
    if not 1800 <= session_seconds <= 43200:
        raise ValueError("Session length must be between 0.5 and 12 hours")

    # The browser follows the redirect immediately, so the URL only needs to live briefly.
    resp = sagemaker.create_presigned_domain_url(
        DomainId=domain_id,
        UserProfileName=profile,
        SessionExpirationDurationInSeconds=session_seconds,
        ExpiresInSeconds=30,
    )
    return resp["AuthorizedUrl"]


def error_page(message):
    return f"""<!doctype html><meta charset="utf-8"><title>Could not open Studio</title>
<style>body{{font:15px/1.5 -apple-system,sans-serif;max-width:560px;margin:48px auto;padding:0 16px}}
@media(prefers-color-scheme:dark){{body{{background:#0f1216;color:#e6e9ee}}}}</style>
<h1>Could not open Studio</h1><p>{html.escape(message)}</p>
<p>Close this tab, fix the details, and try again.</p>""".encode()


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
        if urlparse(self.path).path != "/open":
            return self._json(404, {"error": "Not found"})
        # Only accept submissions from this app's own page, not other sites.
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            return self._send(403, error_page("Request came from another site."), "text/html; charset=utf-8")
        try:
            length = int(self.headers.get("Content-Length") or 0)
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
            url = create_presigned_url(form)
        except ValueError as e:
            return self._send(400, error_page(str(e)), "text/html; charset=utf-8")
        except (ClientError, BotoCoreError) as e:
            return self._send(502, error_page(str(e)), "text/html; charset=utf-8")
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

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
