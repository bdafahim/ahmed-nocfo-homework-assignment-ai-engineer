# NoCFO Homework Assignment – AI Engineer

This repository contains a matching engine that links bank transactions to their supporting attachments (invoices, receipts) using a combination of reference numbers and heuristic rules.

---

## Table of Contents

- [How to Run](#how-to-run)
- [Running Unit Tests](#running-unit-tests)
- [Architecture Overview](#architecture-overview)
- [Matching Logic](#matching-logic)
  - [Reference Matching](#reference-matching)
  - [Heuristic Scoring](#heuristic-scoring)
- [Technical Decisions](#technical-decisions)
- [Temporal Integration](#temporal-integration)
- [License](#license)

---

## How to Run

### Prerequisites

- Python 3.10+
- No external dependencies required beyond the standard library

### Project Structure

```text
.
├── run.py                     # CLI report using pure Python matching
├── worker.py                  # Temporal Worker (runs activities)
├── start_workflow.py          # Temporal client starter script
├── src
│   ├── match.py               # Core matching logic (find_attachment / find_transaction)
│   ├── temporal_activities.py # Temporal activities wrapping the core logic
│   ├── temporal_workflows.py  # Temporal workflow orchestration
│   └── data
│       ├── transactions.json  # Fixture transactions
│       └── attachments.json   # Fixture attachments
└── tests
    └── test_match.py          # Unit tests (fixtures + edge cases)
```

### Running the Matching Report

From the project root:

```bash
python run.py
```

This will:
- Load fixture data from `src/data/transactions.json` and `src/data/attachments.json`
- Call `find_attachment` and `find_transaction` from `src/match.py`
- Print a report showing, for each transaction:
  - The expected attachment
  - The attachment found by the algorithm
  - Whether they match (✅ / ❌)
  - Similarly in the opposite direction (attachment → transaction)

The implementation is fully deterministic, so rerunning `python run.py` with the same data always produces the same output.

---

## Running Unit Tests

Unit tests are provided under `tests/test_match.py`. They cover:

**Expected mappings** from the fixture data (the same expectations used in `run.py`)

**Edge cases** for:
- Missing amount
- Missing dates
- Conflicting counterparty names
- Ambiguous candidates with same amount/date
- Date distance cutoff (> 30 days)
- Substring name matches
- Excluding "Example Company Oy" from counterparty comparison

From the project root:

```bash
python -m unittest tests.test_match
```

---

### ⚙️ Troubleshooting

#### `python` is not recognized

If you see an error like:

```bash
python: command not found
# or
'python' is not recognized as an internal or external command 

#use 
'python3' instead of 'python'
```
---

## Architecture Overview

### Core Functions

The matching logic is implemented in `src/match.py` and exposed via two main functions:

```python
find_attachment(transaction, attachments) -> Attachment | None
find_transaction(attachment, transactions) -> Transaction | None
```

Both functions:
1. First attempt a **reference-based match** (strongest signal)
2. If no reference match is found, fall back to a **heuristic scoring model** that combines:
   - Amount matching
   - Date proximity
   - Counterparty name similarity

### Supporting Helpers

Key helper functions in `match.py`:

- `_normalize_reference_value` – Normalizes reference numbers for comparison
- `_parse_date`, `_attachment_dates` – Date parsing and extraction
- `_normalize_name`, `_attachment_counterparty_names` – Name normalization and counterparty extraction
- `_name_similarity_score` – Computes name similarity score (2, 1, 0, or -1)
- `_find_by_reference` – Reference-based lookup for both directions
- `_compute_amount_base_score` – Validates and scores the amount signal
- `_compute_date_bonus_score` – Computes the date proximity bonus or rejects if too far
- `_compute_match_score` – Combines amount, date, and name signals into a single match score

`find_attachment` and `find_transaction` both delegate the actual scoring of a transaction–attachment pair to `_compute_match_score`.

---

## Matching Logic

### Reference Matching

**Goal:** Reference matches are always 1:1 and must be preferred when present.

**Implementation:**

Reference numbers are normalized by:
- Converting to string
- Uppercasing
- Removing whitespace
- Stripping leading "RF" (for RF references)
- Stripping leading zeros

If a normalized reference match is found between a transaction and an attachment:
- The matched item is returned immediately
- Heuristic scoring is skipped

**Rule:** *A reference number match is always a 1:1 match. If a reference number match is found, the link should always be created.*

---

### Heuristic Scoring

When no reference match exists, the algorithm uses `_compute_match_score(transaction, attachment)` to rate transaction–attachment pairs based on three signals:

1. **Amount** (hard requirement + base score, via `_compute_amount_base_score`)
2. **Date proximity** (0–10 point bonus, via `_compute_date_bonus_score`)
3. **Counterparty name** (penalty/bonus based on similarity score)

The functions `find_attachment` and `find_transaction`:
- Iterate through all candidates
- Compute a match score using `_compute_match_score`
- Track the highest-scoring candidate
- Only return a match if `best_score > 0.0`; otherwise they return `None` ("no confident match")

#### 1. Amount (Hard Requirement, via `_compute_amount_base_score`)

Amount is treated as a hard filter and base signal.

In `_compute_amount_base_score`:
- Both transaction and attachment **must** have an amount
- Absolute values must match within a small tolerance (±0.01)
- If amounts are missing or differ too much, the function returns `None`, and the candidate is rejected
- For valid candidates, it returns a base score of **10.0**

This ensures:
- No attachment is matched to a transaction with a clearly different amount
- Every accepted match is at least supported by the amount signal

#### 2. Date Proximity (Bonus: 0–10 points, via `_compute_date_bonus_score`)

To reflect realistic payment behavior (pay immediately, on due date, or slightly early/late), `_compute_date_bonus_score`:

- Parses the transaction date
- Collects relevant attachment dates from:
  - `invoicing_date`
  - `due_date`
  - `receiving_date` (for receipts)
- Computes day differences for each attachment date
- Uses the smallest difference (`min_difference_in_days`) as the relevant distance

**Scoring rules:**
- If `min_difference_in_days > 30`:
  - Returns `None`, and the candidate is rejected as not credibly related
- Otherwise returns:
  ```python
  date_score = max(0.0, 10.0 - min_difference_in_days)
  ```
  - 0 days difference → +10
  - 1 day → +9
  - 9 days → +1
  - 10–30 days → +0 (allowed, but not boosted)

- If either the transaction date or all attachment dates are missing, `_compute_date_bonus_score` returns **0.0** (neutral: no bonus, no penalty)

This accommodates immediate payments, on-time payments, and slightly early/late payments within a reasonable window.

#### 3. Counterparty Name (Penalty/Bonus: −5 to +10 points)

Counterparty information is extracted from:
- `issuer`
- `recipient`
- `supplier` (merchant for receipts)

**Normalization** (`_normalize_name`):
- Lowercase
- Trim whitespace
- Collapse multiple spaces into one

**Special rule:**
`_attachment_counterparty_names` explicitly excludes "Example Company Oy" because that always refers to the company itself, not the counterparty.

**Similarity scoring** (`_name_similarity_score`):
- **2** – Exact normalized match (e.g., "jane smith")
- **1** – Substring match (e.g., "jane doe" vs "jane doe design")
- **0** – Neutral:
  - Transaction has no contact, or
  - Attachment has no usable names
- **−1** – Explicit mismatch when both sides have names but none are compatible

**Integration into `_compute_match_score`:**
- If the transaction has a contact and the name score is **−1**, the candidate is rejected
- Otherwise, the score is updated as:
  ```python
  score += name_score * 5.0
  ```
  - 2 → +10 (exact match)
  - 1 → +5 (partial/substring match)
  - 0 → +0 (no information)


## Technical Decisions

### Handling Missing, Ambiguous, and Noisy Data

| Scenario | Behavior |
|----------|----------|
| **Missing reference** | Gracefully falls back to heuristics |
| **Missing amount** | Candidate rejected (amount is required for heuristic matching) |
| **Missing dates** | Date bonus returns 0.0 (neutral) if dates are missing |
| **Dates > 30 days apart** | Candidate rejected (treated as unrelated) |
| **Missing names** | Name score is neutral (0, no penalty) |
| **Conflicting names** | Candidate rejected if transaction has contact and names explicitly differ |
| **Ambiguous matches** | Only candidates with `score > 0.0` are considered; else `None` is returned |

**Conservative approach:**
- Favors explainable, well-supported matches
- Minimizes false positives by rejecting mismatched amounts, far-apart dates, and conflicting names
- Returns `None` when the available data does not justify a confident match

These behaviors are explicitly exercised in `tests/test_match.py` via fixture-based and synthetic tests.

### Determinism

The algorithm maintains `best_score` and `best_candidate`, updating only when:

```python
if score > best_score:
    best_score = score
    best_candidate = ...
```

**Result:**
- If multiple candidates tie with the same score, the first one in the input order is retained
- Given fixed input lists, results are fully deterministic across runs

---

## Temporal Integration
In addition to the plain Python entry point (`run.py`), the same matching logic is exposed as a Temporal workflow for durable and observable execution. This is optional and mainly demonstrates how the matching engine can be run as a resilient background workflow.

### Components

#### `worker.py`
Starts a Temporal Worker on the task queue `matching-task-queue`. It registers two async activities:
- `find_attachment_activity` – wraps `find_attachment`
- `find_transaction_activity` – wraps `find_transaction`

#### `src/temporal_activities.py`
Contains the activity definitions that call the core matching functions from `match.py`.

#### `src/temporal_workflows.py`
Defines a `MatchingWorkflow` that:
- Receives the full list of transactions and attachments as input
- For each transaction, calls `find_attachment_activity`
- For each attachment, calls `find_transaction_activity`
- Returns a `MatchingResult` dataclass with:
  - `tx_to_attachment: dict[int, int | None]`
  - `attachment_to_tx: dict[int, int | None]`

#### `start_workflow.py`
Small client script that:
- Loads the fixture JSON from `src/data`
- Connects to the Temporal server at `localhost:7233`
- Starts `MatchingWorkflow` with a unique workflow ID on `matching-task-queue`
- Awaits completion and prints the resulting mappings

### Additional Prerequisites

- Temporal CLI installed
- A local Temporal dev server running

#### 1. Install Temporal CLI

**macOS (Homebrew):**
```bash
brew install temporal
```

After installation, verify:
```bash
temporal --version
```

**Windows:**

One simple option is to use `npm`:
```bash
npm install -g @temporalio/cli
```

Then verify:
```bash
temporal --version
```

(You can also use prebuilt binaries from Temporal's official releases if you prefer.)



### Running with Temporal

From the project root:

**1. Start Temporal dev server** (if not already running):
```bash
temporal server start-dev
```

**2. Start the Temporal worker** in a new terminal:
```bash
python worker.py
# or
python3 worker.py
```

The worker will log that it is listening on the task queue `matching-task-queue`.

**3. Start the workflow** from another terminal:
```bash
python start_workflow.py
# or
python3 start_workflow.py
```

You should see output similar to:
```text
Started workflow with ID: matching-temporal-workflow-XXXXXXXX
Workflow result:
Transactions -> Attachments: { ... }
Attachments -> Transactions: { ... }
```

**4. Inspect the workflow** in the Temporal Web UI:

- Open `http://localhost:8233` in your browser
- Select the `default` namespace
- Locate the workflow by its ID (printed by `start_workflow.py`)

You can see:
- Full event history (workflow started, each activity invocation, workflow completed)
- Inputs and outputs for each activity call
- The final `MatchingResult` returned by the workflow

This setup shows how the matching logic can be run as a durable, observable workflow, suitable for production environments where reliability and auditability are important.

---


## License

This project is provided as-is for evaluation purposes.
