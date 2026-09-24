"""Regression checks for shared dependency staging, deployment preflight and workflow wiring."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
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
PLACEHOLDER = "configured-value-not-to-be-logged"


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


# ---------------------------------------------------------------------------
# check_deploy_config.sh - the strict gate that runs inside a deployment job
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("missing_provider", [False, True])
def test_deployment_preflight(mode: str, missing_provider: bool) -> None:
    env = dict(os.environ, **dict.fromkeys(REQUIRED, PLACEHOLDER))
    if missing_provider:
        env["GCP_WORKLOAD_IDENTITY_PROVIDER"] = "  "
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/check_deploy_config.sh"), mode],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == (1 if missing_provider else 0)
    assert PLACEHOLDER not in result.stdout + result.stderr
    if missing_provider:
        assert "GCP_WORKLOAD_IDENTITY_PROVIDER" in result.stdout
        assert "docs/BUILD_AND_DEPLOY.md" in result.stdout


# ---------------------------------------------------------------------------
# deployment_preflight.sh - decides whether a deployment job runs at all
#
# It must never turn missing configuration into a failure: a skipped check is the
# required behaviour for a fork or for a repository that has not been bootstrapped
# with Terraform yet, and a red check there hides real deployment errors.
# ---------------------------------------------------------------------------


def run_preflight(
    *modes: str,
    env_overrides: dict[str, str | None] | None = None,
    tmp_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    # Start from an environment in which every known variable is unset, so the
    # result never depends on the developer's shell.
    env = {key: value for key, value in os.environ.items() if key not in REQUIRED}
    env.update(dict.fromkeys(REQUIRED, PLACEHOLDER))
    for key, value in (env_overrides or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    if tmp_path is not None:
        env["GITHUB_OUTPUT"] = str(tmp_path / "github_output")
        env["GITHUB_STEP_SUMMARY"] = str(tmp_path / "github_summary")
        (tmp_path / "github_output").write_text("")
        (tmp_path / "github_summary").write_text("")
    else:
        env.pop("GITHUB_OUTPUT", None)
        env.pop("GITHUB_STEP_SUMMARY", None)
    return subprocess.run(
        ["bash", str(ROOT / "scripts/deployment_preflight.sh"), *modes],
        env=env,
        capture_output=True,
        text=True,
    )


def outputs_from(tmp_path: Path, result: subprocess.CompletedProcess[str]) -> dict[str, str]:
    assert result.returncode == 0, result.stderr
    return dict(
        line.split("=", 1) for line in (tmp_path / "github_output").read_text().splitlines() if "=" in line
    )


@pytest.mark.parametrize("mode", MODES)
def test_preflight_reports_configured_target(mode: str, tmp_path: Path) -> None:
    result = run_preflight(mode, tmp_path=tmp_path)
    outputs = outputs_from(tmp_path, result)
    assert outputs[f"{mode}_configured"] == "true"
    assert outputs[f"{mode}_missing"] == ""
    assert outputs["any_configured"] == "true"
    assert "::notice::" in result.stdout


@pytest.mark.parametrize("mode", MODES)
def test_preflight_skips_rather_than_fails_when_unconfigured(mode: str, tmp_path: Path) -> None:
    result = run_preflight(mode, env_overrides=dict.fromkeys(REQUIRED, None), tmp_path=tmp_path)
    # Exit 0 is the whole point: the job that consumes this output is skipped, so
    # the check stays neutral instead of going red.
    assert result.returncode == 0, result.stderr
    outputs = outputs_from(tmp_path, result)
    assert outputs[f"{mode}_configured"] == "false"
    missing = outputs[f"{mode}_missing"].split(",")
    assert "GCP_PROJECT_ID" in missing
    assert "GCP_WORKLOAD_IDENTITY_PROVIDER" in missing
    # Names are reported; values never are.
    assert PLACEHOLDER not in result.stdout + result.stderr
    assert "::warning::" in result.stdout
    assert "docs/BUILD_AND_DEPLOY.md" in result.stdout


def test_preflight_handles_targets_independently(tmp_path: Path) -> None:
    result = run_preflight(
        "gateway",
        "prediction",
        "functions",
        env_overrides={"ML_ARTIFACTS_BUCKET": None, "ALERT_AUDIO_BUCKET": None},
        tmp_path=tmp_path,
    )
    outputs = outputs_from(tmp_path, result)
    # Only the targets that need the unset variables are held back.
    assert outputs["gateway_configured"] == "true"
    assert outputs["prediction_configured"] == "false"
    assert outputs["prediction_missing"] == "ML_ARTIFACTS_BUCKET"
    assert outputs["functions_configured"] == "false"
    assert outputs["functions_missing"] == "ALERT_AUDIO_BUCKET"
    assert outputs["any_configured"] == "true"


def test_preflight_treats_whitespace_as_unset(tmp_path: Path) -> None:
    result = run_preflight("gateway", env_overrides={"GCP_PROJECT_ID": "   "}, tmp_path=tmp_path)
    outputs = outputs_from(tmp_path, result)
    assert outputs["gateway_configured"] == "false"
    assert outputs["gateway_missing"] == "GCP_PROJECT_ID"


def test_preflight_writes_a_step_summary(tmp_path: Path) -> None:
    run_preflight("frontend", env_overrides={"GCP_PROJECT_ID": None}, tmp_path=tmp_path)
    summary = (tmp_path / "github_summary").read_text()
    assert "Deployment preflight" in summary
    assert "`frontend`" in summary
    assert "`GCP_PROJECT_ID`" in summary
    assert "skipped, not failed" in summary
    assert PLACEHOLDER not in summary


def test_preflight_works_without_a_runner_environment() -> None:
    # Locally there is no GITHUB_OUTPUT or GITHUB_STEP_SUMMARY; the script must
    # still exit 0 and explain itself on stdout.
    result = run_preflight("gateway", "terraform")
    assert result.returncode == 0
    assert "ready" in result.stdout


def test_preflight_rejects_unknown_target() -> None:
    result = run_preflight("deploy")
    assert result.returncode == 2
    assert "Usage: deployment_preflight.sh" in result.stderr


def test_preflight_requires_at_least_one_target() -> None:
    result = run_preflight()
    assert result.returncode == 2
    assert "Usage: deployment_preflight.sh" in result.stderr


# ---------------------------------------------------------------------------
# Workflow wiring
#
# The skip behaviour lives in the workflow YAML, so assert on the YAML rather
# than trusting that a future edit keeps the gate in place.
# ---------------------------------------------------------------------------

WORKFLOWS = ("backend-deploy.yml", "frontend-deploy.yml", "terraform.yml")
PREFLIGHT_JOB = "deployment-preflight"

# (workflow, preflight output key, gated job, strict check mode)
GATED_JOBS = (
    ("backend-deploy.yml", "gateway", "deploy-gateway", "gateway"),
    ("backend-deploy.yml", "prediction", "deploy-prediction-service", "prediction"),
    ("backend-deploy.yml", "functions", "deploy-functions", "functions"),
    ("frontend-deploy.yml", "frontend", "deploy", "frontend"),
    ("terraform.yml", "terraform", "terraform", "terraform"),
)


def workflow(name: str) -> dict:
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text())


def needs_of(job: dict) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


@pytest.mark.parametrize("workflow_name", WORKFLOWS)
def test_workflows_define_a_preflight_job(workflow_name: str) -> None:
    jobs = workflow(workflow_name)["jobs"]
    assert PREFLIGHT_JOB in jobs
    runs = [str(step.get("run", "")) for step in jobs[PREFLIGHT_JOB]["steps"]]
    assert any("deployment_preflight.sh" in run for run in runs)


@pytest.mark.parametrize(("workflow_name", "key", "gated", "mode"), GATED_JOBS)
def test_deployments_are_gated_by_the_preflight(workflow_name: str, key: str, gated: str, mode: str) -> None:
    jobs = workflow(workflow_name)["jobs"]
    preflight = jobs[PREFLIGHT_JOB]
    job = jobs[gated]

    assert PREFLIGHT_JOB in needs_of(job)
    assert f"needs.{PREFLIGHT_JOB}.outputs.{key}" in job["if"]

    # The preflight must publish the output the deployment reads ...
    expression = preflight["outputs"][key]
    match = re.fullmatch(r"\$\{\{\s*steps\.([A-Za-z0-9_-]+)\.outputs\.([A-Za-z0-9_-]+)\s*\}\}", expression)
    assert match, f"{workflow_name}:{key} publishes {expression!r}"
    assert match.group(2) == f"{key}_configured"

    # ... from a step that runs the preflight script for that target.
    script_steps = [
        step for step in preflight["steps"] if "deployment_preflight.sh" in str(step.get("run", ""))
    ]
    matching = [step for step in script_steps if step.get("id") == match.group(1)]
    assert matching, f"no preflight step with id {match.group(1)} in {workflow_name}"
    assert mode in matching[0]["run"].split()


@pytest.mark.parametrize(("workflow_name", "key", "gated", "mode"), GATED_JOBS)
def test_gated_jobs_keep_the_strict_configuration_check(
    workflow_name: str, key: str, gated: str, mode: str
) -> None:
    # Defence in depth: the deployment job still validates its own variables, so a
    # wrongly wired preflight cannot deploy into a half-configured project.
    job = workflow(workflow_name)["jobs"][gated]
    runs = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "check_deploy_config.sh" in runs
    assert mode in runs


def test_deployment_summary_ignores_skips_but_still_fails_on_errors() -> None:
    summary = workflow("backend-deploy.yml")["jobs"]["deployment-summary"]
    failing = [step for step in summary["steps"] if "exit 1" in str(step.get("run", ""))]
    assert failing, "the summary must still fail a workflow whose deployment failed"
    for step in failing:
        condition = str(step.get("if", ""))
        assert "failure" in condition
        assert "skipped" not in condition


def test_deployment_summary_reports_skipped_targets() -> None:
    summary = workflow("backend-deploy.yml")["jobs"]["deployment-summary"]
    assert PREFLIGHT_JOB in needs_of(summary)
    body = "\n".join(str(step.get("run", "")) for step in summary["steps"])
    # A skipped deployment must be explained rather than silently green.
    assert "skipped" in body
    assert "docs/BUILD_AND_DEPLOY.md" in body


@pytest.mark.parametrize("workflow_name", WORKFLOWS)
def test_workflow_run_blocks_are_valid_shell(workflow_name: str, tmp_path: Path) -> None:
    script = tmp_path / "step.sh"
    for job_id, job in workflow(workflow_name)["jobs"].items():
        for index, step in enumerate(job["steps"]):
            run = step.get("run")
            if not isinstance(run, str):
                continue
            script.write_text(run)
            result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
            assert result.returncode == 0, f"{workflow_name}:{job_id} step {index}: {result.stderr}"
