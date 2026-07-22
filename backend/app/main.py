from fastapi import FastAPI

from backend.app.models import Model              # Pydantic
from backend.app.db.models import Base            # SQLAlchemy
from backend.app.database import engine
from backend.app.services.deployment import deploy_model


Base.metadata.create_all(bind=engine)


app = FastAPI()


@app.get("/")
def root():
    return {
        "message": "Hello World"
    }


@app.post("/deploy")
def deploy(model: Model):
    return deploy_model(model)