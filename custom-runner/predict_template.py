# A note on requirements.txt: the upload form still accepts one
# alongside this file, but as of the cloud-native rewrite (one fixed
# custom-runner:base image, shared by every custom deployment, with
# no per-deployment build step) nothing installs it anymore — it's
# stored in MinIO and otherwise unused. load_model()/predict() below
# can only rely on what's already in the base image: fastapi, uvicorn,
# scikit-learn, joblib, pandas, numpy. Anything else (xgboost, torch,
# onnxruntime, pillow, ...) currently has no supported way to reach a
# running deployment — see Options B and C further down for exactly
# where that bites.

"""
Vela custom-runner interface contract
======================================

Fill in load_model() and predict() below, then upload this file (as
predict.py) together with your model weights through the "Upload custom
model" flow. Vela packages both into a container image and serves them
behind POST /predict — see custom-runner/base/main.py for exactly how
these two functions get called.

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

Option A (scikit-learn) below is the only one that actually runs against
the current base image as-is. Options B (XGBoost) and C (PyTorch) are
kept as reference for the shape of load_model()/predict() you'd write
for those libraries, but neither has a supported path to actually get
the library installed into a running deployment right now — see each
option's own note.
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
# xgboost isn't in the base image, and there's currently no supported
# way to add it for a running deployment (see the requirements.txt note
# at the top of this file) — this option won't actually run yet.
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
# NOTE: custom-runner:base (custom-runner/base/) does not include
# torch/torchvision/pillow, and — unlike the earlier per-deployment-
# build architecture this replaced — there's currently no per-model
# way to add them at all: one fixed image is shared by every custom
# deployment, with no build or install step of its own left to hook
# into. This option won't actually run until that gap is closed (a
# torch-enabled variant image, most likely, the same idea as the old
# Dockerfile.torch but for this shared-image model).
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
