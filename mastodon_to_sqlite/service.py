import datetime
import json
from pathlib import Path
from typing import Any, Dict, Generator, List

from sqlite_utils import Database

from .client import MastodonClient


def open_database(db_file_path) -> Database:
    """
    Open the Mastodon SQLite database.
    """
    return Database(db_file_path)


def build_database(db: Database):
    """
    Build the Mastodon SQLite database structure.
    """
    table_names = set(db.table_names())

    if "accounts" not in table_names:
        db["accounts"].create(
            columns={
                "id": str,
                "username": str,
                "url": str,
                "display_name": str,
                "note": str,
            },
            pk="id",
        )
        db["accounts"].enable_fts(
            ["username", "display_name", "note"], create_triggers=True
        )

    if "following" not in table_names:
        db["following"].create(
            columns={"followed_id": int, "follower_id": int, "first_seen": str},
            pk=("followed_id", "follower_id"),
            foreign_keys=(
                ("followed_id", "accounts", "id"),
                ("follower_id", "accounts", "id"),
            ),
        )

    following_indexes = {tuple(i.columns) for i in db["following"].indexes}
    if ("followed_id",) not in following_indexes:
        db["following"].create_index(["followed_id"])
    if ("follower_id",) not in following_indexes:
        db["following"].create_index(["follower_id"])


def mastodon_client(auth_file_path: str) -> MastodonClient:
    """
    Returns a fully authenticated MastodonClient.
    """
    with Path(auth_file_path).absolute().open() as file_obj:
        raw_auth = file_obj.read()

    auth = json.loads(raw_auth)

    return MastodonClient(
        domain=auth["mastodon_domain"],
        access_token=auth["mastodon_access_token"],
    )


def verify_auth(auth_file_path: str) -> bool:
    """
    Verify Mastodon authentication.
    """
    client = mastodon_client(auth_file_path)

    _, response = client.accounts_verify_credentials()

    if response.status_code == 200:
        return True

    return False


def get_account_id(client: MastodonClient) -> str:
    """
    Returns the authenticated user's ID.
    """
    _, response = client.accounts_verify_credentials()
    response.raise_for_status()
    return response.json()["id"]


def get_followers(
    account_id: str, client: MastodonClient
) -> Generator[List[Dict[str, Any]], None, None]:
    """
    Get authenticated account's followers.
    """
    for request, response in client.accounts_followers(account_id):
        yield response.json()


def get_followings(
    account_id: str, client: MastodonClient
) -> Generator[List[Dict[str, Any]], None, None]:
    """
    Get authenticated account's followers.
    """
    for request, response in client.accounts_following(account_id):
        yield response.json()


def transformer_account(account: Dict[str, Any]):
    """
    Transformer a Mastodon account so it can be safely saved to the SQLite
    database.
    """
    to_remove = [
        k
        for k in account.keys()
        if k not in ("id", "username", "url", "display_url", "note")
    ]
    for key in to_remove:
        del account[key]


def save_accounts(
    db: Database,
    accounts: List[Dict[str, Any]],
    followed_id: str = None,
    follower_id: str = None,
):
    """
    Save Mastodon Accounts to the SQLite database.
    """
    assert not (followed_id and follower_id)

    build_database(db)

    for account in accounts:
        transformer_account(account)

    db["accounts"].insert_all(accounts, pk="id", alter=True, replace=True)

    if followed_id or follower_id:
        first_seen = datetime.datetime.utcnow().isoformat()
        db["following"].insert_all(
            (
                {
                    "followed_id": followed_id or account["id"],
                    "follower_id": follower_id or account["id"],
                    "first_seen": first_seen,
                }
                for account in accounts
            ),
            ignore=True,
        )