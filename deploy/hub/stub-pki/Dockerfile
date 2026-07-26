# Dev-only stub PKI service — see app.py's module docstring. Not the
# production hub PKI service (that's part of the Go ingest service, per
# docs/architecture/ARCHITECTURE-V2.md).
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

RUN useradd -r -s /bin/false stub-pki && mkdir -p /pki && chown stub-pki /pki
USER stub-pki

EXPOSE 8443
CMD ["python3", "app.py"]
