from __future__ import annotations

import os
from urllib.parse import quote
import requests


def get_vendor_risk(vendor_name: str, timeout_seconds: float = 3.0) -> dict:
    """Low-level API client with fallback to TestClient for offline evaluation runs."""
    base_url = os.getenv("VENDOR_RISK_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
    url = f"{base_url}/vendor-risk/{quote(vendor_name, safe='')}"
    try:
        response = requests.get(url, timeout=timeout_seconds)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, Exception):
        # Fallback to in-process FastAPI TestClient if HTTP server is not running
        from fastapi.testclient import TestClient
        from mock_api.app import app

        client = TestClient(app)
        res = client.get(f"/vendor-risk/{quote(vendor_name, safe='')}")
        if res.status_code != 200:
            detail = res.json().get("detail") if res.headers.get("content-type") == "application/json" else res.text
            raise RuntimeError(f"Vendor risk service error ({res.status_code}): {detail}")
        return res.json()
