import json
import unittest
from pathlib import Path

from src.match import find_attachment, find_transaction


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "src" / "data"


def _load_transactions() -> dict[int, dict]:
    with open(DATA_DIR / "transactions.json", "r", encoding="utf-8") as f:
        transactions_list = json.load(f)
    return {tx["id"]: tx for tx in transactions_list}


def _load_attachments() -> dict[int, dict]:
    with open(DATA_DIR / "attachments.json", "r", encoding="utf-8") as f:
        attachments_list = json.load(f)
    return {att["id"]: att for att in attachments_list}


class MatchFixtureTests(unittest.TestCase):
    """
    Tests that the matching logic reproduces the expected
    mappings used in run.py.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.transactions = _load_transactions()
        cls.attachments = _load_attachments()

        # Same expectations as in run.py
        cls.expected_tx_to_attachment: dict[int, int | None] = {
            2001: 3001,
            2002: 3002,
            2003: 3003,
            2004: 3004,
            2005: 3005,
            2006: None,
            2007: 3006,
            2008: 3007,
            2009: None,
            2010: None,
            2011: None,
            2012: None,
        }

        cls.expected_attachment_to_tx: dict[int, int | None] = {
            3001: 2001,
            3002: 2002,
            3003: 2003,
            3004: 2004,
            3005: 2005,
            3006: 2007,
            3007: 2008,
            3008: None,
            3009: None,
        }

    def test_find_attachment_on_fixture_data(self) -> None:
        """find_attachment should match each transaction to the expected attachment (or None)."""
        all_attachments = list(self.attachments.values())

        for tx_id, expected_att_id in self.expected_tx_to_attachment.items():
            with self.subTest(transaction_id=tx_id):
                transaction = self.transactions[tx_id]
                actual_attachment = find_attachment(transaction, all_attachments)

                if expected_att_id is None:
                    self.assertIsNone(actual_attachment)
                else:
                    self.assertIsNotNone(actual_attachment)
                    self.assertEqual(expected_att_id, actual_attachment["id"])

    def test_find_transaction_on_fixture_data(self) -> None:
        """find_transaction should match each attachment to the expected transaction (or None)."""
        all_transactions = list(self.transactions.values())

        for att_id, expected_tx_id in self.expected_attachment_to_tx.items():
            with self.subTest(attachment_id=att_id):
                attachment = self.attachments[att_id]
                actual_transaction = find_transaction(attachment, all_transactions)

                if expected_tx_id is None:
                    self.assertIsNone(actual_transaction)
                else:
                    self.assertIsNotNone(actual_transaction)
                    self.assertEqual(expected_tx_id, actual_transaction["id"])


class MatchEdgeCaseTests(unittest.TestCase):
    """
    Additional synthetic tests to exercise edge cases:
    - missing data
    - ambiguous candidates
    - noisy / conflicting inputs
    """

    def test_missing_amount_rejects_candidate(self) -> None:
        """If amount is missing on one side, no heuristic match should be created."""
        transaction = {
            "id": 1,
            "date": "2024-01-10",
            "amount": 100.0,
            "contact": "Vendor Oy",
            "reference": None,
        }
        # Attachment without total_amount
        attachment_without_amount = {
            "id": 10,
            "type": "invoice",
            "data": {
                "invoicing_date": "2024-01-09",
                "due_date": "2024-01-20",
                "supplier": "Vendor Oy",
                "reference": None,
                # "total_amount" missing on purpose
            },
        }

        found = find_attachment(transaction, [attachment_without_amount])
        self.assertIsNone(found)

    def test_missing_dates_is_neutral_not_error(self) -> None:
        """
        If dates are missing, the date score becomes neutral (0),
        but a single clear candidate can still be matched by amount/name.
        """
        transaction = {
            "id": 2,
            "date": None,  # missing date
            "amount": 50.0,
            "contact": "Some Vendor",
            "reference": None,
        }
        attachment = {
            "id": 20,
            "type": "invoice",
            "data": {
                "total_amount": 50.0,
                # All date fields missing
                "supplier": "Some Vendor",
                "reference": None,
            },
        }

        found = find_attachment(transaction, [attachment])
        self.assertIsNotNone(found)
        self.assertEqual(20, found["id"])

    def test_conflicting_names_reject_candidate(self) -> None:
        """
        When amounts and dates look plausible but the counterparty name
        clearly conflicts, the candidate should be rejected.
        """
        transaction = {
            "id": 3,
            "date": "2024-03-15",
            "amount": 75.0,
            "contact": "Correct Vendor",
            "reference": None,
        }

        # Same amount/date, but wrong name
        wrong_name_attachment = {
            "id": 30,
            "type": "invoice",
            "data": {
                "total_amount": 75.0,
                "invoicing_date": "2024-03-10",
                "due_date": "2024-03-20",
                "supplier": "Completely Different Vendor",
                "reference": None,
            },
        }

        found = find_attachment(transaction, [wrong_name_attachment])
        # Name mismatch should cause rejection => None
        self.assertIsNone(found)

    def test_ambiguous_candidates_choose_matching_name(self) -> None:
        """
        If there are multiple attachments with same amount/date,
        the one with the matching counterparty name should be selected.
        """
        transaction = {
            "id": 4,
            "date": "2024-04-05",
            "amount": 200.0,
            "contact": "Good Supplier Oy",
            "reference": None,
        }

        common_data = {
            "total_amount": 200.0,
            "invoicing_date": "2024-04-01",
            "due_date": "2024-04-10",
            "reference": None,
        }

        wrong_attachment = {
            "id": 40,
            "type": "invoice",
            "data": {
                **common_data,
                "supplier": "Bad Supplier Oy",
            },
        }
        correct_attachment = {
            "id": 41,
            "type": "invoice",
            "data": {
                **common_data,
                "supplier": "Good Supplier Oy",
            },
        }

        found = find_attachment(transaction, [wrong_attachment, correct_attachment])
        self.assertIsNotNone(found)
        self.assertEqual(41, found["id"])

    def test_date_too_far_apart_rejects_match(self) -> None:
        """
        Even if amounts match, very large date differences (> 30 days)
        should prevent a match.
        """
        transaction = {
            "id": 5,
            "date": "2024-01-01",
            "amount": 300.0,
            "contact": "Far Date Vendor",
            "reference": None,
        }
        # 60 days apart
        attachment_far_date = {
            "id": 50,
            "type": "invoice",
            "data": {
                "total_amount": 300.0,
                "invoicing_date": "2024-03-02",
                "due_date": None,
                "supplier": "Far Date Vendor",
                "reference": None,
            },
        }

        found = find_attachment(transaction, [attachment_far_date])
        self.assertIsNone(found)

    def test_substring_name_match_counts_as_weaker_match(self) -> None:
        """
        Check that a substring relationship (e.g. 'Jane Doe' vs 'Jane Doe Design')
        is treated as a weaker but valid name match.
        """
        transaction = {
            "id": 6,
            "date": "2024-06-20",
            "amount": 120.0,
            "contact": "Jane Doe",
            "reference": None,
        }
        attachment = {
            "id": 60,
            "type": "invoice",
            "data": {
                "total_amount": 120.0,
                "invoicing_date": "2024-06-18",
                "due_date": "2024-07-01",
                "supplier": "Jane Doe Design",
                "reference": None,
            },
        }

        found = find_attachment(transaction, [attachment])
        self.assertIsNotNone(found)
        self.assertEqual(60, found["id"])

    def test_example_company_oy_is_not_treated_as_counterparty(self) -> None:
        """
        Ensure that 'Example Company Oy' is excluded from counterparty comparison
        and the actual other party name is used for matching.
        """
        transaction = {
            "id": 7,
            "date": "2024-05-10",
            "amount": 500.0,
            "contact": "Real Customer Oy",
            "reference": None,
        }
        attachment = {
            "id": 70,
            "type": "invoice",
            "data": {
                "total_amount": 500.0,
                "invoicing_date": "2024-05-05",
                "due_date": "2024-05-20",
                "issuer": "Example Company Oy",      # our own company
                "recipient": "Real Customer Oy",     # counterparty
                "reference": None,
            },
        }

        found = find_attachment(transaction, [attachment])
        self.assertIsNotNone(found)
        self.assertEqual(70, found["id"])


if __name__ == "__main__":
    unittest.main()