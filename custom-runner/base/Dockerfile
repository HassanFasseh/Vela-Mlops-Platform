FROM python:3.11-slim

WORKDIR /app

# Minimal, fixed image shared by every custom deployment — no per-model
# dependencies (that's what the earlier custom-runner/Dockerfile +
# custom-deploy.yml per-deployment image build did; this replaces that
# entirely). predict.py and model_files/ are mounted at runtime from a
# ConfigMap and a PVC respectively (see backend/app/services/
# k8s_custom.py), not baked in here.
#
# minio isn't used by main.py at all — it's here because
# k8s_custom.create_download_job() runs this same image as the download
# Job's container, using the minio Python client to pull model_files/
# out of MinIO into the PVC (replacing minio/mc:latest, which was
# hitting Docker Hub's anonymous pull-rate limit).
RUN pip install --no-cache-dir \
    fastapi uvicorn \
    scikit-learn joblib pandas numpy \
    minio

COPY main.py /app/main.py

# Overridden per-deployment via the Kubernetes Deployment's env (see
# k8s_custom.py) — text, json, or file.
ENV INPUT_TYPE=text

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
