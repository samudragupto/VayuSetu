# Local development image for VayuSetu Cloud Functions.
#
# Runs any function directory with the Functions Framework, mirroring the
# python310 Cloud Functions (2nd gen) runtime. It is used by docker-compose
# only; production deployments use `gcloud functions deploy --source` with
# the staged directory produced by scripts/stage_functions.sh.
#
# Build context: repository root.
#   docker build -f functions/Dockerfile --build-arg FUNCTION_DIR=batch_predict -t vayusetu-fn-batch .
#   docker run -e FUNCTION_TARGET=batch_predict -e FUNCTION_SIGNATURE_TYPE=http -p 8084:8080 vayusetu-fn-batch

FROM python:3.10-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_RETRIES=8 \
    PIP_TIMEOUT=120 \
    PORT=8080

RUN groupadd --system app && useradd --system --gid app --home-dir /app app
WORKDIR /app

# Build tools are a fallback for packages without wheels on the target platform.
# Acquire::Retries keeps a transient DNS/mirror hiccup from failing the whole build.
RUN apt-get update -o Acquire::Retries=3 \
    && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# setuptools/wheel only: pip is never upgraded here. `pip install --upgrade pip`
# pulls the newest pip and then re-resolves every pin above it, which is how a
# typo in a requirements file turns into a long, confusing failure. The pip in
# python:3.10-slim is perfectly capable of installing this stack.
RUN pip install --no-cache-dir --prefer-binary "setuptools>=68" wheel

# Keep the common layer reusable across all four functions.
COPY functions/common/requirements.txt /tmp/common-requirements.txt
RUN pip install --no-cache-dir --prefer-binary -r /tmp/common-requirements.txt

# Declare function-specific args after the shared layers to preserve their cache.
ARG FUNCTION_DIR
RUN test -n "${FUNCTION_DIR}" || (echo "FUNCTION_DIR build argument is required" && exit 1)

# Constraints prevent this separate install from upgrading the shared SDK pins.
COPY functions/${FUNCTION_DIR}/requirements.txt /tmp/function-requirements.txt
RUN pip install --no-cache-dir --prefer-binary \
    -c /tmp/common-requirements.txt -r /tmp/function-requirements.txt \
    && pip check

# functions-framework==3.8.1 is already installed by each function's requirements.

ARG FUNCTION_TARGET
ARG FUNCTION_SIGNATURE_TYPE=cloudevent
ENV FUNCTION_TARGET=${FUNCTION_TARGET} \
    FUNCTION_SIGNATURE_TYPE=${FUNCTION_SIGNATURE_TYPE}

# Function source plus the vendored shared package.
COPY functions/${FUNCTION_DIR}/ /app/
COPY functions/common/vayusetu_common /app/vayusetu_common
RUN rm -rf /app/tests /app/conftest.py /app/__pycache__ && chown -R app:app /app

USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import socket,os; s=socket.create_connection(('127.0.0.1', int(os.environ.get('PORT','8080'))), timeout=3); s.close()" || exit 1

CMD ["sh", "-c", "exec functions-framework --target \"${FUNCTION_TARGET}\" --signature-type \"${FUNCTION_SIGNATURE_TYPE}\" --port \"${PORT}\" --host 0.0.0.0"]
