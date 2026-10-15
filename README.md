# SageMaker AI toolkit

Terraform modules, small apps, and a web portal for running Amazon SageMaker AI domains: create a domain, give people secure one-click access to Studio, and manage who can use which project.

Everything is built to cost close to nothing when idle — no always-on servers, endpoints, or load balancers.

## What's in this repo

| Component | Path | What it does |
|---|---|---|
| [SageMaker AI domain module](#1-sagemaker-ai-domain-module) | `modules/sagemaker-domain/` | Terraform module that creates a domain, execution role, security group, and user profiles |
| [Presigned URL app](#2-presigned-url-app-local) | `app/presigned-url/` | Local web page: pick a domain and user, open Studio in a new tab |
| [One-time launch links](#3-one-time-studio-launch-links) | `modules/studio-launch-tokens/` | API Gateway + Lambda + DynamoDB service that issues single-use Studio links |
| [ML portal](#4-ml-portal) | `portal/` | React + FastAPI portal: browse domains, request project access, admin approval, launch Studio |
| [Churn EDA](#5-churn-eda) | `eda/` | Exploratory data analysis script that runs locally or as a SageMaker Processing job |

## Repository layout

```
.
├── modules/
│   ├── sagemaker-domain/         Terraform: domain, IAM role, security group, user profiles
│   └── studio-launch-tokens/     Terraform + Lambda: one-time Studio launch links
│       ├── lambda/               launch.py, mint.py, common.py
│       └── tests/                pytest (moto) unit tests
├── examples/
│   ├── basic/                    Deploys the domain module
│   └── launch-tokens/            Deploys the launch-link service
├── app/presigned-url/            Local presigned-URL web app (Python stdlib + boto3)
├── scripts/mint_link.py          CLI to mint a one-time launch link
├── portal/                       ML portal (see portal/README.md)
│   ├── infra/                    Terraform: DynamoDB table
│   ├── backend/                  FastAPI + boto3, with tests
│   └── frontend/                 React + TypeScript (Vite)
└── eda/churn_eda.py              EDA for the SageMaker churn sample dataset
```

## Prerequisites

| Tool | Version | Used by |
|---|---|---|
| AWS account + credentials | — | Everything. `aws sts get-caller-identity` should succeed. |
| Terraform | 1.5+ | Modules and examples (AWS provider 6.x) |
| Python | 3.12+ | Apps, Lambda code, portal backend, EDA, tests |
| Node.js | 20+ | Portal frontend only |

The IAM identity you deploy with needs permissions for SageMaker AI, IAM (create roles), EC2/VPC (security groups), DynamoDB, Lambda, API Gateway, and CloudWatch Logs.

Create a Python environment once at the repo root and reuse it:

```bash
python3 -m venv .venv
.venv/bin/pip install boto3 pytest 'moto[dynamodb,iam]'
```

---

## 1. SageMaker AI domain module

`modules/sagemaker-domain/` creates:

- **Execution role** — trusted by `sagemaker.amazonaws.com` (with `sts:SetSourceIdentity`), `AmazonSageMakerFullAccess` attached by default. Bring your own with `create_execution_role = false`.
- **Security group** — allows traffic between the domain's apps and all outbound traffic.
- **Domain** — new Studio experience, IAM or SSO auth, `VpcOnly` networking by default, home EFS retained on delete by default.
- **User profiles** — one per entry in `user_profiles`, optionally with their own execution role.

### Key inputs

| Variable | Default | Notes |
|---|---|---|
| `domain_name` | — | Required |
| `vpc_id`, `subnet_ids` | — | Required. Use private subnets with `VpcOnly`. |
| `auth_mode` | `IAM` | `IAM` or `SSO` (IAM Identity Center). Cannot change after creation. |
| `app_network_access_type` | `VpcOnly` | `VpcOnly` needs a NAT gateway or VPC endpoints for AWS API access |
| `execution_role_policy_arns` | `[AmazonSageMakerFullAccess]` | Narrow this for production |
| `kms_key_id` | `null` | Customer-managed key for the home EFS volume |
| `efs_retention_policy` | `Retain` | `Delete` removes user home directories with the domain |
| `user_profiles` | `{}` | `{ "name" = { execution_role_arn = optional } }` |

Outputs: `domain_id`, `domain_arn`, `domain_url`, `home_efs_file_system_id`, `execution_role_arn`, `security_group_ids`, `user_profile_arns`.

### Deploy the example

```bash
cd examples/basic
cp terraform.tfvars.example terraform.tfvars   # set your VPC and subnet IDs
terraform init
terraform plan
terraform apply
```

The example uses `PublicInternetOnly` so it works in a default VPC without extra networking.

---

## 2. Presigned URL app (local)

A single-file Python server for opening Studio without the console. It lists domains in a dropdown, suggests user profiles, and opens Studio in a new tab.

```bash
cd app/presigned-url
../../.venv/bin/python server.py   # needs boto3; http://127.0.0.1:8000  (--region, --profile, --port)
```

How it works: the form posts to `/open`; the server calls `CreatePresignedDomainUrl` with a 30-second expiry and returns an **HTTP 302** to that URL, so the URL is never displayed on the page. It binds to `127.0.0.1` only, rejects cross-site form posts, and sends `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.

> Anyone who can reach this server can open Studio as any user in the listed domains. Keep it on your own machine. For shared use, see the launch-link service or the portal.

---

## 3. One-time Studio launch links

A serverless service that issues **single-use links** into Studio. An admin mints a link for a specific domain and user profile; the recipient clicks it once.

```
Admin ──POST /tokens (IAM SigV4)──► mint Lambda ──► DynamoDB (token hash, profile, expiry)
                                         │
                                         └─► returns https://<api>/launch?token=…

User ──GET /launch?token=…──► launch Lambda ──► "Open Studio" button page (token not used yet)
User ──POST /launch──────────► launch Lambda
                                 1. Origin and IP allowlist checks
                                 2. DynamoDB conditional update: ISSUED → USED (only if not expired)
                                 3. CreatePresignedDomainUrl (15 s)
                                 4. HTTP 302 → Studio
```

### Design choices

- **Only the SHA-256 hash of each token is stored**, so a table leak exposes no usable links.
- **GET never consumes the token.** Email scanners and chat link previews fetch URLs automatically; the button + POST means they can't burn the link before the user clicks.
- **Atomic single use.** A DynamoDB conditional write guarantees exactly one success even under simultaneous clicks.
- **Uniform failure page.** Unknown, used, expired, and revoked tokens all get the same `410` response.
- **Profile is bound at mint time**, never taken from the browser.
- **Audit trail.** Each row records who minted it, who used it, when, from which IP and user agent. DynamoDB TTL purges rows 90 days after expiry (`purge_at`), not at expiry, so history is kept.
- **Least-privilege Lambdas.** The launch function can only `UpdateItem` and presign; the mint function can only `PutItem` and `DescribeUserProfile`.
- **No tokens in logs.** API access logs exclude the query string; Lambdas log only a hash prefix.

### Deploy

```bash
cd examples/launch-tokens
cp terraform.tfvars.example terraform.tfvars   # set domain_ids; set allowed_cidrs for real use
terraform init
terraform apply
```

Set `allowed_cidrs` to your corporate egress ranges before real use — when empty, links work from any IP.

Attach the `minter_policy_arn` output to anyone who should be able to create links.

### Mint a link

```bash
.venv/bin/python scripts/mint_link.py \
  --mint-url "$(terraform -chdir=examples/launch-tokens output -raw mint_url)" \
  --domain-id <domain-id> --profile <user-profile> --ttl 15 --issued-to someone@example.com
```

Revoke a link by setting its row's `status` to `REVOKED` in the `<name>-tokens` table.

### Tests

```bash
cd modules/studio-launch-tokens
../../.venv/bin/python -m pytest tests
```

29 tests cover minting, button-page behaviour, single use, expiry, revocation, uniform errors, presign failure, cross-site and IP blocking, log hygiene, and 20 parallel clicks.

### Limits worth knowing

- A link is a bearer token: whoever clicks first gets in. Keep TTLs short, restrict IPs, and deliver links only to verified addresses. For identity-verified access, put a real login in front (Cognito / your IdP) or use an SSO-mode domain with IAM Identity Center.
- New AWS accounts default to **10 concurrent Lambda executions**; heavy simultaneous use can return `503`. Request a higher limit in Service Quotas.
- Presigned URLs only work for **IAM-mode** domains.

---

## 4. ML portal

A web portal for domain and project access management. Full details in [`portal/README.md`](portal/README.md).

| Page | Audience | Purpose |
|---|---|---|
| Domains | Everyone | Browse SageMaker AI domains and their projects; request access |
| My access | Everyone | Track your requests and Studio profiles |
| Launch Studio | Everyone | Open Studio for an approved project (302 redirect; URL never shown) |
| Admin | Domain admins only | Create projects, approve or reject access |

How access works:

1. A **domain admin creates a project**. The portal creates an IAM execution role `mlportal-<project>` for it.
2. A **user requests access**. The request is stored in DynamoDB as `PENDING`.
3. The **admin approves**. The portal creates the SageMaker user profile `<user>-<project>` using the project's role, then marks the request `APPROVED`. Failures are recorded as `FAILED` and can be retried.
4. The **user opens Studio** from the Launch Studio page.

Admin rights are per domain and enforced by the API on every call; the UI only hides the page. Approvals are claimed atomically so two admins cannot provision the same request twice.

Quick start (details in the portal README):

```bash
cd portal/infra && terraform init && terraform apply                      # DynamoDB table
cd ../backend && ../../.venv/bin/pip install -r requirements-dev.txt
../../.venv/bin/python -m app.seed --admin-domain <domain-id>              # mock users
../../.venv/bin/uvicorn --factory app.main:create_app --port 8000
cd ../frontend && npm install && npm run dev                               # http://localhost:5173
```

> Login is a **development mock**. Replace it with real authentication and run the backend under a least-privilege role before exposing the portal to anyone else.

---

## 5. Churn EDA

`eda/churn_eda.py` analyses the public SageMaker churn sample dataset (`s3://sagemaker-sample-files/datasets/tabular/synthetic/churn.csv`) and writes charts, `summary.json`, and `report.md`.

```bash
.venv/bin/pip install pandas numpy matplotlib seaborn scikit-learn
mkdir -p data/raw && aws s3 cp s3://sagemaker-sample-files/datasets/tabular/synthetic/churn.csv data/raw/
.venv/bin/python eda/churn_eda.py --input data/raw/churn.csv --output eda/output
```

Input and output paths default to `/opt/ml/processing/input` and `/opt/ml/processing/output`, so the same script runs unchanged as a SageMaker Processing job.

---

## Costs

Everything here is free or near-free while idle. What can cost money:

| Item | Cost driver | How to avoid surprises |
|---|---|---|
| Domain, user profiles, IAM roles, security groups | Free | — |
| Home EFS storage | ~$0.30/GB-month | Small unless users store large files |
| Studio JupyterLab / Code Editor spaces | Per instance-hour while running | Stop spaces when done; enable idle shutdown. Closing the tab does not stop them. |
| SageMaker Canvas | Per session-hour until you log out inside Canvas | Log out from Canvas explicitly |
| Launch-link service and portal table | Lambda, API Gateway, DynamoDB on demand | Fractions of a cent at low volume; $0 idle |
| CloudWatch Logs | $0.50/GB ingested | Tiny at this scale; 30-day retention set |

Set up an **AWS Budget** alert (Billing → Budgets) as a safety net.

## Security notes

- Never commit `terraform.tfvars`, `*.tfstate`, or credentials — `.gitignore` excludes them.
- `AmazonSageMakerFullAccess` is broad. Pass narrower policies via `execution_role_policy_arns` (domain module) or `PORTAL_PROJECT_ROLE_POLICIES` (portal) for production.
- Presigned URLs and launch links are bearer credentials. Keep expiries short, restrict source IPs, and prefer SSO-mode domains with IAM Identity Center when you need verified identity.
- Set `ExecutionRoleIdentityConfig = USER_PROFILE_NAME` on domains so actions in Studio are attributed to the user in CloudTrail.

## Cleanup

Run `terraform destroy` in each directory you applied, newest first:

```bash
terraform -chdir=portal/infra destroy
terraform -chdir=examples/launch-tokens destroy
terraform -chdir=examples/basic destroy
```

Also remove what the portal created at runtime, which Terraform does not track: user profiles tagged `mlportal:project` and IAM roles under the `/mlportal/` path. Delete user profiles before destroying their domain. The domain's home EFS volume is retained by default — delete it in the EFS console if you no longer need it.
