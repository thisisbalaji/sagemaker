"""Create mock users for local development.

    python -m app.seed --admin-domain d-xxxxxxxx [--admin-domain d-yyyy]
"""

import argparse

import boto3

from .config import Settings
from .store import Store

USERS = [
    ("alice", "Alice Chen", "alice@example.com", False),
    ("bob", "Bob Martinez", "bob@example.com", False),
    ("dana", "Dana Admin", "dana@example.com", True),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--admin-domain", action="append", required=True,
                        help="Domain ID the admin user manages ('*' for all). Repeatable.")
    args = parser.parse_args()

    settings = Settings()
    store = Store(boto3.Session(region_name=settings.region).resource("dynamodb").Table(settings.table_name))
    for user_id, name, email, is_admin in USERS:
        store.put_user(user_id, name, email, args.admin_domain if is_admin else [])
        print(f"{user_id:6} {'admin of ' + ', '.join(args.admin_domain) if is_admin else 'user'}")


if __name__ == "__main__":
    main()
