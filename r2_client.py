# r2_client.py
import os
import boto3
import mimetypes
from urllib.parse import quote
from botocore.config import Config

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.getenv("R2_BUCKET")
R2_PUBLIC_BASE = os.getenv("R2_PUBLIC_BASE")  # ex.: https://pub-XXXXX.r2.dev/blackbot-assets

missing = [k for k, v in {
    "R2_ACCOUNT_ID": R2_ACCOUNT_ID,
    "R2_ACCESS_KEY_ID": R2_ACCESS_KEY_ID,
    "R2_SECRET_ACCESS_KEY": R2_SECRET_ACCESS_KEY,
    "R2_BUCKET": R2_BUCKET,
    "R2_PUBLIC_BASE": R2_PUBLIC_BASE,
}.items() if not v]
if missing:
    raise RuntimeError(f"Variáveis de ambiente do R2 ausentes: {', '.join(missing)}")

_session = boto3.session.Session()
_s3 = _session.client(
    "s3",
    endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    config=Config(signature_version="s3v4"),
)

def guess_ext(filename: str, content_type: str | None) -> str:
    """
    Determina a extensão do arquivo, priorizando o nome original.
    Se não houver, tenta inferir pelo content_type.
    """
    if filename and "." in filename:
        return "." + filename.rsplit(".", 1)[-1].lower()
    if content_type:
        ext = mimetypes.guess_extension(content_type)
        if ext:
            return ext
    return ""

def build_public_url(key: str) -> str:
    # Garante path seguro; preserva '/' entre pastas
    safe_key = quote(key, safe="/")
    # R2_PUBLIC_BASE já inclui '/<bucket>' no final
    return f"{R2_PUBLIC_BASE}/{safe_key}"

def presign_put_url(key: str, content_type: str, expires_in: int = 600) -> str:
    """
    Gera URL pré‑assinada para PUT com Content-Type fixado.
    O cliente deve enviar o MESMO Content-Type no PUT.
    """
    params = {
        "Bucket": R2_BUCKET,
        "Key": key,
        "ContentType": content_type or "application/octet-stream",
    }
    url = _s3.generate_presigned_url(
        ClientMethod="put_object",
        Params=params,
        ExpiresIn=expires_in,
        HttpMethod="PUT",
    )
    return url