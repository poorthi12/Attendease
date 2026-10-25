import logging
from collections.abc import Callable

from pymongo.errors import OperationFailure
from pymongo.database import Database

logger = logging.getLogger(__name__)


def _transactions_unavailable(error: Exception) -> bool:
    if isinstance(error, NotImplementedError):
        return True
    if isinstance(error, OperationFailure):
        message = str(error).lower()
        return error.code in {20, 303} or "transaction numbers are only allowed" in message or "transactions are not supported" in message
    return False


def atomic_write_or_compensate(
    database: Database,
    operation: Callable[[object | None], None],
    compensate: Callable[[], None],
) -> None:
    """Use a Mongo transaction, or run a best-effort compensating fallback.

    The fallback only reports success if every write completed. If a fallback write
    fails, the supplied compensation must remove or restore the operation's changes.
    """
    try:
        with database.client.start_session() as session:
            with session.start_transaction():
                operation(session)
        return
    except (OperationFailure, NotImplementedError) as error:
        if not _transactions_unavailable(error):
            raise

    logger.warning("MongoDB transactions are unavailable; using compensating cleanup for a multi-document change.")
    try:
        operation(None)
    except Exception as operation_error:
        try:
            compensate()
        except Exception as compensation_error:
            logger.error("Compensating cleanup failed (%s).", type(compensation_error).__name__)
            raise RuntimeError("The operation failed and could not be fully recovered. Contact an administrator.") from compensation_error
        raise RuntimeError("The operation failed. Partial changes were rolled back.") from operation_error
