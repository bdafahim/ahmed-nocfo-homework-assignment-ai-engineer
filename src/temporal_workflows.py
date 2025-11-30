from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Optional

from temporalio import workflow

from src.match import Attachment, Transaction
from src.temporal_activities import (
    find_attachment_activity,
    find_transaction_activity,
)


@dataclass
class MatchingResult:
    tx_to_attachment: Dict[int, Optional[int]]
    attachment_to_tx: Dict[int, Optional[int]]


@workflow.defn
class MatchingWorkflow:
    @workflow.run
    async def run(
        self,
        transactions: List[Transaction],
        attachments: List[Attachment],
    ) -> MatchingResult:
        tx_to_attachment: Dict[int, Optional[int]] = {}
        attachment_to_tx: Dict[int, Optional[int]] = {}

        # 1) For each transaction, find best attachment
        for tx in transactions:
            tx_id = tx.get("id")
            matched_attachment = await workflow.execute_activity(
                find_attachment_activity,
                args=[tx, attachments],  # <-- pass via args list
                schedule_to_close_timeout=timedelta(seconds=30),
            )
            if matched_attachment is None:
                tx_to_attachment[tx_id] = None
            else:
                tx_to_attachment[tx_id] = matched_attachment.get("id")

        # 2) For each attachment, find best transaction
        for att in attachments:
            att_id = att.get("id")
            matched_transaction = await workflow.execute_activity(
                find_transaction_activity,
                args=[att, transactions],  # <-- pass via args list
                schedule_to_close_timeout=timedelta(seconds=30),
            )
            if matched_transaction is None:
                attachment_to_tx[att_id] = None
            else:
                attachment_to_tx[att_id] = matched_transaction.get("id")

        return MatchingResult(
            tx_to_attachment=tx_to_attachment,
            attachment_to_tx=attachment_to_tx,
        )