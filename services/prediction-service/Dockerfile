# Build context: repository root (the image needs both ml/ and this service).
#   docker build -f services/prediction-service/Dockerfile -t prediction-service .

FROM python:3.10-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_RETRIES=8 \
    PIP_TIMEOUT=120

WORKDIR /app

# libgomp is required by XGBoost's multi-threaded histogram implementation.
RUN apt-get update -o Acquire::Retries=3 \
    && apt-get install -y --no-install-recommends build-essential libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# See functions/Dockerfile: pip is intentionally not upgraded, so the pinned
# dependency layers stay deterministic and cache-friendly.
RUN pip install --no-cache-dir --prefer-binary "setuptools>=68" wheel

COPY functions/common/requirements.txt /tmp/common-requirements.txt
RUN pip install --no-cache-dir --prefer-binary -r /tmp/common-requirements.txt

COPY services/prediction-service/requirements.txt /tmp/function-requirements.txt
RUN pip install --no-cache-dir --prefer-binary \
    -c /tmp/common-requirements.txt -r /tmp/function-requirements.txt \
    && pip check

# Shared feature engineering library and training entry point.
COPY ml/vayusetu_ml ./vayusetu_ml
COPY ml/train_xgboost_model.py ./train_xgboost_model.py

# Application code and any pre-built model artifact provided by CI.
COPY services/prediction-service/app ./app
COPY services/prediction-service/model ./model

# Guarantee the image is self-sufficient: train a synthetic baseline model when
# CI did not supply a published one.
RUN if [ ! -f /app/model/model.joblib ]; then \
      python train_xgboost_model.py --source synthetic --rows 12000 --output /app/model/model.joblib --log-level WARNING; \
    fi

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

ENV PORT=8080 \
    MODEL_PATH=/app/model/model.joblib \
    PYTHONPATH=/app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status == 200 else 1)"

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 75"]
