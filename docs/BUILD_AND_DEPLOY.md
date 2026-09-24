# Build and deployment runbook

Everything needed to build VayuSetu locally, understand what CI runs, and get the
Google Cloud deployments green for the first time. Read
[Deployment configuration](#deployment-configuration-and-workflow-behaviour) first if
your GitHub checks are red or skipped.

## Contents

1. [Build map](#build-map)
2. [Deployment configuration and workflow behaviour](#deployment-configuration-and-workflow-behaviour)
3. [Dependency and Docker policy](#dependency-and-docker-policy)
4. [Clean rebuild from the repository root](#clean-rebuild-from-the-repository-root)
5. [Base image and build-network troubleshooting](#base-image-and-build-network-troubleshooting)
6. [CRLF line endings](#crlf-line-endings)
7. [Bootstrapping the cloud deployments](#bootstrapping-the-cloud-deployments)
8. [Reproducing CI validation without Docker](#reproducing-ci-validation-without-docker)

## Build map

There is no `backend/` directory: `backend-deploy.yml` is the workflow that builds and
deploys the backend components, and each one lives under `services/`, `functions/` or
`ml/`.

| Component | Requirements | Dockerfile / build context |
| --- | --- | --- |
| Shared SDKs | `functions/common/requirements.txt` | Included by both Python Dockerfiles |
| `process-citizen-image` | `functions/process_citizen_image/requirements.txt` | `functions/Dockerfile`, repository root |
| `fetch-gee-metrics` | `functions/fetch_gee_metrics/requirements.txt` | Same |
| `batch-predict` | `functions/batch_predict/requirements.txt` | Same |
| `send-authority-alerts` | `functions/send_authority_alerts/requirements.txt` | Same |
| `prediction-service` | `services/prediction-service/requirements.txt` | `services/prediction-service/Dockerfile`, repository root |
| `api-gateway` | `services/api-gateway/package-lock.json` | `services/api-gateway/Dockerfile`, that directory |

Deployment stages copy only the staged function directory, so the shared library has
to be vendored in first: `scripts/stage_functions.sh`, covered below.

## Deployment configuration and workflow behaviour

The workflows authenticate to Google Cloud with Workload Identity Federation and read
every value from GitHub Actions **variables** (`vars.*`). A similarly named repository
*secret* does not satisfy them.

Each workflow starts with a **deployment preflight** job
(`scripts/deployment_preflight.sh`) that answers one question per deployment target:
are all the variables it needs present?

| Outcome | What happens |
| --- | --- |
| All present | The deployment job runs. If it then fails, the check is red and the failure is real. |
| Any missing | The deployment job is **skipped**. The preflight prints the missing *names* (never values) as a warning annotation plus a run-summary table, and links here. |

The quality jobs - ESLint, type checks, Jest, Ruff and pytest - always run and carry
the real signal. Consequences worth stating plainly:

- A skipped deployment is **not** a deployment, and not a success. A green run on a
  repository without cloud configuration means "the code is fine and nothing was
  deployed", nothing more.
- Once the variables are configured, the very same commit deploys for real; re-run the
  workflow or push again.
- `scripts/check_deploy_config.sh` still runs inside each deployment job as a strict
  second gate, so a wrongly wired preflight cannot deploy into a half-configured
  project. It fails the job with the missing names if that ever happens.
- Only genuinely blocked *deployments* are skipped. A missing variable never hides a
  failing test.

Required variables per target - the preflight and the strict gate use the same table:

| Target | Required Actions variables |
| --- | --- |
| All | `GCP_PROJECT_ID`, `GCP_WORKLOAD_IDENTITY_PROVIDER` |
| API gateway | `GCP_DEPLOYER_SERVICE_ACCOUNT`, `ARTIFACT_REGISTRY` |
| Prediction service | The above plus `ML_ARTIFACTS_BUCKET` |
| Four functions | `GCP_DEPLOYER_SERVICE_ACCOUNT`, `CITIZEN_IMAGES_BUCKET`, `ALERT_AUDIO_BUCKET`, `PREDICTION_SERVICE_URL` |
| Firebase Hosting | `GCP_DEPLOYER_SERVICE_ACCOUNT` |
| Terraform | `GCP_TERRAFORM_SERVICE_ACCOUNT`, `TF_STATE_BUCKET`, `ADMIN_DOMAIN` |

Run the preflight locally at any time (`bash scripts/deployment_preflight.sh gateway
prediction functions`) to see the same table without touching GitHub.

## Dependency and Docker policy

`functions/common/requirements.txt` is both the shared installation manifest
(`-r`) and the constraint set for subsequent installs (`-c`).

- The runtime SDK/transport pins are exact, including the protobuf 4.25.3 stack.
- `google-events==0.14.0` is retained for real Eventarc protobuf decoding.
- `google-cloud-translate==3.15.3` and `google-cloud-texttospeech==2.16.3` live in
  common requirements; deleting them would break production alerts.
- `grpcio-status==1.62.3` is deliberate: 1.64.x requires protobuf 5 and is
  incompatible with the protobuf 4 pin. Its version need not match grpcio's.
- Shared Google client dependencies are pinned too, which limits resolver
  backtracking.
- Each function pins `functions-framework==3.8.1`. Vision pins
  `google-generativeai==0.7.2`; Earth Engine pins `earthengine-api==0.1.410`.
- `requirements-dev.txt` includes the common manifest and adds the test tooling,
  including `pyyaml`, which the workflow regression tests use. CI installs with
  `-c functions/common/requirements.txt`, then runs `pip check`.
- Production function staging merges the common manifest into the uploaded
  `requirements.txt`; regression tests cover that.
- Both Dockerfiles install build-essential, ensure `setuptools`/`wheel`, prefer
  wheels, install common requirements first and constrain the later installation.
  The prediction image keeps `libgomp1` for XGBoost at runtime.
- Neither Python Dockerfile runs `pip install --upgrade pip`. Doing so pulls an
  unpinned tool, forces a second full resolution pass, and turns one bad requirements
  line into a long failure that looks like a network problem. The interpreter images
  ship a pip that resolves this stack correctly.
- There is no final loose `functions-framework>=3.8,<4` install. The exact pin is
  already installed, and the FastAPI prediction service does not need the framework.
- Function-specific build arguments are declared after the shared layers so all four
  functions can reuse them. The root `.dockerignore` excludes credentials and large
  development caches without excluding CI's trained model.

These are compatibility pins for the Python 3.10 stack, **not a complete transitive
lockfile or a security certification**. Non-Google application libraries keep their
existing ranges. Before production use, scan the built images and plan coordinated
SDK and security upgrades rather than moving protobuf or a single Google SDK on its
own. Wheel preference does not guarantee wheels on every architecture; the verified
target is Linux x86_64.

## Clean rebuild from the repository root

Prerequisites: Docker Engine or Desktop running, Docker Compose v2, and enough disk
space for the ML wheels and images. Copy `.env.example` only if `.env` does not
already exist. These commands stop this Compose stack. **Builder cache pruning affects
other projects using the same builder** but does not delete application volumes.

```bash
cd /path/to/VayuSetu
[ -f .env ] || cp .env.example .env
docker compose config --quiet

docker compose down --remove-orphans
# WARNING: this deletes BuildKit's copy of the base-image layers, and BuildKit does
# not fall back to `docker pull` - every target re-downloads ~120 MB from
# production.cloudfront.docker.com afterwards. Skip it while the registry path is
# flaky; `--no-cache` alone rebuilds without losing the base layers.
docker builder prune --all --force   # only when you really need the disk space
# If using a separate Buildx builder, also clear that builder's cache:
docker buildx prune --all --force

# Refresh base images and bypass all cached layers for the entire stack.
docker compose --progress plain build --pull --no-cache
docker compose up -d --force-recreate
docker compose ps
docker compose logs --tail=100 fn-process-image fn-fetch-gee fn-batch fn-alerts prediction-service
```

Do **not** add `down --volumes` or `system prune --volumes` unless you intend to reset
local data. To rebuild only the affected Python images:

```bash
docker compose --progress plain build --pull --no-cache \
  fn-process-image fn-fetch-gee fn-batch fn-alerts prediction-service
docker compose up -d --force-recreate
```

Verify the installed metadata in each image without starting Firebase or calling GCP:

```bash
for service in fn-process-image fn-fetch-gee fn-batch fn-alerts prediction-service; do
  docker compose run --rm --no-deps --entrypoint python "$service" -m pip check
done
curl --fail http://localhost:8090/healthz
curl --fail http://localhost:8081/healthz
```

Function endpoints consume POST/CloudEvent payloads, so a browser GET returning 400 or
405 is not a dependency failure. Use the simulation commands in the README instead.

## Base image and build-network troubleshooting

Build failures in this stack are usually the build container's network, not the
Dockerfiles. Three signatures seen on a Windows/Docker Desktop checkout:

```
WARNING: fetching https://dl-cdn.alpinelinux.org/alpine/v3.23/main/x86_64/APKINDEX.tar.gz: DNS: transient error (try again later)
ERROR: unable to select packages:
  tini (no such package):
    required by: world[tini]
```

```
WARNING: fetching .../v3.23/community/x86_64/APKINDEX.tar.gz: v2 database format error
```

```
failed to compute cache key: failed to copy: httpReadSeeker: failed open: ...
Get "https://production.cloudfront.docker.com/registry-v2/docker/registry/v2/blobs/sha256/e5/...":
dialing production.cloudfront.docker.com:443 container via direct connection
because Docker Desktop has no HTTPS proxy: connecting to
production.cloudfront.docker.com:443: dial tcp: lookup production.cloudfront.docker.com: no such host
```

The earlier variant names `registry-1.docker.io` instead - same fault, one hop
earlier. The instruction BuildKit blames, for example `WORKDIR /app`, is irrelevant:
it failed while materialising the base image's layers.

The first two mean the same thing: `apk` could not load a package index, so it
reported the requested package as nonexistent. Alpine 3.21+ publishes APKINDEX in the
v2 format, which the `apk-tools` in some Docker Desktop VMs cannot parse, and a
registry mirror or flaky resolver turns the rest into `DNS: transient error`.

The third is the registry content path: the build VM can resolve
`registry-1.docker.io` (metadata succeeds) but not `production.cloudfront.docker.com`,
where Docker Hub redirects blob downloads. Read the hint it hands you - *"because
Docker Desktop has no HTTPS proxy"* - a proxy is configured for HTTP only, so HTTPS
traffic from the VM bypasses it and hits a resolver that cannot answer. The partial
downloads (`sha256:... 10.49MB / 11.80MB`) are the same failure: layers stall, the
build aborts, and mid-copy it reports `failed to compute cache key`.

Confirm it from inside the VM before touching anything else:

```powershell
docker run --rm alpine sh -c "nslookup production.cloudfront.docker.com && nslookup registry-1.docker.io"
docker info --format '{{json .RegistryConfig.Mirrors}}'   # expect []
```

If the first `nslookup` fails and the second resolves, this is purely the VM's DNS
path for the blob CDN - no Dockerfile change can fix it. Note also that **BuildKit
never consults `docker images`**: a `docker pull` warms the classic builder only, so a
BuildKit build re-streams every base layer for every target. That is why targets whose
base layers are already in the BuildKit cache (the mock servers, `FROM` resolved in
0.1 s) succeed while `firebase` and `api-gateway` fail in the same run.

Fixes, in order of preference:

1. If the proxy page shows an HTTP proxy but no HTTPS one (the usual cause of the
   `no such host` variant): either fill in **Secure Web Proxy (HTTPS)** with the same
   address, or clear both boxes so the VM uses direct system DNS. Restart Docker
   Desktop afterwards - the VM's resolver only re-reads settings on restart.
2. Update Docker Desktop (Settings → General → *Check for updates*). Newer builds
   ship an `apk-tools` that reads the v2 index, and any `node:20` image cached from an
   older pull should be refreshed with `docker compose build --pull`.
3. Give containers a resolver that works off the corporate/VPN network:
   Docker Desktop → Settings → Resources → Network → *DNS server* → `8.8.8.8, 1.1.1.1`.
   The same value in the Docker Engine JSON tab is `{"dns": ["8.8.8.8", "1.1.1.1"]}`.
4. If a registry mirror is configured for Docker Hub, remove it (or add
   `https://index.docker.io/1.1/` as a fallback) in Docker Engine settings; broken
   mirrors cause the slow layer downloads that turn into DNS timeouts.

### Build offline-ish: pre-pull the bases, skip BuildKit

Until the resolver is fixed, take the registry out of the build path. The
`docker pull` loop retries on its own and needs no BuildKit, and
`DOCKER_BUILDKIT=0` switches to the classic builder, which *does* use whatever is
already in the local image store instead of resolving each tag (and each `# syntax=`
frontend image) against the registry and re-streaming every layer:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\prepull_base_images.ps1 -Build
docker compose up          # images are built; no --build needed
```

```bash
./scripts/prepull_base_images.sh --build
docker compose up
```

Without `-Build`/`--build` the scripts only pull; in that case run
`DOCKER_BUILDKIT=0 docker compose up --build` yourself.

The classic builder still runs the same `RUN` layers, so the *distro* CDNs must be
reachable for those (npm, PyPI and Debian are separate hosts from
`cloudfront.docker.com` and usually still work when the registry path is broken), but
no base image is re-downloaded per target and no frontend image is fetched:
`functions/Dockerfile`, `services/*/Dockerfile` and the local mocks carry no
`# syntax=` pin. After one successful classic build, BuildKit's cache is still empty,
so avoid `docker builder prune` until the proxy and DNS settings are fixed - and when
you do upgrade a base image, use `docker compose build --pull` on a healthy network
rather than pruning the whole builder.

### The API gateway no longer installs packages at runtime

The gateway image moved from `node:20-alpine` to `node:20-bookworm-slim` and the
`apk add tini` layer was dropped, so rebuilding `api-gateway` needs only the base
image and `npm`. The Debian base is also the one the local Firebase emulator image
already downloads, so the two builds share the layer cache. Signal handling is
unchanged: `docker compose` delivers `SIGTERM`/`SIGINT` straight to the Node process,
which installs handlers for both, and Cloud Run's sandbox reaps orphans itself.

### `No matching distribution found for <package>`

This one is not network related: it means a requirements file lists a package that
does not exist on PyPI. `functions/common/requirements.txt` is vendored into every
function image and into `requirements-dev.txt`, so a stray local edit there breaks all
four function builds at once. Recover with a clean copy and verify:

```bash
git checkout -- functions/common/requirements.txt
# every pin below must exist on PyPI, e.g.:
python -c "import json,urllib.request as u; d=json.load(u.urlopen('https://pypi.org/pypi/protobuf/json')); print('4.25.3' in d['releases'])"
```

After changing `functions/common/requirements.txt`, rebuild every Python image - the
common layer is shared, so a partially cached stack mixes old and new SDKs, and
`pip check` inside the image is what surfaces it.

## CRLF line endings

A container that exits instantly with code 127 and
`/usr/bin/env: 'bash\r': No such file or directory` - the failing line being a script's
shebang - is Git's `core.autocrlf=true` rewriting LF to CRLF at checkout on Windows,
not an image problem. The repository stores LF (no tracked file contains a CR) and
`.editorconfig` asks editors for LF, but neither applies at checkout time;
`.gitattributes` (`* text=auto eol=lf`) does.

```powershell
git ls-files --eol local/firebase/entrypoint.sh   # expect `i/lf w/lf`; `w/crlf` is the bug
git config core.autocrlf false
git add --renormalize .
git commit -m "chore: normalise line endings"
del local\firebase\entrypoint.sh
git restore local/firebase/entrypoint.sh
grep -c ([char]13) local/firebase/entrypoint.sh    # 0 once fixed
```

`git pull` alone is already enough to boot the stack: the Compose `firebase` service
`command` strips CRs from *each candidate entrypoint* (the bind-mounted working copy
first, then the image copy) and execs the first one that passes `sh -n`, so a stale
CRLF image is bypassed and the working file is repaired in place. Because that repair
rewrites a file Git had stored with CRLF, `git status` may afterwards list
`local/firebase/entrypoint.sh` as modified while the content matches the repository's
bytes - commit it with `git add --renormalize .`, or `git restore` it. Run
`docker compose up --build` once to bake a clean copy into the image.

Two things that are *not* enough on their own:

- A CRLF script cannot self-repair when it is exec'd: the kernel rejects `#!/bin/sh\r`
  (and `#!/usr/bin/env: 'bash\r'`) before any line of the script runs. The repair must
  live outside the file (Compose `command`, image build).
- `local/firebase/entrypoint.sh` is POSIX sh, one statement per line: multi-line
  constructs (`if x && y \` plus continuation, `ARGS=(...)`) make the parser see
  `then\r` or treat `((` as arithmetic and fail. Keep the script readable by dash even
  with CRLF, and avoid bash arrays.

Any other script mounted into a container is equally affected; strip CR at the call
site the same way, or invoke it as `sh file.sh` only if it is one-statement-per-line
POSIX sh.

## Bootstrapping the cloud deployments

### 1. Bootstrap outside GitHub Actions

The Terraform configuration creates its own GitHub WIF provider and service accounts,
so the first apply must use an existing human or cloud administrator identity, not the
as-yet-uncreated GitHub identity. This provisions billable resources; review the plan
and organisation permissions first.

Use the Google Cloud CLI, Terraform 1.9.8 and a current GitHub CLI locally. Replace
every placeholder below. Do not paste credentials into chat, issues or commits.

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
# Edit terraform.tfvars: project, repository, region and locations, admin domain,
# environment and application secret values. Prefer TF_VAR_* for secrets.
# Edit backend.hcl: bucket=<TF_STATE_BUCKET>, prefix="vayusetu/dev".
terraform init -backend-config=backend.hcl
terraform fmt -check -recursive
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
```

> **Run `terraform fmt -recursive` before the first apply.** The README records that
> Terraform was never executed while this repository was written, and a `terraform
> fmt -check -recursive -diff` run against a current binary reports files that need
> formatting (exit code 3). The gate sits near the top of the Terraform job, so an
> unformatted tree fails there with the diff in the log before `plan` runs. Formatting
> is a no-op for behaviour, so run the command, commit the result, and the check turns
> green.

If infrastructure already exists, use its existing remote state and matching
configuration. Do not apply a fresh state over existing resources or create a second
provider blindly. The bootstrap identity needs permission to create the resources and
grant the IAM bindings declared in `iam.tf`. Register the project with Earth Engine,
enable and configure Firebase and Hosting, and create the Firebase web app as the
README describes. A dependency fix does not perform these steps.

### 2. Populate GitHub Actions variables

Repository variables are recommended, because the quality jobs also read public
frontend configuration. Deployment jobs use the GitHub Environment named by the
repository variable `ENVIRONMENT` (default `dev`); check for stale environment-level
overrides there, and configure approval and branch protection for that environment.

From `infrastructure/terraform`, after the initial apply:

```bash
# Requires repository Variables write permission on your GitHub connection.
# These outputs are non-secret configuration, not Terraform's sensitive outputs.
terraform output -json github_repository_variables | \
  jq -r 'to_entries[] | [.key, (.value | tostring)] | @tsv' | \
  while IFS=$'\t' read -r name value; do
    gh variable set "$name" --repo "$GH_REPO" --body "$value"
  done
gh variable set TF_STATE_BUCKET --repo "$GH_REPO" --body "$TF_STATE_BUCKET"
gh variable list --repo "$GH_REPO"
cd ../..
```

The output includes `API_GATEWAY_URL`, `ENVIRONMENT` and both database locations, in
addition to the provider, service accounts, buckets and registry. `TF_STATE_BUCKET`
stays explicit because the remote backend is bootstrapped separately. Keep the state
prefix (`vayusetu/<environment>`) consistent with the workflow.

The provider must be the full resource name
`projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/POOL/providers/PROVIDER`.
Service account variables must be email addresses, taken from the Terraform outputs
rather than guessed project IDs or numbers. `ARTIFACT_REGISTRY` is a repository path
such as `us-central1-docker.pkg.dev/PROJECT/REPOSITORY`, without `https://`.

Also set the public frontend values from your Firebase web app and Google Maps
configuration: `NEXT_PUBLIC_FIREBASE_API_KEY`, `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`,
`NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET`, `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID`,
`NEXT_PUBLIC_FIREBASE_APP_ID`, `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`,
`NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID`. They are bundled at build time, so configure API-key
restrictions and authorised domains. The README lists the full optional variable set.

Set Terraform's application **secrets** with secure GitHub CLI prompts or the
repository Settings UI (do not put secret values on the command line):

```bash
for name in TWILIO_ACCOUNT_SID TWILIO_AUTH_TOKEN TWILIO_WHATSAPP_FROM \
  TWILIO_VOICE_FROM GOOGLE_AI_STUDIO_API_KEY PHONE_HASH_SECRET; do
  gh secret set "$name" --repo "$GH_REPO"
done
```

Keep the values consistent with the bootstrap configuration. The Terraform identity
needs access to the remote-state bucket, and the WIF repository claim must match
`samudragupto/VayuSetu` exactly. `wif.tf` grants `roles/iam.workloadIdentityUser` on
both pipeline accounts. For later 403 errors, inspect the actual missing permission
instead of introducing service-account JSON keys or broad owner grants.

### 3. Validate and deploy in order

Push workflows start on merge, so configure WIF first. For an initial rollout, finish
the infrastructure before dispatching backend and frontend manually. A re-run of an
old workflow run uses the old workflow revision; dispatch a new run against updated
`main` to exercise the current one.

```bash
# Inspect a plan first; review the Actions result before applying.
gh workflow run terraform.yml --ref main -f action=plan
gh run list --workflow terraform.yml --limit 5
# Then, only after reviewing the plan:
gh workflow run terraform.yml --ref main -f action=apply
# Wait for infrastructure success before proceeding:
gh workflow run backend-deploy.yml --ref main -f deploy=true
# Wait for backend health checks, verify API_GATEWAY_URL, then:
gh workflow run frontend-deploy.yml --ref main

gh run list --limit 10
# For any failing run, substitute its numeric ID:
gh run view RUN_ID --log-failed
```

While the variables are absent, the deployment jobs are skipped and the preflight job
in each run lists what is missing - see
[Deployment configuration](#deployment-configuration-and-workflow-behaviour). The
backend summary fails if a deployment fails or is cancelled, and explains a
`skipped` row instead of passing it off as a success. The function deploy command uses
gcloud's `^|^` dictionary delimiter so the comma-separated Gemini model list arrives
as one value; do not include `|` in those environment values.

## Reproducing CI validation without Docker

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
ruff check functions services/prediction-service ml scripts
pytest scripts/tests -q
# Match CI: separate processes prevent collisions between functions' main modules.
for component in functions/common functions/process_citizen_image \
  functions/fetch_gee_metrics functions/send_authority_alerts \
  functions/batch_predict services/prediction-service ml; do
  pytest "$component" -q || exit 1
done
bash scripts/stage_functions.sh --all
```

`scripts/tests` covers the deployment preflight and workflow gating as well as
dependency staging, so it is the fastest way to confirm a workflow edit behaves: it
asserts that every deployment job is gated by the preflight job, keeps the strict
configuration check, and stops the summary job from failing on skipped work.

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

The gateway and dashboard gates run on Node 20: `npm ci && npm run lint && npm run
typecheck && npm test` in `services/api-gateway`, and `npm ci && npm run lint && npm
run typecheck && npm run build` in `frontend`.
