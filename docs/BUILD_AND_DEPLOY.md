# Python builds and deployment recovery

## Scope and diagnosis

This checkout has **no `backend/` directory**. The requested paths map to:

| Component | Requirements | Dockerfile / build context |
| --- | --- | --- |
| Shared SDKs | `functions/common/requirements.txt` | Included by both Python Dockerfiles |
| `fn-process-image` | `functions/process_citizen_image/requirements.txt` | `functions/Dockerfile`, repository root |
| `fn-fetch-gee` | `functions/fetch_gee_metrics/requirements.txt` | Same |
| `fn-batch` | `functions/batch_predict/requirements.txt` | Same |
| `fn-alerts` | `functions/send_authority_alerts/requirements.txt` | Same |
| `prediction-service` | `services/prediction-service/requirements.txt` | `services/prediction-service/Dockerfile`, repository root |

There are two separate issues:

1. **Python resolution:** loosely bounded SDKs and the image function's previous
   `protobuf>=5.26,<6` constraint allowed incompatible selections. The shared SDK
   versions are now exact pins, including the requested protobuf 4.25.3 stack.
2. **GitHub deployments:** the annotations for all eight failed deployment checks
   on commit `de376da5d6e03aa090962016079d83daba955304` report:

   > google-github-actions/auth failed with: the GitHub Action workflow must
   > specify exactly one of "workload_identity_provider" or "credentials_json"!

   These jobs failed **before building/deploying**. They use WIF, not JSON keys,
   so `vars.GCP_WORKLOAD_IDENTITY_PROVIDER` was empty at runtime. Package pins
   cannot fix an unconfigured identity provider. The successful tests did not
   exercise cloud authentication. The old successful deployment summary also did
   not mean deployments succeeded.

Evidence: [backend run](https://github.com/samudragupto/VayuSetu/actions/runs/35568984949),
[frontend run](https://github.com/samudragupto/VayuSetu/actions/runs/35568984951),
[Terraform run](https://github.com/samudragupto/VayuSetu/actions/runs/35568984953).
Annotations were available via the GitHub API; downloading full log archives
failed in the sandbox. Repository-variable inspection was denied by the GitHub
integration (HTTP 403), so no variable values were inspected or changed.

## Dependency and Docker policy

`functions/common/requirements.txt` is both the shared installation manifest
(`-r`) and the constraint set for subsequent installs (`-c`).

- The nine requested SDK/transport pins are preserved exactly.
- `google-events==0.14.0` is retained for real Eventarc protobuf decoding.
- `google-cloud-translate==3.15.3` and `google-cloud-texttospeech==2.16.3`
  moved to common requirements; deleting them would break production alerts.
- `grpcio-status==1.62.3` is deliberate: 1.64.x requires protobuf 5 and is not
  compatible with the requested protobuf 4 pin. Its version need not match grpcio.
- Shared Google client dependencies are pinned too, limiting resolver backtracking.
- Each function pins `functions-framework==3.8.1`. Vision pins
  `google-generativeai==0.7.2`; Earth Engine pins `earthengine-api==0.1.410`.
- `requirements-dev.txt` includes the common manifest; CI uses the same constraints
  and runs `pip check`. Production function staging already merges the common
  manifest into the uploaded `requirements.txt` and is covered by regression tests.
- Both Dockerfiles install build-essential, ensure `setuptools`/`wheel`, prefer
  wheels, install common requirements first, and constrain the later installation.
  The prediction image retains `libgomp1` for XGBoost at runtime.
- Neither Python Dockerfile runs `pip install --upgrade pip`. Upgrading pip inside a
  build layer pulls an unpinned tool and forces a second full resolution pass, which
  is how one bad line in a requirements file becomes a long, confusing failure that
  looks like a network problem. The interpreter images ship a pip that resolves this
  stack correctly.
- There is no final loose `functions-framework>=3.8,<4` install. The exact pin
  is already installed; the FastAPI prediction service does not need the framework.
- Function-specific build arguments are declared after the shared layers, so all
  four functions can reuse them. The root `.dockerignore` excludes credentials and
  large development caches without excluding CI's trained model.

These are compatibility pins requested for the Python 3.10 stack, **not a complete
transitive lockfile or a security certification**. Non-Google application libraries
still retain their existing ranges. Before production use, scan the built images
and plan coordinated SDK/security upgrades rather than upgrading protobuf or an
individual Google SDK independently. Wheel preference does not guarantee wheels
on every architecture; the verified target was Linux x86_64.

## Clean rebuild from the repository root

Prerequisites: Docker Engine/Desktop running, Docker Compose v2, enough disk space
for ML wheels/images. Copy `.env.example` only if `.env` does not already exist.
These commands stop this Compose stack. **Builder cache pruning affects other
projects using the same builder**, but does not delete application volumes.

```bash
cd /path/to/VayuSetu
[ -f .env ] || cp .env.example .env
docker compose config --quiet

docker compose down --remove-orphans
# Remove unused build cache; confirm the shared-cache impact before running.
docker builder prune --all --force
# If using a separate Buildx builder, also clear that builder's cache:
docker buildx prune --all --force

# Refresh base images and bypass all cached layers for the entire stack.
docker compose --progress plain build --pull --no-cache
docker compose up -d --force-recreate
docker compose ps
docker compose logs --tail=100 fn-process-image fn-fetch-gee fn-batch fn-alerts prediction-service
```

Do **not** add `down --volumes` or `system prune --volumes` unless intentionally
resetting local data. To rebuild only the affected Python images instead:

```bash
docker compose --progress plain build --pull --no-cache \
  fn-process-image fn-fetch-gee fn-batch fn-alerts prediction-service
docker compose up -d --force-recreate
```

Verify installed metadata in each image without starting Firebase or calling GCP:

```bash
for service in fn-process-image fn-fetch-gee fn-batch fn-alerts prediction-service; do
  docker compose run --rm --no-deps --entrypoint python "$service" -m pip check
done
curl --fail http://localhost:8090/healthz
curl --fail http://localhost:8081/healthz
```

Function endpoints consume POST/CloudEvent payloads; a browser GET returning 400 or
405 is not a dependency failure. Follow the local simulation commands in README.

## Base images and build-network troubleshooting

Build failures in this stack are usually the build container's network, not the
Dockerfiles. Two signatures seen on a Windows/Docker Desktop checkout:

```
WARNING: fetching https://dl-cdn.alpinelinux.org/alpine/v3.23/main/x86_64/APKINDEX.tar.gz: DNS: transient error (try again later)
ERROR: unable to select packages:
  tini (no such package):
    required by: world[tini]
```

```
WARNING: fetching .../v3.23/community/x86_64/APKINDEX.tar.gz: v2 database format error
```

Both mean the same thing: `apk` could not load a package index, so it reported the
requested package as nonexistent. Alpine 3.21+ publishes APKINDEX in the new v2
format, which older `apk-tools` in Docker Desktop's VM cannot always parse, and a
registry mirror or flaky resolver turns the rest into `DNS: transient error`.

Fixes, in order of preference:

1. Update Docker Desktop (Settings → General → *Check for updates*). Newer builds
   ship an `apk-tools` that reads the v2 index, and any `node:20-alpine` image
   cached from an older pull should be refreshed with `docker compose build --pull`.
2. Give containers a resolver that works off the corporate/VPN network:
   Docker Desktop → Settings → Resources → Network → *DNS server* → `1.1.1.1, 8.8.8.8`.
   The same value in the Docker Engine JSON tab is `{"dns": ["1.1.1.1", "8.8.8.8"]}`.
3. If a registry mirror is configured for Docker Hub, remove it (or add
   `https://index.docker.io/1.1/` as a fallback) in Docker Engine settings; broken
   mirrors cause the slow layer downloads that turn into DNS timeouts.
4. If a proxy is set on the Docker Desktop *Resources → Proxies* page, the build
   container uses it for every CDN. A proxy that cannot reach
   `dl-cdn.alpinelinux.org` or `deb.debian.org` fails exactly like the above.

**The repository no longer depends on runtime package installs in the API gateway
image**: the gateway moved from `node:20-alpine` to `node:20-bookworm-slim` and the
`apk add tini` layer was dropped, so a rebuild of `api-gateway` now only needs the
base image and `npm`. The Debian base is also the one the local Firebase emulator
image already downloads, so the two builds share the layer cache. Signal handling is
unchanged: `docker compose` delivers `SIGTERM`/`SIGINT` straight to the Node process,
which installs handlers for both, and Cloud Run's sandbox reaps orphans itself.

A third failure mode, `No matching distribution found for <package>`, is not network
related: it means a requirements file lists a package that does not exist on PyPI.
`functions/common/requirements.txt` is vendored into every function image and into
`requirements-dev.txt`, so a stray local edit there breaks all four function builds
at once. Recover with a clean copy and verify:

```bash
git checkout -- functions/common/requirements.txt
# every pin below must exist on PyPI, e.g.:
python -c "import json,urllib.request as u; d=json.load(u.urlopen('https://pypi.org/pypi/protobuf/json')); print('4.25.3' in d['releases'])"
```

After changing `functions/common/requirements.txt`, rebuild every Python image -
the common layer is shared, so a partially cached stack mixes old and new SDKs and
`pip check` in the image is what surfaces it.

## Unblock all eight cloud deployments

### 1. Bootstrap outside GitHub Actions

The Terraform configuration creates its own GitHub WIF provider and service
accounts. The first apply therefore must use an existing authorized human/cloud
administrator identity, not the as-yet-uncreated GitHub identity. This provisions
billable resources; review the plan and organization permissions first.

Use Google Cloud CLI, Terraform 1.9.8, and a current GitHub CLI locally. Replace
all placeholders below. Do not paste credentials into chat or commit them.

```bash
export PROJECT_ID='your-real-gcp-project'
export REGION='us-central1'
export TF_STATE_BUCKET="${PROJECT_ID}-vayusetu-tfstate"
export GH_REPO='samudragupto/VayuSetu'

gcloud auth login
gcloud auth application-default login
gcloud config set project "$PROJECT_ID"
gcloud auth application-default set-quota-project "$PROJECT_ID"

# Only if not already created; billing must be linked to the project.
gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com \
  iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com storage.googleapis.com
# Only if the state bucket does not already exist:
gcloud storage buckets create "gs://${TF_STATE_BUCKET}" \
  --project "$PROJECT_ID" --location "$REGION" \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update "gs://${TF_STATE_BUCKET}" --versioning

cd infrastructure/terraform
cp -n terraform.tfvars.example terraform.tfvars
cp -n backend.hcl.example backend.hcl
# Edit terraform.tfvars: real project, repository, region/locations, admin domain,
# environment and application secret values. Prefer TF_VAR_* for secrets.
# Edit backend.hcl: bucket=<TF_STATE_BUCKET>, prefix="vayusetu/dev".
# The prefix/environment must match the workflow. Never commit these files.
terraform init -backend-config=backend.hcl
terraform fmt -check -recursive
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
```

If infrastructure already exists, use its existing remote state and matching
configuration. Do not apply a fresh state over existing resources or create a
second provider blindly. The bootstrap identity needs permission to create the
resources and grant the IAM bindings declared in `iam.tf`. Register the project
with Earth Engine, enable/configure Firebase and Hosting, and create the Firebase
web app as described in README. A dependency fix does not perform these steps.

### 2. Populate GitHub **Actions variables**, not secrets, for WIF

The workflows read `vars.*`, so adding similarly named GitHub secrets will not
satisfy them. Repository variables are recommended because non-deployment build
jobs also need public frontend configuration. Jobs use the GitHub Environment
named by repository `ENVIRONMENT` (default `dev`); check for stale overrides there
and configure approval/branch protection for that environment.

From `infrastructure/terraform`, after the initial apply:

```bash
# Requires repository Variables write permission in your GitHub connection.
# Outputs here are non-secret configuration, not Terraform's sensitive outputs.
terraform output -json github_repository_variables | \
  jq -r 'to_entries[] | [.key, (.value | tostring)] | @tsv' | \
  while IFS=$'\t' read -r name value; do
    gh variable set "$name" --repo "$GH_REPO" --body "$value"
  done
gh variable set TF_STATE_BUCKET --repo "$GH_REPO" --body "$TF_STATE_BUCKET"
gh variable list --repo "$GH_REPO"
cd ../..
```

The output now includes `API_GATEWAY_URL`, `ENVIRONMENT`, and both database
locations, in addition to the provider, service accounts, buckets and registry.
`TF_STATE_BUCKET` remains explicit because the remote backend is bootstrapped
separately. Keep the state prefix (`vayusetu/<environment>`) consistent.

Required configuration by deployment:

| Job | Required Actions variables |
| --- | --- |
| All | `GCP_PROJECT_ID`, `GCP_WORKLOAD_IDENTITY_PROVIDER` |
| API gateway | `GCP_DEPLOYER_SERVICE_ACCOUNT`, `ARTIFACT_REGISTRY` |
| Prediction | Same plus `ML_ARTIFACTS_BUCKET` |
| Four functions | `GCP_DEPLOYER_SERVICE_ACCOUNT`, `CITIZEN_IMAGES_BUCKET`, `ALERT_AUDIO_BUCKET`, `PREDICTION_SERVICE_URL` |
| Firebase Hosting | `GCP_DEPLOYER_SERVICE_ACCOUNT`; Firebase/Hosting must exist |
| Terraform | `GCP_TERRAFORM_SERVICE_ACCOUNT`, `TF_STATE_BUCKET`, `ADMIN_DOMAIN` |

The provider must be the full resource name:
`projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/POOL/providers/PROVIDER`.
Service account variables must be email addresses. Use the Terraform outputs, not
guessed project IDs/numbers. `ARTIFACT_REGISTRY` is a repository path such as
`us-central1-docker.pkg.dev/PROJECT/REPOSITORY`, without `https://`.

Also set the public frontend values from your Firebase web app and Google Maps
configuration: `NEXT_PUBLIC_FIREBASE_API_KEY`, `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`,
`NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET`, `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID`,
`NEXT_PUBLIC_FIREBASE_APP_ID`, `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`,
`NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID`. These are bundled at build time; configure API-key
restrictions and authorized domains. See README for the full optional variable list.

Set Terraform's application **secrets** using secure GitHub CLI prompts or the
repository Settings UI (do not put secret values on the command line):

```bash
for name in TWILIO_ACCOUNT_SID TWILIO_AUTH_TOKEN TWILIO_WHATSAPP_FROM \
  TWILIO_VOICE_FROM GOOGLE_AI_STUDIO_API_KEY PHONE_HASH_SECRET; do
  gh secret set "$name" --repo "$GH_REPO"
done
```

Keep values consistent with the bootstrap configuration. The Terraform identity
needs access to the remote-state bucket, and the WIF repository claim must match
`samudragupto/VayuSetu` exactly. `wif.tf` grants `roles/iam.workloadIdentityUser` on
both pipeline accounts. For subsequent 403 errors, inspect the actual missing
permission instead of introducing service-account JSON keys or broad owner grants.

### 3. Validate and deploy in order

Merge the reviewed changes through a PR from `arena/01a0c36e-vayusetu` into `main`.
No cloud deployment was dispatched from this sandbox. Push workflows may start on
merge, so configure WIF first. For initial rollout, finish infrastructure before
manually dispatching backend and frontend. An old run re-run uses the old workflow
revision; dispatch a new run on updated `main` to exercise the fixes.

```bash
# Inspect a plan first; review the Actions result before applying.
gh workflow run terraform.yml --ref main -f action=plan
gh run list --workflow terraform.yml --limit 5
# Then, only after reviewing the plan:
gh workflow run terraform.yml --ref main -f action=apply
# Wait for infrastructure success before proceeding:
gh workflow run backend-deploy.yml --ref main -f deploy=true
# Wait for backend health checks and verify API_GATEWAY_URL, then:
gh workflow run frontend-deploy.yml --ref main

gh run list --limit 10
# For any failing run, substitute its numeric ID:
# gh run view RUN_ID --log-failed
```

All deployment jobs now fail early with the missing **variable names** and this
runbook link; they do not skip authentication or mark absent configuration green.
The backend summary fails if a deployment fails/cancels. The function deploy command
uses gcloud's `^|^` dictionary delimiter so the comma-separated Gemini model list
is passed as one value. Do not include `|` in those environment values.

## Reproduce Python validation without Docker

Use Python 3.10 in a clean environment:

```bash
python3.10 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install --prefer-binary -c functions/common/requirements.txt \
  -r requirements-dev.txt -r ml/requirements.txt \
  -r functions/process_citizen_image/requirements.txt \
  -r functions/fetch_gee_metrics/requirements.txt \
  -r functions/batch_predict/requirements.txt \
  -r functions/send_authority_alerts/requirements.txt \
  -r services/prediction-service/requirements.txt
python -m pip check
ruff check functions services/prediction-service ml scripts/tests
pytest scripts/tests -q
# Match CI: separate processes prevent collisions between functions' main modules.
for component in functions/common functions/process_citizen_image \
  functions/fetch_gee_metrics functions/send_authority_alerts \
  functions/batch_predict services/prediction-service ml; do
  pytest "$component" -q || exit 1
done
bash scripts/stage_functions.sh --all
```

For a resolution-only check targeting Python 3.10 from another Python version:

```bash
python -m pip install --dry-run --ignore-installed --python-version 3.10 \
  --only-binary=:all: \
  -r functions/common/requirements.txt \
  -r functions/process_citizen_image/requirements.txt \
  -r functions/fetch_gee_metrics/requirements.txt \
  -r functions/batch_predict/requirements.txt \
  -r functions/send_authority_alerts/requirements.txt \
  -r services/prediction-service/requirements.txt -r ml/requirements.txt
```

## Verification performed for this change

- Linux x86_64, Python 3.10-targeted resolution of all runtime manifests together,
  with binary distributions only: passed. Each of the four staged Cloud Function
  deployment manifests also passed independent Python 3.10-targeted resolution.
- Actual installation on the sandbox's Python 3.11 and `pip check`: passed.
- Existing tests in CI-style component isolation: **87 passed**.
- New staging/pinning/real-SDK/preflight regression tests: **18 passed**.
- Real Gemini 0.7.2 response-schema construction and Earth Engine/Google client
  imports: passed without network calls to cloud APIs.
- Ruff, workflow YAML parsing, workflow run-step shell syntax, and `git diff --check`: passed.
- A single all-components `pytest` invocation exposes pre-existing `main` module
  import collisions; use the component-isolated commands above, as CI does.
- Docker Engine and Terraform are unavailable in the sandbox. Container builds,
  Terraform validation/apply and live deployments were **not executed**. Downloading
  a Python 3.10 interpreter was blocked by the sandbox's GitHub download connection;
  runtime tests here therefore used Python 3.11, not Python 3.10.

The eight remote deployment failures will remain on their old runs until the
configuration is supplied and new runs succeed. No remote check status is claimed
fixed by local tests alone.
