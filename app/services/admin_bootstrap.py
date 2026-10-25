from datetime import datetime, timezone

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.models.user import user_document
from app.security.password import hash_password
from app.services.atomic_write import atomic_write_or_compensate

BOOTSTRAP_ID = "initial_admin"


class BootstrapAlreadyComplete(Exception):
    pass


class EmailAlreadyRegistered(Exception):
    pass


def first_admin_setup_available(database: Database) -> bool:
    return not (
        database.admin_bootstrap.find_one({"_id": BOOTSTRAP_ID})
        or database.users.find_one({"role": "admin"}, {"_id": 1})
    )


def create_first_admin(database: Database, name: str, email: str, password: str, source: str) -> dict:
    if not first_admin_setup_available(database):
        raise BootstrapAlreadyComplete

    account = user_document(name, email, "admin", hash_password(password))
    created_at = datetime.now(timezone.utc)
    marker = {"_id": BOOTSTRAP_ID, "admin_id": account["_id"], "source": source, "created_at": created_at}
    audit = {
        "actor_id": account["_id"],
        "action": "admin.bootstrapped",
        "target_id": account["_id"],
        "created_at": created_at,
    }

    def insert_document(collection, document, session):
        options = {"session": session} if session is not None else {}
        collection.insert_one(document, **options)

    def operation(session):
        insert_document(database.admin_bootstrap, marker, session)
        insert_document(database.users, account, session)
        insert_document(database.audit_logs, audit, session)

    def compensate():
        database.audit_logs.delete_one({"actor_id": account["_id"], "action": "admin.bootstrapped"})
        database.users.delete_one({"_id": account["_id"]})
        database.admin_bootstrap.delete_one({"_id": BOOTSTRAP_ID, "admin_id": account["_id"]})

    try:
        atomic_write_or_compensate(database, operation, compensate)
    except (DuplicateKeyError, RuntimeError) as exc:
        cause = exc.__cause__ if isinstance(exc, RuntimeError) else exc
        if not isinstance(cause, DuplicateKeyError):
            raise
        if not first_admin_setup_available(database):
            raise BootstrapAlreadyComplete from exc
        raise EmailAlreadyRegistered from exc
    return account
