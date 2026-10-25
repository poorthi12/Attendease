import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import ensure_indexes, get_database
from app.services.admin_bootstrap import (
    BootstrapAlreadyComplete,
    EmailAlreadyRegistered,
    create_first_admin,
)


def main() -> None:
    email = (os.environ.get("ADMIN_EMAIL") or input("Administrator email: ")).strip().lower()
    name = (os.environ.get("ADMIN_NAME") or input("Administrator name: ")).strip()
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Administrator password (10+ characters): ")
    database = get_database()
    ensure_indexes(database)
    try:
        create_first_admin(database, name, email, password, "cli")
    except BootstrapAlreadyComplete as exc:
        raise SystemExit("Administrator setup is already complete. No account was created.") from exc
    except EmailAlreadyRegistered as exc:
        raise SystemExit("That email address is already registered.") from exc
    print("Administrator account created. Sign in at /login/admin.")


if __name__ == "__main__":
    main()
