FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Fuseaux IANA (dont Europe/Paris) pour des horodatages corrects été/hiver.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY app/ /app/
RUN useradd --create-home --uid 10001 rhsync && chown -R rhsync:rhsync /app
USER rhsync
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import os; assert all(os.getenv(k) for k in ('GRIST_HOST','RH_SYNC_API_KEY','DEMANDES_DOC_ID','COCKPIT_DOC_ID'))"
CMD ["python", "/app/runner.py"]
