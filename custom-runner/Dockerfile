FROM python:3.11-slim

WORKDIR /app

# Bare minimum for the runner itself plus the most common model
# libraries. Anything more specific to a particular model (onnxruntime,
# xgboost, lightgbm, scipy, pillow, torch, ...) belongs in that model's
# own requirements.txt below, not baked into every image regardless of
# whether it's actually used — that's what made this image 1.35GB.
RUN pip install --no-cache-dir \
        fastapi uvicorn \
        joblib numpy pandas scikit-learn

COPY main.py /app/main.py

# predict.py, model_files/ and requirements.txt are NOT part of this
# repo — custom-deploy.yml downloads them from MinIO into this build
# context (custom-runner/) before `docker build` runs (see
# .github/workflows/custom-deploy.yml, step "Download predict.py,
# model_files/ and requirements.txt from MinIO"). requirements.txt is
# optional at upload time; the workflow writes an empty one when there
# isn't one, so this COPY always has something to copy and the RUN
# below is always a (possibly no-op) valid pip install.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# predict.py supplies load_model()/predict() (see predict_template.py
# for the interface contract), model_files/ is whatever load_model()
# reads from disk. Both required for the container to start.
COPY predict.py /app/predict.py
COPY model_files/ /app/model_files/

# Overridden per-deployment via the Kubernetes Deployment's env (see
# custom-deploy.yml) — text, json, or file.
ENV INPUT_TYPE=text

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
