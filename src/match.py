from __future__ import annotations

from datetime import datetime, date
from typing import Optional, List, Dict, Any

Attachment = dict[str, Any]
Transaction = dict[str, Any]


def find_attachment(
    transaction: Transaction,
    attachments: list[Attachment],
) -> Attachment | None:
    """Find the best matching attachment for a given transaction."""
    # 1) Reference-based match (always 1:1 if exists)
    normalized_transaction_reference = _normalize_reference_value(transaction.get("reference"))
    attachment_by_reference = _find_by_reference(normalized_transaction_reference, attachments, is_attachment=True)
    if attachment_by_reference is not None:
        return attachment_by_reference

    # 2) Heuristic scoring using amount + date + counterparty
    best_score = 0.0
    best_attachment: Optional[Attachment] = None

    for att in attachments:
        score = _compute_match_score(transaction, att)
        # Find the highest-scoring candidate,
        if score > best_score:
            best_score = score
            best_attachment = att

    # Only return a match if at least one candidate passed the hard filters
    # (amount, reasonable date, non-conflicting names) and achieved a positive score.
    # If all candidates scored 0.0, treat this as "no confident match" and return None.
    return best_attachment if best_score > 0.0 else None

def find_transaction(
    attachment: Attachment,
    transactions: list[Transaction],
) -> Transaction | None:
    """Find the best matching transaction for a given attachment."""
    # 1) Reference-based match
    data = attachment.get("data", {}) or {}
    normalized_attachment_reference = _normalize_reference_value(data.get("reference"))
    transaction_by_reference = _find_by_reference(normalized_attachment_reference, transactions, is_attachment=False)
    if transaction_by_reference is not None:
        return transaction_by_reference

    # 2) Heuristic scoring (same logic as in find_attachment)
    best_score = 0.0
    best_transaction: Optional[Transaction] = None

    for tx in transactions:
        score = _compute_match_score(tx, attachment)
        # Find the highest-scoring candidate,
        if score > best_score:
            best_score = score
            best_transaction = tx

    # Same logic as in find_attachment: only link the attachment to a transaction if some candidate achieved a positive score.
    # A score of 0.0 across all candidates means the data did not provide enough evidence for a reliable match, so return None.
    return best_transaction if best_score > 0.0 else None



# -----------------------------
# Helper functions
# -----------------------------


def _normalize_reference_value(ref: Optional[str]) -> Optional[str]:
    """
    Normalize reference numbers by:
    - Converting to string
    - Uppercasing
    - Removing spaces
    - Stripping leading 'RF'
    - Stripping leading zeros

    Returns None if the input is falsy after normalization.
    """
    if not ref:
        return None
    normalized_ref = str(ref).upper()
    normalized_ref = normalized_ref.replace(" ", "")
    if normalized_ref.startswith("RF"):
        normalized_ref = normalized_ref[2:]
    # Strip leading zeros
    normalized_ref = normalized_ref.lstrip("0")
    return normalized_ref or None


def _parse_date(value: Optional[str]) -> Optional[date]:
    """Parse a YYYY-MM-DD date string into a date object."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _attachment_dates(att: Attachment) -> List[date]:
    """
    Collect all relevant dates from an attachment:
    - invoicing_date
    - due_date
    - receiving_date (for receipts)
    """
    data = att.get("data", {}) or {}
    dates: List[date] = []
    for key in ("invoicing_date", "due_date", "receiving_date"):
        parsed_date = _parse_date(data.get(key))
        if parsed_date:
            dates.append(parsed_date)
    return dates


def _normalize_name(name: Optional[str]) -> Optional[str]:
    """Normalize a name for comparison: lowercase and strip extra spaces."""
    if not name:
        return None
    normalized_name = " ".join(str(name).strip().lower().split())
    return normalized_name or None


def _attachment_counterparty_names(att: Attachment) -> List[str]:
    """
    Return all possible counterparty names from an attachment.

    Exclude the company itself ("Example Company Oy"), since that
    represents the company itself, not the counterparty.
    """
    data = att.get("data", {}) or {}
    names: List[str] = []

    # Normalized name for the company itself
    company_self = _normalize_name("Example Company Oy")

    for key in ("issuer", "recipient", "supplier"):
        value = data.get(key)
        norm = _normalize_name(value)
        if not norm:
            continue
        # Skip the name of the company itself
        if company_self and norm == company_self:
            continue
        names.append(norm)

    return names


def _name_similarity_score(contact: Optional[str], att: Attachment) -> int:
    """
    Compare the transaction contact with attachment counterparties.

    Returns:
    - 2 for a strong match (exact normalized equality)
    - 1 for a weaker match (one is substring of the other)
    - 0 if contact is None or no information
    - -1 if contact exists but clearly does not match any counterparty
    """
    norm_contact = _normalize_name(contact)
    if not norm_contact:
        return 0  # no contact info: neutral, not a penalty

    candidates = _attachment_counterparty_names(att)
    if not candidates:
        # We know the contact but attachment has no names to compare.
        # Treat as neutral instead of explicit mismatch.
        return 0

    for candidate in candidates:
        if norm_contact == candidate:
            return 2
        if norm_contact in candidate or candidate in norm_contact:
            return 1

    return -1  # explicit mismatch when we have info on both sides


def _compute_amount_base_score(transaction: Transaction, attachment: Attachment) -> Optional[float]:
    """
    Validate that both sides have a compatible amount and return the
    base score contributed by the amount signal.

    Returns:
        - 10.0 if the absolute amounts match within a small tolerance
        - None if amounts are missing or inconsistent, meaning the
          candidate should be rejected
    """
    data = attachment.get("data", {}) or {}
    tx_amount = transaction.get("amount")
    att_amount = data.get("total_amount")

    if tx_amount is None or att_amount is None:
        return None

    # Compare absolute values to handle negative/positive signs
    if abs(abs(tx_amount) - abs(att_amount)) > 0.01:
        return None

    return 10.0


def _compute_date_bonus_score(transaction: Transaction, attachment: Attachment) -> Optional[float]:
    """
    Compute an additional score based on how close the transaction date
    is to the relevant dates on the attachment (invoicing, due, receiving).

    Returns:
        - A non-negative float in [0, 10] representing the date-based bonus
        - 0.0 if there is not enough date information to use (no penalty)
        - None if dates are too far apart (> 30 days), meaning the
          candidate should be rejected
    """
    tx_date = _parse_date(transaction.get("date"))
    attachment_dates = _attachment_dates(attachment)

    if not tx_date or not attachment_dates:
        # No usable date information on one or both sides: neutral
        return 0.0

    day_differences = [abs((tx_date - attachment_date).days) for attachment_date in attachment_dates]
    min_difference_in_days = min(day_differences)

    # If dates are too far apart, do not consider this a confident match
    if min_difference_in_days > 30:
        return None

    # Smaller difference -> larger bonus, capped at 10
    return max(0.0, 10.0 - float(min_difference_in_days))


def _compute_match_score(transaction: Transaction, attachment: Attachment) -> float:
    """
    Compute a heuristic score for how well this transaction matches this attachment,
    using three signals:
      - Amount (required, acts as a hard filter and base score)
      - Date proximity (optional bonus, can also reject if too far)
      - Counterparty name similarity (optional bonus, can also reject on conflict)

    Assumes there is NO reference match (reference matches are handled separately).
    """
    # 1) Amount: hard requirement + base score
    amount_score = _compute_amount_base_score(transaction, attachment)
    if amount_score is None:
        return 0.0

    score = amount_score

    # 2) Date proximity: bonus if close, rejection if too far
    date_bonus_score = _compute_date_bonus_score(transaction, attachment)
    if date_bonus_score is None:
        return 0.0
    score += date_bonus_score

    # 3) Counterparty name similarity
    name_score = _name_similarity_score(transaction.get("contact"), attachment)
    if transaction.get("contact") and name_score < 0:
        # We know the contact and it explicitly conflicts with all candidate names
        return 0.0

    # Scale name similarity (2, 1, 0) to a meaningful range (+10, +5, 0)
    score += float(name_score) * 5.0

    return score


def _find_by_reference(
    ref_value: Optional[str], attachments_or_transactions: List[dict], is_attachment: bool
) -> Optional[dict]:
    """
    Generic helper to find a single item by normalized reference.

    - For transactions, reference is in item["reference"]
    - For attachments, reference is in item["data"]["reference"]

    ref_value must already be normalized.
    """
    if not ref_value:
        return None

    for item in attachments_or_transactions:
        if is_attachment:
            data = item.get("data", {}) or {}
            item_ref_raw = data.get("reference")
        else:
            item_ref_raw = item.get("reference")

        item_ref = _normalize_reference_value(item_ref_raw)
        if item_ref and item_ref == ref_value:
            return item

    return None