# ML Portal

Web portal for SageMaker AI domains: browse domains, request project access, approve requests (domain admins), and open Studio.

```
portal/
  infra/      Terraform: the DynamoDB table
  backend/    FastAPI + boto3 (DynamoDB, IAM, SageMaker)
  frontend/   React + TypeScript (Vite)
```

## How it works

- **Projects** are created by a domain admin. Creating one also creates an IAM execution role `mlportal-<project>` (path `/mlportal/`, trusted by SageMaker, `AmazonSageMakerFullAccess` by default — override with `PORTAL_PROJECT_ROLE_POLICIES`).
- **Users** request access to a project. The request is stored in DynamoDB as `PENDING`.
- **Admins** approve or reject on the Admin page. Approving creates the SageMaker user profile `<user>-<project>` in the project's domain, using the project's role, then marks the request `APPROVED`. If AWS fails, the request is `FAILED` with the error and can be retried.
- **Launch Studio** is a separate page. Clicking *Open Studio* posts a form to the backend, which checks access, creates a 15-second presigned URL, and 302-redirects a new tab into Studio. The URL is never shown. Needs an IAM-mode domain.
- **Admin rights** are per domain (`admin_domains` on the user). The API checks them on every admin call; the UI only hides the Admin page.

## Run locally

Prerequisites: AWS credentials that can manage DynamoDB, IAM roles, and SageMaker; Python 3.12+; Node 20+.

```bash
# 1. Table (once)
cd portal/infra && terraform init && terraform apply

# 2. Backend
cd portal/backend
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # or reuse the repo's .venv
.venv/bin/python -m app.seed --admin-domain <your-domain-id>            # mock users: alice, bob, dana (admin)
.venv/bin/uvicorn --factory app.main:create_app --reload --port 8000

# 3. Frontend (second terminal)
cd portal/frontend
npm install && npm run dev        # http://localhost:5173
```

Or build the UI once (`npm run build`) and open http://127.0.0.1:8000, where the backend serves it.

## Tests

```bash
cd portal/backend && python -m pytest tests        # moto for DynamoDB/IAM, fake SageMaker; no AWS calls
cd portal/frontend && npm run typecheck
```

## Before sharing beyond your machine

Login is a **development mock** (`PORTAL_MOCK_AUTH=1`, pick any user). Replace it with real sign-in (e.g. Cognito or your IdP) and set `PORTAL_MOCK_AUTH=0`, serve over HTTPS, and run the backend with a least-privilege IAM role instead of personal admin credentials.

## Cleaning up

Deleting the table does not delete what the portal created in AWS. Remove those too:
user profiles named `<user>-<project>` (tag `mlportal:project`) and IAM roles under path `/mlportal/`.
