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
(the earlier variant names `registry-1.docker.io` instead - same fault, one hop
earlier. The instruction BuildKit blames, e.g. `WORKDIR /app`, is irrelevant: it
failed while materialising the base image's layers.)

The first two mean the same thing: `apk` could not load a package index, so it
reported the requested package as nonexistent. Alpine 3.21+ publishes APKINDEX in
the new v2 format, which older `apk-tools` in Docker Desktop's VM cannot always
parse, and a registry mirror or flaky resolver turns the rest into
`DNS: transient error`.

The third is the registry content path: the build VM can resolve
`registry-1.docker.io` (metadata succeeds) but not
`production.cloudfront.docker.com`, where Docker Hub redirects blob downloads.
Read the hint it hands you - *"because Docker Desktop has no HTTPS proxy"* - a proxy
is configured for HTTP only, so HTTPS traffic from the VM bypasses it and hits a
resolver that cannot answer. The partial downloads (`sha256:... 10.49MB / 11.80MB`)
are the same failure: layers stall, the build aborts, and mid-copy it reports
`failed to compute cache key`.

Confirm it from inside the VM before touching anything else:

```powershell
docker run --rm alpine sh -c "nslookup production.cloudfront.docker.com && nslookup registry-1.docker.io"
docker info --format '{{json .RegistryConfig.Mirrors}}'   # expect []
```

If the first `nslookup` fails and the second resolves, this is purely the VM's DNS
path for the blob CDN - no Dockerfile change can fix it. Note also that **BuildKit
never consults `docker images`**: a `docker pull` warms the classic builder only, so
a BuildKit build re-streams every base layer for every target. That is why targets
whose base layers are already in the BuildKit cache (the mock servers,
`FROM` resolved in 0.1 s) succeed while `firebase` and `api-gateway` fail in the
same run.

Fixes, in order of preference:

1. If the proxy page shows an HTTP proxy but no HTTPS one (the usual cause of the
   `no such host` variant): either fill in **Secure Web Proxy (HTTPS)** with the same
   address, or clear both boxes so the VM uses direct system DNS. Restart Docker
   Desktop afterwards - the VM's resolver only re-reads settings on restart.
2. Update Docker Desktop (Settings → General → *Check for updates*). Newer builds
   ship an `apk-tools` that reads the v2 index, and any `node:20-alpine` image
   cached from an older pull should be refreshed with `docker compose build --pull`.
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
already in the local image store instead of resolving each tag (and each
`# syntax=` frontend image) against the registry and re-streaming every layer:

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
reachable for those (npm/PyPI/Debian are separate hosts from `cloudfront.docker.com`
and usually still work when the registry path is broken), but no base image is
re-downloaded per target and no frontend image is fetched: `functions/Dockerfile`,
`services/*/Dockerfile` and the local mocks carry no `# syntax=` pin. After one
successful classic build, BuildKit's own cache is still empty, so avoid
`docker builder prune` until Docker Desktop's proxy/DNS settings are fixed - and
when you do upgrade a base image, use `docker compose build --pull` on a healthy
network rather than pruning the whole builder.

### CRLF line endings: `/usr/bin/env: 'bash
': No such file or directory`

A container that exits instantly with code 127 and that message - and the failing
line being a script's shebang - is Git's `core.autocrlf=true` rewriting LF to CRLF at
checkout on Windows, not an image problem. The repository stores LF (verified: no
tracked file contains a CR) and `.editorconfig` asks editors for LF, but neither
applies at checkout time; `.gitattributes` (`* text=auto eol=lf`) does.

```powershell
git ls-files --eol local/firebase/entrypoint.sh   # expect `i/lf w/lf`; `w/crlf` is the bug
git add --renormalize .                            # store the normalised endings
git commit -m "chore: normalise line endings via .gitattributes"
# force the working copy to be rewritten:
del local\firebase\entrypoint.sh
git restore local/firebase/entrypoint.sh
grep -c ([char]13) local/firebase/entrypoint.sh    # 0 once fixed
```

Recovery, and why the stack now also repairs itself:

```powershell
git ls-files --eol local/firebase/entrypoint.sh   # expect `i/lf w/lf`; `w/crlf` is the bug
git config core.autocrlf false
git add --renormalize .
git commit -m "chore: normalise line endings"
del local\firebase\entrypoint.sh
git restore local/firebase/entrypoint.sh
```

`git pull` alone is already enough to boot the stack: the Compose `firebase` service
`command` strips CRs from *each candidate entrypoint* (the bind-mounted working copy
first, then the image copy) and execs the first one that passes `sh -n`, so a stale
CRLF image is bypassed and the working file is repaired in place. Because that repair
rewrites a file Git had stored with CRLF, `git status` may afterwards list
`local/firebase/entrypoint.sh` as modified while the content matches the repo's
bytes - commit it with `git add --renormalize .`, or `git restore` it. Run
`docker compose up --build` once to bake a clean copy into the image.

Two things that are *not* enough on their own, learned the hard way:

- A CRLF script cannot self-repair when it is exec'd: the kernel rejects
  `#!/bin/sh\r` (and `#!/usr/bin/env: 'bash\r'`) before any line of the script runs.
  The repair must live outside the file (Compose `command`, image build).
- `local/firebase/entrypoint.sh` is POSIX sh, one statement per line: multi-line
  constructs (`if x && y \` + continuation, `ARGS=(...)`) make the parser see
  `then\r` / treat `((` as arithmetic and fail, so keep the script readable by
  dash even with CRLF, and avoid bash arrays.

Any other script mounted into a container is equally affected; strip CR at the call
site the same way, or invoke it as `sh file.sh` only if it is one-statement-per-line
POSIX sh.

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
