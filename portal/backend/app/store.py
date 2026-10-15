"""DynamoDB access for the portal (single table).

Items
  USER     pk=USER#<uid>         sk=META
  PROJECT  pk=PROJECT#<pid>      sk=META           gsi1pk=DOMAIN#<domain>  gsi1sk=PROJECT#<pid>
  REQUEST  pk=PROJECT#<pid>      sk=REQUEST#<uid>  gsi1pk=USER#<uid>       gsi1sk=PROJECT#<pid>
                                                   gsi2pk=DOMAIN#<domain>#STATUS#<status>  gsi2sk=<requested_at>
"""

from datetime import datetime, timezone

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

PENDING = "PENDING"
PROVISIONING = "PROVISIONING"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
FAILED = "FAILED"


class Conflict(Exception):
    """A conditional write lost: the item was not in the expected state."""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(item):
    return {k: v for k, v in item.items() if k not in ("pk", "sk", "gsi1pk", "gsi1sk", "gsi2pk", "gsi2sk")}


class Store:
    def __init__(self, table):
        self.table = table

    # ------------------------------------------------------------------ users
    def put_user(self, user_id, display_name, email, admin_domains=()):
        self.table.put_item(Item={
            "pk": f"USER#{user_id}", "sk": "META", "type": "USER",
            "user_id": user_id, "display_name": display_name, "email": email,
            "admin_domains": list(admin_domains),
        })

    def get_user(self, user_id):
        item = self.table.get_item(Key={"pk": f"USER#{user_id}", "sk": "META"}).get("Item")
        return _clean(item) if item else None

    def list_users(self):
        items = self._scan(Attr("type").eq("USER"))
        return sorted((_clean(i) for i in items), key=lambda u: u["user_id"])

    # --------------------------------------------------------------- projects
    def create_project(self, project_id, domain_id, name, description, role_name, role_arn, created_by):
        item = {
            "pk": f"PROJECT#{project_id}", "sk": "META", "type": "PROJECT",
            "gsi1pk": f"DOMAIN#{domain_id}", "gsi1sk": f"PROJECT#{project_id}",
            "project_id": project_id, "domain_id": domain_id, "name": name, "description": description,
            "role_name": role_name, "role_arn": role_arn, "created_by": created_by, "created_at": now_iso(),
        }
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise Conflict(f"Project {project_id} already exists") from e
            raise
        return _clean(item)

    def get_project(self, project_id):
        item = self.table.get_item(Key={"pk": f"PROJECT#{project_id}", "sk": "META"}).get("Item")
        return _clean(item) if item else None

    def list_projects(self, domain_id):
        items = self._query("gsi1", Key("gsi1pk").eq(f"DOMAIN#{domain_id}") & Key("gsi1sk").begins_with("PROJECT#"))
        return sorted((_clean(i) for i in items if i.get("type") == "PROJECT"), key=lambda p: p["name"].lower())

    # --------------------------------------------------------------- requests
    def create_request(self, project, user_id, reason):
        """New request, or a re-request after rejection. Fails if one is already open or approved."""
        ts = now_iso()
        item = {
            "pk": f"PROJECT#{project['project_id']}", "sk": f"REQUEST#{user_id}", "type": "REQUEST",
            "gsi1pk": f"USER#{user_id}", "gsi1sk": f"PROJECT#{project['project_id']}",
            "gsi2pk": f"DOMAIN#{project['domain_id']}#STATUS#{PENDING}", "gsi2sk": ts,
            "project_id": project["project_id"], "domain_id": project["domain_id"], "user_id": user_id,
            "status": PENDING, "reason": reason, "requested_at": ts,
        }
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(pk) OR #s = :rejected",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":rejected": REJECTED},
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise Conflict("You already have an open or approved request for this project") from e
            raise
        return _clean(item)

    def get_request(self, project_id, user_id):
        item = self.table.get_item(Key={"pk": f"PROJECT#{project_id}", "sk": f"REQUEST#{user_id}"}).get("Item")
        return _clean(item) if item else None

    def list_requests_for_user(self, user_id):
        items = self._query("gsi1", Key("gsi1pk").eq(f"USER#{user_id}") & Key("gsi1sk").begins_with("PROJECT#"))
        return [_clean(i) for i in items if i.get("type") == "REQUEST"]

    def list_requests_by_status(self, domain_id, status):
        items = self._query("gsi2", Key("gsi2pk").eq(f"DOMAIN#{domain_id}#STATUS#{status}"))
        return [_clean(i) for i in items]

    def transition(self, project_id, user_id, from_statuses, to_status, **fields):
        """Atomically move a request between statuses; raises Conflict if it is not in from_statuses."""
        names = {"#s": "status"}
        values = {":to": to_status, ":gsi2pk": None}
        sets = ["#s = :to", "gsi2pk = :gsi2pk"]
        for i, (k, v) in enumerate(fields.items()):
            names[f"#f{i}"] = k
            values[f":f{i}"] = v
            sets.append(f"#f{i} = :f{i}")
        conds = []
        for i, s in enumerate(from_statuses):
            values[f":from{i}"] = s
            conds.append(f"#s = :from{i}")

        current = self.get_request(project_id, user_id)
        if current is None:
            raise Conflict("Request not found")
        values[":gsi2pk"] = f"DOMAIN#{current['domain_id']}#STATUS#{to_status}"
        try:
            item = self.table.update_item(
                Key={"pk": f"PROJECT#{project_id}", "sk": f"REQUEST#{user_id}"},
                UpdateExpression="SET " + ", ".join(sets),
                ConditionExpression="(" + " OR ".join(conds) + ")",
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
            )["Attributes"]
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise Conflict(f"Request is no longer {' or '.join(from_statuses)}") from e
            raise
        return _clean(item)

    # ---------------------------------------------------------------- helpers
    def _query(self, index, key_condition):
        kwargs = {"IndexName": index, "KeyConditionExpression": key_condition}
        items = []
        while True:
            resp = self.table.query(**kwargs)
            items.extend(resp["Items"])
            if "LastEvaluatedKey" not in resp:
                return items
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    def _scan(self, filter_expression):
        kwargs = {"FilterExpression": filter_expression}
        items = []
        while True:
            resp = self.table.scan(**kwargs)
            items.extend(resp["Items"])
            if "LastEvaluatedKey" not in resp:
                return items
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
