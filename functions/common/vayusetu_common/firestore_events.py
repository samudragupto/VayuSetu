"""Helpers for decoding Firestore CloudEvents delivered by Eventarc.

Production Firestore triggers deliver a protobuf-encoded
``google.events.cloud.firestore.v1.DocumentEventData`` payload. The local event
bridge (local/event-bridge) delivers a JSON payload instead. Rather than parsing
document fields out of the event, the functions extract only the document path
and re-read the document through the Firestore client. This keeps the decoding
logic tiny and guarantees the function always operates on the latest state.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

_DOCUMENT_PATH_RE = re.compile(r"projects/[^/]+/databases/[^/]+/documents/(?P<path>.+)$")


def _relative_path(full_name: str) -> str:
    match = _DOCUMENT_PATH_RE.match(full_name)
    if match:
        return match.group("path")
    return full_name


def _from_protobuf(data: bytes) -> Optional[str]:
    try:
        from google.events.cloud import firestore as firestoredata  # type: ignore
    except ImportError:  # pragma: no cover - dependency present in deployed functions
        logger.warning("google-events is not installed; cannot decode protobuf Firestore event")
        return None
    payload = firestoredata.DocumentEventData()
    payload._pb.ParseFromString(data)  # noqa: SLF001 - documented usage
    document = payload.value if payload.value and payload.value.name else payload.old_value
    if document is None or not document.name:
        return None
    return _relative_path(document.name)


def _from_mapping(data: Mapping[str, Any]) -> Optional[str]:
    for key in ("value", "oldValue", "old_value"):
        section = data.get(key)
        if isinstance(section, Mapping) and section.get("name"):
            return _relative_path(str(section["name"]))
    if data.get("name"):
        return _relative_path(str(data["name"]))
    if data.get("document"):
        return _relative_path(str(data["document"]))
    return None


def extract_document_path(cloud_event: Any) -> str:
    """Return the collection/document path referenced by a Firestore CloudEvent.

    Resolution order:
      1. the ``document`` CloudEvent extension attribute set by Eventarc;
      2. a protobuf ``DocumentEventData`` payload;
      3. a JSON payload produced by the local event bridge.
    """
    attribute = None
    try:
        attribute = cloud_event["document"]
    except (KeyError, TypeError, AttributeError):
        attribute = getattr(cloud_event, "document", None)
    if attribute:
        return _relative_path(str(attribute))

    data = getattr(cloud_event, "data", None)
    if isinstance(data, (bytes, bytearray)):
        path = _from_protobuf(bytes(data))
        if path:
            return path
    elif isinstance(data, Mapping):
        path = _from_mapping(data)
        if path:
            return path

    raise ValueError("Unable to determine Firestore document path from CloudEvent")


def document_id_from_path(path: str) -> str:
    """Return the final path segment (document ID)."""
    return path.rstrip("/").split("/")[-1]
