import os
from minio import Minio
from minio.error import S3Error
import io

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio.default.svc.cluster.local:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "aodp")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "aodp_minio_2026")
BUCKET_NAME = "models"

def get_client():
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False
    )

def ensure_bucket():
    client = get_client()
    if not client.bucket_exists(BUCKET_NAME):
        client.make_bucket(BUCKET_NAME)

def upload_model(file_bytes: bytes, workspace_id: int, model_name: str) -> str:
    """Upload model file to MinIO. Returns the object path."""
    ensure_bucket()
    client = get_client()
    object_name = f"workspace-{workspace_id}/{model_name}"
    client.put_object(
        BUCKET_NAME,
        object_name,
        io.BytesIO(file_bytes),
        length=len(file_bytes),
        content_type="application/octet-stream"
    )
    return f"{BUCKET_NAME}/{object_name}"

def get_presigned_upload_url(workspace_id: int, model_name: str) -> str:
    """Generate a presigned URL for direct browser upload."""
    from datetime import timedelta
    ensure_bucket()
    client = get_client()
    object_name = f"workspace-{workspace_id}/{model_name}"
    url = client.presigned_put_object(
        BUCKET_NAME,
        object_name,
        expires=timedelta(hours=1)
    )
    return url, object_name

def list_workspace_models(workspace_id: int) -> list:
    """List all models uploaded by a workspace."""
    client = get_client()
    prefix = f"workspace-{workspace_id}/"
    try:
        objects = client.list_objects(BUCKET_NAME, prefix=prefix)
        return [{"name": obj.object_name.replace(prefix, ""), "size": obj.size, "path": obj.object_name} for obj in objects]
    except Exception:
        return []

def delete_model(workspace_id: int, model_name: str):
    """Delete a model from MinIO."""
    client = get_client()
    object_name = f"workspace-{workspace_id}/{model_name}"
    client.remove_object(BUCKET_NAME, object_name)
