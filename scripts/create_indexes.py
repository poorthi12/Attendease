import logging

from app.database import ensure_indexes, get_database


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ensure_indexes(get_database())
    print("AttendEase indexes are ready.")
