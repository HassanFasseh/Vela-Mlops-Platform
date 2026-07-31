from fastapi import FastAPI
from backend.app.schemas import Model
from backend.app.db.models import Base
from backend.app.database import engine
from backend.app.services.deployment import deploy_model

Base.metadata.create_all(bind=engine)
app = FastAPI()

@app.get("/")
def root():
    return {"message": "Hello World"}

@app.post("/deploy")
def deploy(model: Model):
    deploy_model(model)
    return {"status": "deployed", "model": model.name}

from backend.app.services.timeline import build_timeline

@app.get("/timeline")
def timeline(window_minutes: int = 360):
    return build_timeline(window_minutes)
