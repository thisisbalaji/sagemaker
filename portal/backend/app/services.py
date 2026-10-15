"""Portal workflows: projects (with IAM roles), access requests, user profiles, Studio launch."""

import json
import re
import time

from botocore.exceptions import ClientError

from .store import APPROVED, FAILED, PENDING, PROVISIONING, REJECTED, Conflict, now_iso


class NotFound(Exception):
    pass


class Forbidden(Exception):
    pass


class AwsError(Exception):
    pass


def slugify(text, max_len):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].strip("-")


def profile_name_for(user_id, project_id):
    # SageMaker: [a-zA-Z0-9](-*[a-zA-Z0-9]){0,62}
    return slugify(f"{user_id}-{project_id}", 63)


def is_admin_for(user, domain_id):
    domains = user.get("admin_domains") or []
    return "*" in domains or domain_id in domains


def aws_message(e):
    err = e.response.get("Error", {})
    return f"{err.get('Code', 'Error')}: {err.get('Message', str(e))}"


class Portal:
    def __init__(self, settings, store, sagemaker, iam, sleep=time.sleep):
        self.settings = settings
        self.store = store
        self.sagemaker = sagemaker
        self.iam = iam
        self.sleep = sleep
        self._domain_cache = (0.0, None)

    # ---------------------------------------------------------------- domains
    def list_domains(self):
        fetched_at, cached = self._domain_cache
        if cached is not None and time.time() - fetched_at < self.settings.domain_cache_seconds:
            return cached
        domains = []
        try:
            for page in self.sagemaker.get_paginator("list_domains").paginate():
                for d in page["Domains"]:
                    detail = self.sagemaker.describe_domain(DomainId=d["DomainId"])
                    domains.append({
                        "domain_id": d["DomainId"],
                        "name": d["DomainName"],
                        "status": d["Status"],
                        "auth_mode": detail.get("AuthMode"),
                    })
        except ClientError as e:
            raise AwsError(aws_message(e)) from e
        domains.sort(key=lambda d: d["name"].lower())
        self._domain_cache = (time.time(), domains)
        return domains

    def get_domain(self, domain_id):
        for d in self.list_domains():
            if d["domain_id"] == domain_id:
                return d
        raise NotFound(f"Domain {domain_id} not found")

    # --------------------------------------------------------------- projects
    def create_project(self, admin, domain_id, name, description):
        if not is_admin_for(admin, domain_id):
            raise Forbidden("You are not an admin for this domain")
        self.get_domain(domain_id)
        name = name.strip()
        project_id = slugify(name, 40)
        if not project_id:
            raise ValueError("Project name must contain letters or numbers")
        if self.store.get_project(project_id):
            raise Conflict(f"A project with id '{project_id}' already exists")

        role_name = f"mlportal-{project_id}"
        role_arn = self._create_project_role(role_name, project_id, domain_id)
        try:
            return self.store.create_project(project_id, domain_id, name, description.strip(), role_name, role_arn, admin["user_id"])
        except Exception:
            self._delete_role(role_name)  # Don't leave an orphaned role if the save fails.
            raise

    def _delete_role(self, role_name):
        try:
            attached = self.iam.list_attached_role_policies(RoleName=role_name)["AttachedPolicies"]
            for p in attached:
                self.iam.detach_role_policy(RoleName=role_name, PolicyArn=p["PolicyArn"])
            self.iam.delete_role(RoleName=role_name)
        except ClientError:
            pass  # Best effort; the original error is what the caller needs to see.

    def _create_project_role(self, role_name, project_id, domain_id):
        trust = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "sagemaker.amazonaws.com"},
                "Action": ["sts:AssumeRole", "sts:SetSourceIdentity"],
            }],
        }
        try:
            role = self.iam.create_role(
                RoleName=role_name,
                Path=self.settings.project_role_path,
                AssumeRolePolicyDocument=json.dumps(trust),
                Description=f"SageMaker execution role for ML portal project {project_id}",
                Tags=[
                    {"Key": "mlportal:project", "Value": project_id},
                    {"Key": "mlportal:domain", "Value": domain_id},
                ],
            )["Role"]
        except ClientError as e:
            if e.response["Error"]["Code"] == "EntityAlreadyExists":
                raise Conflict(f"IAM role {role_name} already exists") from e
            raise AwsError(aws_message(e)) from e
        try:
            for arn in self.settings.project_role_policy_arns:
                self.iam.attach_role_policy(RoleName=role_name, PolicyArn=arn)
        except ClientError as e:
            self._delete_role(role_name)
            raise AwsError(aws_message(e)) from e
        return role["Arn"]

    def list_projects(self, domain_id):
        self.get_domain(domain_id)
        return self.store.list_projects(domain_id)

    def projects_for_user(self, user, domain_id):
        mine = {r["project_id"]: r for r in self.store.list_requests_for_user(user["user_id"])}
        result = []
        for p in self.list_projects(domain_id):
            req = mine.get(p["project_id"])
            result.append({
                **public_project(p),
                "my_status": req["status"] if req else None,
            })
        return result

    def admin_projects(self, admin):
        out = []
        for d in self.list_domains():
            if is_admin_for(admin, d["domain_id"]):
                out.extend({**p, "domain_name": d["name"]} for p in self.store.list_projects(d["domain_id"]))
        return out

    # --------------------------------------------------------------- requests
    def request_access(self, user, project_id, reason):
        project = self.store.get_project(project_id)
        if not project:
            raise NotFound("Project not found")
        return self.store.create_request(project, user["user_id"], reason.strip()[:500])

    def my_requests(self, user):
        out = []
        for r in self.store.list_requests_for_user(user["user_id"]):
            project = self.store.get_project(r["project_id"]) or {}
            row = {**r, "project_name": project.get("name", r["project_id"])}
            if r["status"] == APPROVED and r.get("user_profile_name"):
                row["profile_status"] = self._profile_status(r["domain_id"], r["user_profile_name"])
            out.append(row)
        return sorted(out, key=lambda r: r["requested_at"], reverse=True)

    def admin_requests(self, admin, status):
        out = []
        for d in self.list_domains():
            if not is_admin_for(admin, d["domain_id"]):
                continue
            for r in self.store.list_requests_by_status(d["domain_id"], status):
                user = self.store.get_user(r["user_id"]) or {}
                project = self.store.get_project(r["project_id"]) or {}
                out.append({
                    **r,
                    "domain_name": d["name"],
                    "project_name": project.get("name", r["project_id"]),
                    "user_display_name": user.get("display_name", r["user_id"]),
                    "user_email": user.get("email"),
                })
        return sorted(out, key=lambda r: r["requested_at"])

    def _request_for_admin(self, admin, project_id, user_id):
        req = self.store.get_request(project_id, user_id)
        if not req:
            raise NotFound("Request not found")
        if not is_admin_for(admin, req["domain_id"]):
            raise Forbidden("You are not an admin for this domain")
        return req

    def approve(self, admin, project_id, user_id):
        self._request_for_admin(admin, project_id, user_id)
        project = self.store.get_project(project_id)
        if not project:
            raise NotFound("Project not found")

        # Claim the request first so two admins cannot provision it twice.
        self.store.transition(project_id, user_id, [PENDING, FAILED], PROVISIONING,
                              decided_by=admin["user_id"], decided_at=now_iso())
        profile_name = profile_name_for(user_id, project_id)
        try:
            self._create_user_profile(project, user_id, profile_name)
        except AwsError as e:
            self.store.transition(project_id, user_id, [PROVISIONING], FAILED, error=str(e)[:500])
            raise
        return self.store.transition(project_id, user_id, [PROVISIONING], APPROVED,
                                     user_profile_name=profile_name, error=None)

    def _create_user_profile(self, project, user_id, profile_name):
        user = self.store.get_user(user_id) or {}
        tags = [
            {"Key": "mlportal:project", "Value": project["project_id"]},
            {"Key": "mlportal:user", "Value": user_id},
        ]
        if user.get("email"):
            tags.append({"Key": "owner", "Value": user["email"]})

        for attempt in range(1, self.settings.profile_create_retries + 1):
            try:
                self.sagemaker.create_user_profile(
                    DomainId=project["domain_id"],
                    UserProfileName=profile_name,
                    UserSettings={"ExecutionRole": project["role_arn"]},
                    Tags=tags,
                )
                return
            except ClientError as e:
                code = e.response["Error"]["Code"]
                if code == "ResourceInUse":
                    return  # Profile already exists (e.g. a retried approval); reuse it.
                retryable = code == "ValidationException" and "role" in aws_message(e).lower()
                if retryable and attempt < self.settings.profile_create_retries:
                    self.sleep(self.settings.profile_create_retry_delay)
                    continue
                raise AwsError(aws_message(e)) from e

    def reject(self, admin, project_id, user_id, note):
        self._request_for_admin(admin, project_id, user_id)
        return self.store.transition(project_id, user_id, [PENDING, FAILED], REJECTED,
                                     decided_by=admin["user_id"], decided_at=now_iso(),
                                     decision_note=note.strip()[:500])

    # ---------------------------------------------------------------- launch
    def launch_url(self, user, project_id):
        req = self.store.get_request(project_id, user["user_id"])
        if not req or req["status"] != APPROVED or not req.get("user_profile_name"):
            raise Forbidden("You do not have approved access to this project")
        status = self._profile_status(req["domain_id"], req["user_profile_name"])
        if status != "InService":
            raise Conflict(f"Your Studio profile is not ready yet (status: {status}). Try again in a minute.")
        try:
            return self.sagemaker.create_presigned_domain_url(
                DomainId=req["domain_id"],
                UserProfileName=req["user_profile_name"],
                ExpiresInSeconds=self.settings.presign_expires_seconds,
                SessionExpirationDurationInSeconds=self.settings.studio_session_seconds,
            )["AuthorizedUrl"]
        except ClientError as e:
            raise AwsError(aws_message(e)) from e

    def _profile_status(self, domain_id, profile_name):
        try:
            return self.sagemaker.describe_user_profile(DomainId=domain_id, UserProfileName=profile_name)["Status"]
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFound":
                return "NotFound"
            raise AwsError(aws_message(e)) from e


def public_project(p):
    """Project fields safe to show non-admin users."""
    return {k: p[k] for k in ("project_id", "domain_id", "name", "description", "created_at") if k in p}
