import pytest

from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal


def test_source_guard_failure_rolls_back_before_commit_and_journal_remains_usable(tmp_path):
    path = tmp_path / "fee-pair-source-guard.sqlite3"
    journal = ExecutionDecisionJournal(path)

    def reject_stale_source():
        raise RuntimeError("FEE_PAIR_SOURCE_EXPIRED")

    with pytest.raises(RuntimeError, match="FEE_PAIR_SOURCE_EXPIRED"):
        with journal._transaction(before_commit=reject_stale_source) as cursor:
            cursor.execute(
                "CREATE TABLE fee_pair_source_guard_probe (value TEXT NOT NULL)"
            )
            cursor.execute(
                "INSERT INTO fee_pair_source_guard_probe(value) VALUES('must rollback')"
            )

    assert journal._failed_closed is False
    assert journal._connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='fee_pair_source_guard_probe'"
    ).fetchone() is None

    with journal._transaction() as cursor:
        cursor.execute(
            "CREATE TABLE fee_pair_source_guard_probe (value TEXT NOT NULL)"
        )
        cursor.execute(
            "INSERT INTO fee_pair_source_guard_probe(value) VALUES('later transaction')"
        )
    assert journal._connection.execute(
        "SELECT value FROM fee_pair_source_guard_probe"
    ).fetchone()[0] == "later transaction"
    journal.close()

    reopened = ExecutionDecisionJournal(path)
    try:
        assert reopened._connection.execute(
            "SELECT value FROM fee_pair_source_guard_probe"
        ).fetchone()[0] == "later transaction"
    finally:
        reopened.close()

