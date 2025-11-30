import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from src.temporal_workflows import MatchingWorkflow
from src.temporal_activities import (
    find_attachment_activity,
    find_transaction_activity,
)


async def main() -> None:
    # Connect to local Temporal dev server
    client = await Client.connect("localhost:7233")

    # Worker listens on a task queue and executes workflows/activities
    worker = Worker(
        client,
        task_queue="matching-task-queue",
        workflows=[MatchingWorkflow],
        activities=[find_attachment_activity, find_transaction_activity],
    )

    print("Worker started, listening on task queue 'matching-task-queue'...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())