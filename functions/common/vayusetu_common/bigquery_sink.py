"""Cost-aware BigQuery writer.

Two write strategies are supported:

``load`` (default)
    Uses ``load_table_from_json`` which is a BigQuery *load job*. Load jobs are
    free of charge but limited to 1,500 per table per day, which comfortably
    covers hackathon and pilot traffic.

``streaming``
    Uses ``insert_rows_json`` (legacy streaming inserts, USD 0.01 per 200 MB).
    Switch to this mode with ``BIGQUERY_WRITE_MODE=streaming`` when a deployment
    outgrows the load job quota; the code path is otherwise identical.

Set ``BIGQUERY_ENABLED=false`` to disable BigQuery entirely (local emulator).
"""

from __future__ import annotations

import datetime as dt
import io
import json
import logging
from typing import Any, Dict, Iterable, List, Optional

from vayusetu_common.retry import retry_with_backoff

logger = logging.getLogger(__name__)


def _serialise(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialise(v) for v in value]
    if hasattr(value, "latitude") and hasattr(value, "longitude"):
        return {"latitude": value.latitude, "longitude": value.longitude}
    return value


class BigQuerySink:
    """Write rows to BigQuery with retries and a configurable strategy."""

    def __init__(
        self,
        project_id: str,
        dataset_id: str,
        mode: str = "load",
        enabled: bool = True,
        client: Optional[Any] = None,
    ) -> None:
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.mode = mode.lower()
        self.enabled = enabled
        if self.mode not in {"load", "streaming"}:
            raise ValueError("mode must be 'load' or 'streaming'")
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from google.cloud import bigquery  # imported lazily to keep cold starts small

            self._client = bigquery.Client(project=self.project_id)
        return self._client

    def table_ref(self, table_id: str) -> str:
        return f"{self.project_id}.{self.dataset_id}.{table_id}"

    def write(self, table_id: str, rows: Iterable[Dict[str, Any]]) -> int:
        """Write ``rows`` to ``table_id``; returns the number of rows written."""
        payload: List[Dict[str, Any]] = [_serialise(row) for row in rows]
        if not payload:
            return 0
        if not self.enabled:
            logger.info(
                "BigQuery disabled; skipping %d row(s) for %s", len(payload), table_id, extra={"table": table_id}
            )
            return 0

        if self.mode == "streaming":
            self._stream(table_id, payload)
        else:
            self._load(table_id, payload)
        logger.info("Wrote %d row(s) to %s", len(payload), self.table_ref(table_id), extra={"table": table_id})
        return len(payload)

    @retry_with_backoff(max_attempts=4, base_delay=2.0, max_delay=30.0, operation_name="bigquery_load")
    def _load(self, table_id: str, payload: List[Dict[str, Any]]) -> None:
        from google.cloud import bigquery

        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            ignore_unknown_values=True,
        )
        buffer = io.BytesIO()
        for row in payload:
            buffer.write(json.dumps(row, default=str).encode("utf-8"))
            buffer.write(b"\n")
        buffer.seek(0)
        job = self.client.load_table_from_file(buffer, self.table_ref(table_id), job_config=job_config)
        job.result(timeout=120)
        if job.errors:
            raise RuntimeError(f"BigQuery load job reported errors: {job.errors}")

    @retry_with_backoff(max_attempts=4, base_delay=1.0, max_delay=20.0, operation_name="bigquery_stream")
    def _stream(self, table_id: str, payload: List[Dict[str, Any]]) -> None:
        errors = self.client.insert_rows_json(self.table_ref(table_id), payload)
        if errors:
            raise RuntimeError(f"BigQuery streaming insert reported errors: {errors}")
