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

ARG FUNCTION_DIR
ARG FUNCTION_TARGET
ARG FUNCTION_SIGNATURE_TYPE=cloudevent

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080 \
    FUNCTION_TARGET=${FUNCTION_TARGET} \
    FUNCTION_SIGNATURE_TYPE=${FUNCTION_SIGNATURE_TYPE}

RUN test -n "${FUNCTION_DIR}" || (echo "FUNCTION_DIR build argument is required" && exit 1)

RUN groupadd --system app && useradd --system --gid app --home-dir /app app
WORKDIR /app

# Install dependencies first to benefit from layer caching.
COPY functions/common/requirements.txt /tmp/common-requirements.txt
COPY functions/${FUNCTION_DIR}/requirements.txt /tmp/function-requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /tmp/common-requirements.txt -r /tmp/function-requirements.txt \
    && pip install "functions-framework>=3.8,<4"

# Function source plus the vendored shared package.
COPY functions/${FUNCTION_DIR}/ /app/
COPY functions/common/vayusetu_common /app/vayusetu_common
RUN rm -rf /app/tests /app/conftest.py /app/__pycache__ && chown -R app:app /app

USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import socket,os; s=socket.create_connection(('127.0.0.1', int(os.environ.get('PORT','8080'))), timeout=3); s.close()" || exit 1

CMD ["sh", "-c", "exec functions-framework --target \"${FUNCTION_TARGET}\" --signature-type \"${FUNCTION_SIGNATURE_TYPE}\" --port \"${PORT}\" --host 0.0.0.0"]
