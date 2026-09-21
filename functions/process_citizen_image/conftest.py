"""Pytest configuration for this Cloud Function.

Every function ships a module named ``main`` (the Cloud Functions convention),
so the function directory is moved to the front of ``sys.path`` and any
previously imported sibling modules are evicted. This allows ``pytest`` to run
from the repository root across all functions as well as per directory in CI.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_COMMON = os.path.join(os.path.dirname(_HERE), "common")
_LOCAL_MODULES = {"main", "gemini_client", "prompts", "gee_client", "alerting", "messaging", "translation", "pipeline", "weather", "data_sources", "prediction_client"}

for _path in (_COMMON, _HERE):
    if _path in sys.path:
        sys.path.remove(_path)
    sys.path.insert(0, _path)

for _name in list(sys.modules):
    if _name in _LOCAL_MODULES:
        del sys.modules[_name]

os.environ.setdefault("GCP_PROJECT_ID", "vayusetu-test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test-key")
os.environ.setdefault("BIGQUERY_ENABLED", "false")
