"""Regression checks for shared dependency staging and deployment preflight."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]
FUNCTIONS = ("batch_predict", "fetch_gee_metrics", "process_citizen_image", "send_authority_alerts")
MODES = ("gateway", "prediction", "functions", "frontend", "terraform")
REQUIRED = (
    "GCP_PROJECT_ID",
    "GCP_WORKLOAD_IDENTITY_PROVIDER",
    "GCP_DEPLOYER_SERVICE_ACCOUNT",
    "GCP_TERRAFORM_SERVICE_ACCOUNT",
    "ARTIFACT_REGISTRY",
    "ML_ARTIFACTS_BUCKET",
    "CITIZEN_IMAGES_BUCKET",
    "ALERT_AUDIO_BUCKET",
    "PREDICTION_SERVICE_URL",
    "TF_STATE_BUCKET",
    "ADMIN_DOMAIN",
)


def requirements(path: Path) -> dict[str, Requirement]:
    return {
        req.name: req
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
        for req in [Requirement(line)]
    }


def test_common_requirements_are_exact_pins() -> None:
    common = requirements(ROOT / "functions/common/requirements.txt")
    for req in common.values():
        specs = list(req.specifier)
        assert len(specs) == 1 and specs[0].operator == "=="
        assert "*" not in specs[0].version
    assert str(common["protobuf"].specifier) == "==4.25.3"
    assert str(common["grpcio-status"].specifier) == "==1.62.3"
    assert {"google-events", "google-cloud-translate", "google-cloud-texttospeech"} <= common.keys()


@pytest.mark.parametrize("function", FUNCTIONS)
def test_function_requirements_have_no_shared_duplicates(function: str) -> None:
    common = requirements(ROOT / "functions/common/requirements.txt")
    specific = requirements(ROOT / f"functions/{function}/requirements.txt")
    assert not common.keys() & specific.keys()
    assert not any(name.startswith("google-cloud-") for name in specific)
    assert str(specific["functions-framework"].specifier) == "==3.8.1"


def test_prediction_requirements_have_no_shared_duplicates() -> None:
    common = requirements(ROOT / "functions/common/requirements.txt")
    specific = requirements(ROOT / "services/prediction-service/requirements.txt")
    assert not common.keys() & specific.keys()


def test_staging_vendors_all_common_pins(tmp_path: Path) -> None:
    # Exercise the real staging script in an isolated tree, not the working copy.
    shutil.copytree(ROOT / "functions", tmp_path / "functions", ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/stage_functions.sh", tmp_path / "scripts")
    subprocess.run(["bash", str(tmp_path / "scripts/stage_functions.sh"), "--all"], check=True)
    common = requirements(ROOT / "functions/common/requirements.txt")
    for function in FUNCTIONS:
        staged = tmp_path / "build/functions" / function
        merged = requirements(staged / "requirements.txt")
        for name, req in common.items():
            assert merged[name] == req
        assert (staged / "vayusetu_common/firestore_events.py").is_file()
        assert not (staged / "tests").exists()
        assert not (staged / "conftest.py").exists()


def test_real_eventarc_and_alert_sdk_imports() -> None:
    # Unit tests often mock these SDKs; exercise the actual pinned distributions.
    subprocess.run(
        [
            os.sys.executable,
            "-c",
            "from google.cloud import bigquery, firestore, storage, translate_v2, texttospeech; "
            "from google.events.cloud.firestore_v1.types.data import DocumentEventData; "
            "event = DocumentEventData(); "
            "assert DocumentEventData.deserialize(DocumentEventData.serialize(event)) == event",
        ],
        check=True,
    )


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("missing_provider", [False, True])
def test_deployment_preflight(mode: str, missing_provider: bool) -> None:
    env = dict(os.environ, **dict.fromkeys(REQUIRED, "configured-value-not-to-be-logged"))
    if missing_provider:
        env["GCP_WORKLOAD_IDENTITY_PROVIDER"] = "  "
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/check_deploy_config.sh"), mode],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == (1 if missing_provider else 0)
    assert "configured-value-not-to-be-logged" not in result.stdout + result.stderr
    if missing_provider:
        assert "GCP_WORKLOAD_IDENTITY_PROVIDER" in result.stdout
        assert "docs/BUILD_AND_DEPLOY.md" in result.stdout
