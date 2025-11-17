from __future__ import annotations

from datetime import datetime, date
from typing import Optional, List, Dict, Any

Attachment = dict[str, dict]
Transaction = dict[str, dict]


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
        score = _score_pair(transaction, att)
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
        score = _score_pair(tx, attachment)
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
    s = str(ref).upper()
    s = s.replace(" ", "")
    if s.startswith("RF"):
        s = s[2:]
    # Strip leading zeros
    s = s.lstrip("0")
    return s or None


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
        d = _parse_date(data.get(key))
        if d:
            dates.append(d)
    return dates


def _normalize_name(name: Optional[str]) -> Optional[str]:
    """Normalize a name for comparison: lowercase and strip extra spaces."""
    if not name:
        return None
    s = " ".join(str(name).strip().lower().split())
    return s or None


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

    for c in candidates:
        if norm_contact == c:
            return 2
        if norm_contact in c or c in norm_contact:
            return 1

    return -1  # explicit mismatch when we have info on both sides


def _score_pair(transaction: Transaction, attachment: Attachment) -> float:
    """
    Compute a heuristic score for how well this transaction matches this attachment,
    using amount, date and counterparty name.

    Assumes there is NO reference match (reference matches are handled separately).
    """
    data: Dict[str, Any] = attachment.get("data", {}) or {}

    tx_amount = transaction.get("amount")
    att_amount = data.get("total_amount")

    # Amount must exist and match in absolute value
    if tx_amount is None or att_amount is None:
        return 0.0

    if abs(abs(tx_amount) - abs(att_amount)) > 0.01:
        return 0.0

    # Base score for amount match
    score = 10.0

    # Date proximity
    tx_date = _parse_date(transaction.get("date"))
    att_dates = _attachment_dates(attachment)

    if tx_date and att_dates:
        diffs = [abs((tx_date - d).days) for d in att_dates]
        min_diff = min(diffs)
        # If dates are too far apart, do not consider this a confident match
        if min_diff > 30:
            return 0.0
        # Smaller difference -> larger bonus, capped at 10
        date_score = max(0.0, 10.0 - float(min_diff))
        score += date_score

    # Counterparty name similarity
    name_score = _name_similarity_score(transaction.get("contact"), attachment)
    if transaction.get("contact") and name_score < 0:
        # We know the contact and it explicitly conflicts with all candidate names
        return 0.0

    score += float(name_score) * 5.0  # give strong weight to names when present

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