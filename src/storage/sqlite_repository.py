import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional


class SQLiteResultRepository:
    def __init__(self, database_path: str):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS test_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    test_run_id TEXT NOT NULL UNIQUE,
                    timestamp_utc TEXT NOT NULL,
                    ammeter_type TEXT NOT NULL,
                    sampling_count INTEGER NOT NULL,
                    sampling_duration_seconds REAL NOT NULL,
                    sampling_frequency_hz REAL NOT NULL,
                    actual_duration_seconds REAL NOT NULL,
                    statistics_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS test_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    test_run_id TEXT NOT NULL,
                    sample_index INTEGER NOT NULL,
                    captured_at_seconds REAL NOT NULL,
                    current_amps REAL NOT NULL,
                    FOREIGN KEY(test_run_id) REFERENCES test_runs(test_run_id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_test_runs_timestamp ON test_runs(timestamp_utc)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_test_runs_ammeter ON test_runs(ammeter_type)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_test_samples_run ON test_samples(test_run_id)"
            )

    def save_result(self, result: Dict[str, Any]) -> str:
        metadata = result["metadata"]
        sampling = metadata["sampling"]
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO test_runs(
                    test_run_id,
                    timestamp_utc,
                    ammeter_type,
                    sampling_count,
                    sampling_duration_seconds,
                    sampling_frequency_hz,
                    actual_duration_seconds,
                    statistics_json,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result["test_run_id"],
                    result["timestamp_utc"],
                    metadata["ammeter_type"],
                    int(sampling["measurements_count"]),
                    float(sampling["total_duration_seconds"]),
                    float(sampling["sampling_frequency_hz"]),
                    float(metadata["actual_duration_seconds"]),
                    json.dumps(result["statistics"]),
                    json.dumps(metadata),
                ),
            )
            cursor.executemany(
                """
                INSERT INTO test_samples(
                    test_run_id,
                    sample_index,
                    captured_at_seconds,
                    current_amps
                )
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        result["test_run_id"],
                        int(sample["sample_index"]),
                        float(sample["captured_at_seconds"]),
                        float(sample["current_amps"]),
                    )
                    for sample in result["samples"]
                ],
            )
        return result["test_run_id"]

    def get_result(self, test_run_id: str) -> Dict[str, Any]:
        with self._connect() as connection:
            cursor = connection.cursor()
            run_row = cursor.execute(
                "SELECT * FROM test_runs WHERE test_run_id = ?",
                (test_run_id,),
            ).fetchone()
            if run_row is None:
                raise FileNotFoundError(
                    f"No archived result with test_run_id '{test_run_id}'"
                )

            samples = cursor.execute(
                """
                SELECT sample_index, captured_at_seconds, current_amps
                FROM test_samples
                WHERE test_run_id = ?
                ORDER BY sample_index ASC
                """,
                (test_run_id,),
            ).fetchall()

        return self._row_to_result(run_row, samples)

    def list_results(
        self, ammeter_type: Optional[str] = None, include_samples: bool = False
    ) -> List[Dict[str, Any]]:
        params: List[Any] = []
        query = "SELECT * FROM test_runs"
        if ammeter_type:
            query += " WHERE ammeter_type = ?"
            params.append(ammeter_type.strip().lower())
        query += " ORDER BY timestamp_utc DESC"

        with self._connect() as connection:
            cursor = connection.cursor()
            run_rows = cursor.execute(query, tuple(params)).fetchall()

            results: List[Dict[str, Any]] = []
            for run_row in run_rows:
                sample_rows: List[sqlite3.Row] = []
                if include_samples:
                    sample_rows = cursor.execute(
                        """
                        SELECT sample_index, captured_at_seconds, current_amps
                        FROM test_samples
                        WHERE test_run_id = ?
                        ORDER BY sample_index ASC
                        """,
                        (run_row["test_run_id"],),
                    ).fetchall()
                results.append(self._row_to_result(run_row, sample_rows))
            return results

    @staticmethod
    def _row_to_result(
        run_row: sqlite3.Row, sample_rows: List[sqlite3.Row]
    ) -> Dict[str, Any]:
        metadata = json.loads(run_row["metadata_json"])
        statistics = json.loads(run_row["statistics_json"])
        samples = [
            {
                "sample_index": int(sample["sample_index"]),
                "captured_at_seconds": float(sample["captured_at_seconds"]),
                "current_amps": float(sample["current_amps"]),
            }
            for sample in sample_rows
        ]
        return {
            "test_run_id": run_row["test_run_id"],
            "timestamp_utc": run_row["timestamp_utc"],
            "metadata": metadata,
            "samples": samples,
            "statistics": statistics,
        }
