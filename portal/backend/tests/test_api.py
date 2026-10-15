import json

import pytest

from conftest import DOMAIN, OTHER_DOMAIN


def make_project(env, name="Churn Model", domain=DOMAIN, admin="dana"):
    r = env.client(admin).post("/api/admin/projects", json={"domain_id": domain, "name": name, "description": "d"})
    assert r.status_code == 201, r.text
    return r.json()


def request(env, user, project_id, reason="need it"):
    return env.client(user).post(f"/api/projects/{project_id}/requests", json={"reason": reason})


# ------------------------------------------------------------------- auth


def test_requires_login(env):
    c = env.client()
    for path in ["/api/me", "/api/domains", "/api/me/requests", "/api/admin/requests"]:
        assert c.get(path).status_code == 401, path


def test_unknown_user_cannot_log_in(env):
    assert env.client().post("/api/auth/login", json={"user_id": "mallory"}).status_code == 401


def test_me_reports_admin_flag(env):
    assert env.client("alice").get("/api/me").json()["is_admin"] is False
    assert env.client("dana").get("/api/me").json()["is_admin"] is True


def test_logout(env):
    c = env.client("alice")
    c.post("/api/auth/logout")
    assert c.get("/api/me").status_code == 401


def test_mock_user_list_hidden_when_mock_auth_off(env):
    env.portal.settings.mock_auth = False
    # create_app captured settings by reference, so the flag flip applies.
    assert env.client().get("/api/auth/users").status_code == 404


# ------------------------------------------------------------- admin gate


@pytest.mark.parametrize("method, path", [
    ("get", "/api/admin/projects"),
    ("get", "/api/admin/requests"),
    ("post", "/api/admin/projects"),
    ("post", "/api/admin/requests/p/alice/approve"),
    ("post", "/api/admin/requests/p/alice/reject"),
])
def test_normal_users_cannot_use_admin_api(env, method, path):
    c = env.client("alice")
    kwargs = {"json": {"domain_id": DOMAIN, "name": "x"}} if method == "post" else {}
    assert getattr(c, method)(path, **kwargs).status_code == 403


def test_admin_of_other_domain_cannot_create_project_here(env):
    r = env.client("olga").post("/api/admin/projects", json={"domain_id": DOMAIN, "name": "X"})
    assert r.status_code == 403


def test_admin_of_other_domain_cannot_approve(env):
    p = make_project(env)
    request(env, "alice", p["project_id"])
    r = env.client("olga").post(f"/api/admin/requests/{p['project_id']}/alice/approve")
    assert r.status_code == 403
    assert env.client("olga").get("/api/admin/requests").json() == []


# --------------------------------------------------------------- projects


def test_create_project_creates_iam_role(env):
    p = make_project(env)
    assert p["project_id"] == "churn-model"
    role = env.iam.get_role(RoleName="mlportal-churn-model")["Role"]
    assert role["Path"] == "/mlportal/"
    assert role["Arn"] == p["role_arn"]
    trust = role["AssumeRolePolicyDocument"]
    trust = json.loads(trust) if isinstance(trust, str) else trust
    assert trust["Statement"][0]["Principal"]["Service"] == "sagemaker.amazonaws.com"
    attached = env.iam.list_attached_role_policies(RoleName="mlportal-churn-model")["AttachedPolicies"]
    assert [a["PolicyArn"] for a in attached] == ["arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"]


def test_duplicate_project_rejected_without_new_role(env):
    make_project(env)
    r = env.client("dana").post("/api/admin/projects", json={"domain_id": DOMAIN, "name": "churn model!"})
    assert r.status_code == 409


def test_failed_policy_attach_leaves_no_orphan_role(env):
    env.portal.settings.project_role_policy_arns = ["arn:aws:iam::aws:policy/DoesNotExist"]
    r = env.client("dana").post("/api/admin/projects", json={"domain_id": DOMAIN, "name": "Orphan"})
    assert r.status_code == 502
    roles = [x["RoleName"] for x in env.iam.list_roles(PathPrefix="/mlportal/")["Roles"]]
    assert roles == []
    assert env.store.get_project("orphan") is None


def test_project_on_unknown_domain(env):
    env.store.put_user("root", "Root", "r@example.com", ["*"])
    r = env.client("root").post("/api/admin/projects", json={"domain_id": "d-nope", "name": "X"})
    assert r.status_code == 404


def test_domains_and_projects_visible_to_users_without_role_details(env):
    make_project(env)
    domains = env.client("alice").get("/api/domains").json()
    assert {d["domain_id"] for d in domains} == {DOMAIN, OTHER_DOMAIN}
    assert all(d["auth_mode"] == "IAM" for d in domains)
    projects = env.client("alice").get(f"/api/domains/{DOMAIN}/projects").json()
    assert [p["name"] for p in projects] == ["Churn Model"]
    assert "role_arn" not in projects[0]
    assert projects[0]["my_status"] is None


# --------------------------------------------------------------- requests


def test_request_flow_approve_creates_profile_with_project_role(env):
    p = make_project(env)
    assert request(env, "alice", p["project_id"]).status_code == 201
    assert request(env, "alice", p["project_id"]).status_code == 409, "no duplicate open requests"

    pending = env.client("dana").get("/api/admin/requests").json()
    assert [(r["user_id"], r["project_name"]) for r in pending] == [("alice", "Churn Model")]

    r = env.client("dana").post(f"/api/admin/requests/{p['project_id']}/alice/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APPROVED"
    assert r.json()["user_profile_name"] == "alice-churn-model"

    profile = env.sm.profiles[(DOMAIN, "alice-churn-model")]
    assert profile["UserSettings"]["ExecutionRole"] == p["role_arn"]
    assert {"Key": "owner", "Value": "alice@example.com"} in profile["Tags"]

    assert env.client("dana").get("/api/admin/requests").json() == []
    mine = env.client("alice").get("/api/me/requests").json()
    assert mine[0]["status"] == "APPROVED" and mine[0]["profile_status"] == "InService"
    projects = env.client("alice").get(f"/api/domains/{DOMAIN}/projects").json()
    assert projects[0]["my_status"] == "APPROVED"


def test_double_approve_is_conflict(env):
    p = make_project(env)
    request(env, "alice", p["project_id"])
    dana = env.client("dana")
    assert dana.post(f"/api/admin/requests/{p['project_id']}/alice/approve").status_code == 200
    assert dana.post(f"/api/admin/requests/{p['project_id']}/alice/approve").status_code == 409


def test_approve_retries_while_new_role_propagates(env):
    p = make_project(env)
    request(env, "alice", p["project_id"])
    env.sm.role_not_ready = 2
    r = env.client("dana").post(f"/api/admin/requests/{p['project_id']}/alice/approve")
    assert r.status_code == 200
    assert (DOMAIN, "alice-churn-model") in env.sm.profiles


def test_failed_provisioning_is_recorded_and_retryable(env):
    p = make_project(env)
    request(env, "alice", p["project_id"])
    env.sm.fail_create = "ResourceLimitExceeded"
    dana = env.client("dana")
    r = dana.post(f"/api/admin/requests/{p['project_id']}/alice/approve")
    assert r.status_code == 502
    req = env.store.get_request(p["project_id"], "alice")
    assert req["status"] == "FAILED" and "ResourceLimitExceeded" in req["error"]
    assert [x["user_id"] for x in dana.get("/api/admin/requests?status=FAILED").json()] == ["alice"]

    env.sm.fail_create = None
    assert dana.post(f"/api/admin/requests/{p['project_id']}/alice/approve").status_code == 200


def test_reject_then_rerequest(env):
    p = make_project(env)
    request(env, "alice", p["project_id"])
    r = env.client("dana").post(f"/api/admin/requests/{p['project_id']}/alice/reject", json={"note": "not now"})
    assert r.json()["status"] == "REJECTED" and r.json()["decision_note"] == "not now"
    assert (DOMAIN, "alice-churn-model") not in env.sm.profiles
    assert request(env, "alice", p["project_id"]).status_code == 201, "can ask again after rejection"
    assert env.store.get_request(p["project_id"], "alice")["status"] == "PENDING"


def test_request_unknown_project(env):
    assert request(env, "alice", "nope").status_code == 404


# ----------------------------------------------------------------- launch


def test_launch_redirects_only_with_approved_access(env):
    p = make_project(env)
    alice = env.client("alice")
    r = alice.post("/api/studio/launch", data={"project_id": p["project_id"]}, follow_redirects=False)
    assert r.status_code == 403 and "approved access" in r.text

    request(env, "alice", p["project_id"])
    env.client("dana").post(f"/api/admin/requests/{p['project_id']}/alice/approve")

    r = alice.post("/api/studio/launch", data={"project_id": p["project_id"]}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].startswith(f"https://{DOMAIN}.studio.")
    assert r.headers["cache-control"] == "no-store"
    assert env.sm.presign_calls[-1]["UserProfileName"] == "alice-churn-model"
    assert env.sm.presign_calls[-1]["ExpiresInSeconds"] == 15

    bob = env.client("bob")
    r = bob.post("/api/studio/launch", data={"project_id": p["project_id"]}, follow_redirects=False)
    assert r.status_code == 403, "another user cannot launch alice's profile"


def test_launch_waits_for_profile(env):
    p = make_project(env)
    request(env, "alice", p["project_id"])
    env.client("dana").post(f"/api/admin/requests/{p['project_id']}/alice/approve")
    env.sm.profiles[(DOMAIN, "alice-churn-model")]["Status"] = "Pending"
    r = env.client("alice").post("/api/studio/launch", data={"project_id": p["project_id"]}, follow_redirects=False)
    assert r.status_code == 409 and "not ready" in r.text


def test_cross_site_post_blocked(env):
    p = make_project(env)
    r = env.client("alice").post(f"/api/projects/{p['project_id']}/requests", json={},
                                 headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert env.store.get_request(p["project_id"], "alice") is None
