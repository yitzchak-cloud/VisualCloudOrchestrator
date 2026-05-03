"""
core/iap_identity.py
====================
מחלץ identity מ-IAP JWT ומייצר access token על-ידי impersonation.

דרישות:
  - ה-VM SA צריך roles/iam.serviceAccountTokenCreator
    על כל SA שהוא מבצע עליו impersonation.
  - כל משתמש מופה ל-SA בפורמט: user-<hash>@<project>.iam.gserviceaccount.com
    (או SA קבוע לפי email — תלוי במדיניות).

env vars:
  IAP_AUDIENCE   — /projects/<num>/global/backendServices/<id>
  GCP_PROJECT    — פרויקט שבו ה-SAs חיים
"""
from __future__ import annotations

import hashlib
import logging
import os
from functools import lru_cache

import google.auth
import google.auth.transport.requests
from google.oauth2 import id_token as google_id_token
import google.auth.impersonated_credentials

logger = logging.getLogger(__name__)

IAP_AUDIENCE = os.environ.get("IAP_AUDIENCE", "")
GCP_PROJECT  = os.environ.get("GCP_PROJECT", os.environ.get("DEFAULT_GCP_PROJECT", ""))


def extract_iap_email(iap_jwt: str) -> str | None:
    """
    מאמת את ה-IAP JWT ומחזיר את ה-email של המשתמש.
    מחזיר None אם ה-JWT לא תקין.
    """
    if not iap_jwt:
        return None
    try:
        request   = google.auth.transport.requests.Request()
        id_info   = google_id_token.verify_token(
            iap_jwt,
            request,
            audience=IAP_AUDIENCE,
            certs_url="https://www.gstatic.com/iap/verify/public_key",
        )
        email = id_info.get("email", "")
        logger.info("IAP identity resolved: %s", email)
        return email or None
    except Exception as exc:
        logger.warning("IAP JWT validation failed: %s", exc)
        return None


def _sa_for_user(email: str) -> str:
    """
    ממפה email → SA email.

    אפשרויות:
      A) SA ייעודי לכל משתמש (צריך ליצור מראש).
      B) SA אחד משותף לכל המשתמשים (פחות בטוח).
      C) impersonation ישירה של ה-Google account (לא נתמך ב-GCP).

    כאן אנחנו מיישמים A:
      user-<first8ofsha256(email)>@<project>.iam.gserviceaccount.com
    """
    suffix = hashlib.sha256(email.encode()).hexdigest()[:8]
    return f"user-{suffix}@{GCP_PROJECT}.iam.gserviceaccount.com"


def get_impersonated_token(email: str) -> str:
    """
    מבצע impersonation של ה-SA המשויך ל-email ומחזיר access token.
    ה-VM SA חייב להיות בעל roles/iam.serviceAccountTokenCreator על ה-SA היעד.
    """
    target_sa = _sa_for_user(email)
    logger.info("Impersonating SA %s for user %s", target_sa, email)

    # credentials של ה-VM עצמו (ADC)
    source_creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )

    impersonated = google.auth.impersonated_credentials.Credentials(
        source_credentials=source_creds,  
        target_principal=target_sa,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        lifetime=3600,
    )

    # רענן כדי לקבל access token
    request = google.auth.transport.requests.Request()
    impersonated.refresh(request)
    return impersonated.token # type: ignore[attr-defined]