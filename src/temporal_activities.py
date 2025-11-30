from __future__ import annotations

from typing import List, Optional

from temporalio import activity

from src.match import Attachment, Transaction, find_attachment, find_transaction


@activity.defn
async def find_attachment_activity(
    transaction: Transaction,
    attachments: List[Attachment],
) -> Optional[Attachment]:
    """
    Async activity wrapper around find_attachment.

    The underlying matching function is synchronous and pure,
    but defining the activity as async keeps the Temporal worker
    configuration simple (no custom activity_executor needed).
    """
    return find_attachment(transaction, attachments)


@activity.defn
async def find_transaction_activity(
    attachment: Attachment,
    transactions: List[Transaction],
) -> Optional[Transaction]:
    """
    Async activity wrapper around find_transaction.
    """
    return find_transaction(attachment, transactions)