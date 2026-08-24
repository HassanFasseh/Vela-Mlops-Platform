# Sample requirements.txt — a SEPARATE file, uploaded alongside this one
# (optional field on the upload form). The base custom-runner image only
# ships fastapi, uvicorn, joblib, numpy, pandas and scikit-learn — list
# anything else your predict.py imports, one package per line, same
# syntax pip normally uses:
#
#     xgboost==2.0.3
#     lightgbm==4.3.0
#     onnxruntime==1.17.1
#     scipy==1.13.0
#     pillow==10.3.0
#
# Leave it out entirely if load_model()/predict() only need what's
# already in the base image (e.g. Option A below).

"""
Vela custom-runner interface contract
======================================

Fill in load_model() and predict() below, then upload this file (as
predict.py) together with your model weights through the "Upload custom
model" flow. Vela packages both into a container image and serves them
behind POST /predict — see custom-runner/main.py for exactly how these
two functions get called.

    load_model(model_dir)
        Called once, at container startup, with model_dir set to
        "/app/model_files" — that directory holds every file you
        uploaded alongside this script. Load whatever you need from
        there and return it — whatever you return is passed as `model`
        to every predict() call for the life of the container. Do all
        your expensive setup here, not in predict().

    predict(model, input_data)
        Called once per POST /predict request. `model` is exactly what
        load_model() returned. `input_data`'s type depends on the
        input_type you chose when uploading:

          input_type="text"   input_data: str
                               Caller sends {"text": "..."}.
                               input_data is that string, as-is.

          input_type="json"   input_data: dict
                               Caller sends {"data": {...}}.
                               input_data is that dict, as-is — shape it
                               however your model needs (and describe it
                               for callers via the input_schema field
                               when uploading).

          input_type="file"   input_data: str (base64)
                               Caller sends a multipart form with a
                               `file` field (an image, audio clip, PDF,
                               whatever your model reads). Vela reads the
                               raw bytes and base64-encodes them before
                               calling predict() — decode with
                               base64.b64decode(input_data) to get the
                               original bytes back.

        Return a JSON-serializable dict. If your model produces a single
        classification, returning {"label": ..., "score": ...} gets you
        the same colored-badge + confidence-bar treatment in Vela's
        prediction tester that the built-in sentiment/zero-shot models
        get — anything else is shown as-is. Raise on failure; Vela turns
        that into a 400 response ({"error": str(e)}) rather than a crash.

Pick ONE of the three worked examples below (sklearn / xgboost /
pytorch) that matches your model, delete the other two, and adjust the
model_files/ filenames and predict() body to match what you actually
uploaded and how your model expects its input shaped.
"""

import os


# =============================================================================
# Option A — scikit-learn, input_type="json"   [ACTIVE — this is the one
# load_model()/predict() actually in effect below; the other two options
# are shown commented-out further down as a reference]
#
# Typical for tabular models: the caller POSTs a JSON object of feature
# name -> value, e.g. {"data": {"age": 34, "income": 52000, "region": 2}}
# =============================================================================

FEATURE_ORDER = ["age", "income", "region"]  # must match your training data's column order


def load_model(model_dir):
    import joblib

    return joblib.load(os.path.join(model_dir, "model.joblib"))


def predict(model, input_data):
    # input_data is a dict (input_type="json"), e.g. {"age": 34, ...}
    features = [[input_data[key] for key in FEATURE_ORDER]]
    proba = model.predict_proba(features)[0]
    top_idx = proba.argmax()
    return {
        "label": str(model.classes_[top_idx]),
        "score": float(proba[top_idx]),
        "all_scores": {str(c): float(p) for c, p in zip(model.classes_, proba)},
    }


# =============================================================================
# Option B — XGBoost, input_type="json"
#
# Same input shape as Option A above — XGBoost's sklearn-compatible API
# (XGBClassifier/XGBRegressor) works identically to Option A once
# loaded. This example instead shows the native Booster API, which is
# what you get from xgboost.train() or a raw .json/.ubj model file.
#
# xgboost isn't in the base image — upload a requirements.txt alongside
# this file with a line for it (see the sample at the top of this file).
# =============================================================================
#
# def load_model(model_dir):
#     import xgboost as xgb
#     booster = xgb.Booster()
#     booster.load_model(os.path.join(model_dir, "model.json"))
#     return booster
#
# def predict(model, input_data):
#     import xgboost as xgb
#     features = [[input_data[key] for key in FEATURE_ORDER]]
#     dmatrix = xgb.DMatrix(features)
#     score = float(model.predict(dmatrix)[0])
#     return {"label": "positive" if score >= 0.5 else "negative", "score": score}


# =============================================================================
# Option C — PyTorch, input_type="file"
#
# Typical for image/audio models: the caller POSTs a multipart file
# field. input_data arrives base64-encoded — decode it back to raw bytes
# before handing it to your usual preprocessing.
#
# NOTE: the default custom-runner image (Dockerfile) does not include
# torch/torchvision/pillow. Two ways to get them:
#   1. custom-runner/Dockerfile.torch already has all three — pass
#      use_torch=true when (re-)dispatching custom-deploy.yml. The admin
#      upload form doesn't expose that toggle yet, so ask whoever's
#      running the GitHub Actions workflow to re-dispatch it by hand
#      with use_torch=true for this deployment_name.
#   2. Or list torch/torchvision/pillow in a requirements.txt uploaded
#      alongside this file and stay on the slim image — works, but
#      re-downloads the same multi-gigabyte wheels Dockerfile.torch
#      already has baked in, so (1) is usually the better call for a
#      PyTorch model specifically.
# =============================================================================
#
# def load_model(model_dir):
#     import torch
#     model = torch.load(os.path.join(model_dir, "model.pt"), map_location="cpu")
#     model.eval()
#     return model
#
# def predict(model, input_data):
#     import base64
#     import io
#     import torch
#     from PIL import Image
#     from torchvision import transforms
#
#     image_bytes = base64.b64decode(input_data)
#     image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
#     tensor = transforms.Compose([
#         transforms.Resize((224, 224)),
#         transforms.ToTensor(),
#     ])(image).unsqueeze(0)
#
#     with torch.no_grad():
#         logits = model(tensor)
#         probs = torch.softmax(logits, dim=1)[0]
#         top_idx = int(torch.argmax(probs))
#
#     labels = ["class_a", "class_b", "class_c"]  # replace with your model's real classes
#     return {"label": labels[top_idx], "score": float(probs[top_idx])}


# =============================================================================
# Reference — input_type="text" (not used by any option above; NLP models
# like the platform's built-in sentiment/zero-shot runners use this)
#
# def predict(model, input_data):
#     # input_data is a str, e.g. "this movie was great"
#     result = model.predict([input_data])[0]
#     return {"label": str(result), "score": 1.0}
# =============================================================================
