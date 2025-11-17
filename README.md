# NoCFO Homework Assignment – AI Engineer

This repository contains a matching engine that links bank transactions to their supporting attachments (invoices, receipts) using a combination of reference numbers and heuristic rules.

---

## Table of Contents

- [How to Run](#how-to-run)
- [Architecture Overview](#architecture-overview)
- [Matching Logic](#matching-logic)
  - [Reference Matching](#reference-matching)
  - [Heuristic Scoring](#heuristic-scoring)
- [Technical Decisions](#technical-decisions)

---

## How to Run

### Prerequisites

- Python 3.10+
- No external dependencies required beyond the standard library

### Project Structure

```text
.
├── run.py
└── src
    ├── match.py
    └── data
        ├── transactions.json
        └── attachments.json
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

- `_normalize_reference_value` – Normalizes reference numbers for comparison
- `_parse_date`, `_attachment_dates` – Date parsing and extraction
- `_normalize_name`, `_attachment_counterparty_names` – Name normalization and extraction
- `_name_similarity_score` – Computes name similarity
- `_find_by_reference` – Reference-based lookup
- `_score_pair` – Heuristic scoring function

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

If a normalized reference match is found between a transaction and attachment:
- The match is immediately returned
- Heuristic scoring is skipped

**Rule:** *A reference number match is always a 1:1 match. If a reference number match is found, the link should always be created.*

---

### Heuristic Scoring

When no reference match exists, the algorithm uses `_score_pair` to rate transaction–attachment pairs based on three signals:

#### 1. Amount (Hard Requirement)

- Both transaction and attachment **must** have an amount
- Absolute values must match within tolerance (±0.01)
- If amounts are missing or differ, the pair is rejected (`score = 0.0`)
- Valid candidates receive a base score of **10.0**

#### 2. Date Proximity (Bonus: 0–10 points)

The algorithm:
- Parses the transaction date
- Collects relevant attachment dates:
  - `invoicing_date`
  - `due_date`
  - `receiving_date` (for receipts)
- Computes day differences and uses the smallest difference (`min_diff`)

**Scoring rules:**
- `min_diff > 30 days` → Pair rejected (`score = 0.0`)
- Otherwise: `date_score = max(0, 10 - min_diff)`
  - 0 days difference → +10
  - 1 day → +9
  - 9 days → +1
  - 10–30 days → +0 (allowed but not boosted)

This accommodates immediate payments, on-time payments, and slightly early/late payments.

#### 3. Counterparty Name (Penalty/Bonus: −5 to +10 points)

Counterparty information is extracted from:
- `issuer`
- `recipient`
- `supplier` (merchant for receipts)

**Normalization:**
- Lowercase, trimmed, collapsed whitespace
- Excludes "Example Company Oy" (refers to the company itself)

**Similarity scoring (`_name_similarity_score`):**
- **2** – Exact match (e.g., "jane smith")
- **1** – Substring match (e.g., "jane doe" vs "jane doe design")
- **0** – Neutral (no contact or no usable names)
- **−1** – Explicit mismatch (both sides have names but incompatible)

**Integration:**
- If name score is −1 and transaction has a contact → Pair rejected
- Otherwise: `score += name_score * 5.0`
  - 2 → +10 (exact match)
  - 1 → +5 (partial match)
  - 0 → +0 (no information)

---

## Technical Decisions

### Handling Missing, Ambiguous, and Noisy Data

| Scenario | Behavior |
|----------|----------|
| **Missing reference** | Gracefully falls back to heuristics |
| **Missing amount** | Candidate rejected (amount is required) |
| **Missing dates** | Date bonus skipped |
| **Missing names** | Name score neutral (0, no penalty) |
| **Conflicting names** | Candidate rejected if transaction has contact |
| **Ambiguous matches** | Only candidates with `score > 0.0` considered |

**Conservative approach:**
- Favors explainable matches
- Minimizes false positives
- Returns `None` when no confident match exists

### Determinism

The algorithm maintains `best_score` and `best_candidate`, updating only when:

```python
if score > best_score:
    best_score = score
    best_candidate = ...
```

**Result:**
- If multiple candidates tie, the first one in input order is retained
- Given fixed input lists, results are fully deterministic across runs

---

## License

This project is provided as-is for evaluation purposes.