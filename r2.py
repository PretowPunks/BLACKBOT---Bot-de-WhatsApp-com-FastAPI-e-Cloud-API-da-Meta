# r2.py
import os, boto3
from botocore.config import Config

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.getenv("R2_BUCKET")
R2_PUBLIC_BASE = os.getenv("R2_PUBLIC_BASE")  # ex: https://pub-xxx.r2.dev/blackbot-assets

session = boto3.session.Session()
client = session.client(
    service_name="s3",
    endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    config=Config(s3={"addressing_style": "virtual"})
)

def create_presigned_put(key: str, content_type: str, expires=600) -> str:
    return client.generate_presigned_url(
        "put_object",
        Params={"Bucket": R2_BUCKET, "Key": key, "ContentType": content_type, "ACL": "public-read"},
        ExpiresIn=expires,
        HttpMethod="PUT"
    )

def public_url(key: str) -> str:
    base = (R2_PUBLIC_BASE or "").rstrip("/")
    return f"{base}/{key.lstrip('/')}" if base else ""