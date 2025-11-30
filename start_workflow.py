from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from temporalio.client import Client

from src.temporal_workflows import MatchingWorkflow


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "src" / "data"


def _load_transactions() -> list[dict]:
    with open(DATA_DIR / "transactions.json", "r", encoding="utf-8") as f:
        return json.load(f)


def _load_attachments() -> list[dict]:
    with open(DATA_DIR / "attachments.json", "r", encoding="utf-8") as f:
        return json.load(f)


async def main() -> None:
    client = await Client.connect("localhost:7233")

    transactions = _load_transactions()
    attachments = _load_attachments()

    # Start workflow execution
    handle = await client.start_workflow(
        MatchingWorkflow.run,
        args=[transactions, attachments],
        id=f"matching-temporal-workflow-{int(time.time())}",
        task_queue="matching-task-queue",
    )

    print(f"Started workflow with ID: {handle.id}")

    # Wait for the workflow to finish and get result
    result = await handle.result()
    print("Workflow result:")
    print("Transactions -> Attachments:", result.tx_to_attachment)
    print("Attachments -> Transactions:", result.attachment_to_tx)


if __name__ == "__main__":
    asyncio.run(main())