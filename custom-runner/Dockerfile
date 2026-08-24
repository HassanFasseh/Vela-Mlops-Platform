FROM python:3.11-slim

WORKDIR /app

# CPU-only torch/torchvision wheels, same as model-runner/Dockerfile —
# the default PyPI wheels pull in multi-gigabyte CUDA builds that this
# CPU-only cluster (and the arm64+amd64 cross-build in
# custom-deploy.yml) has no use for and would make painfully slow.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision && \
    pip install --no-cache-dir \
        fastapi uvicorn \
        scikit-learn xgboost lightgbm \
        onnxruntime \
        joblib pandas numpy pillow librosa scipy

COPY main.py /app/main.py

# predict.py and model_files/ are NOT part of this repo — custom-
# deploy.yml downloads them from MinIO into this build context
# (custom-runner/) before `docker build` runs (see
# .github/workflows/custom-deploy.yml, step "Download model files from
# MinIO"). Both are required for the container to start: predict.py
# supplies load_model()/predict() (see predict_template.py for the
# interface contract), model_files/ is whatever load_model() reads
# from disk.
COPY predict.py /app/predict.py
COPY model_files/ /app/model_files/

# Overridden per-deployment via the Kubernetes Deployment's env (see
# custom-deploy.yml) — text, json, or file.
ENV INPUT_TYPE=text

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
