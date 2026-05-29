"""
Windmill test script — Verifica integración con botilleria_core API.
"""

# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
from __future__ import annotations

import json
import urllib.request
from typing import Any


def main() -> dict[str, Any]:
    """Health check + endpoint test contra botilleria_core API."""
    base_url = "http://botilleria_core_api:8000"

    # 1. Health check
    resp = urllib.request.urlopen(f"{base_url}/health")
    health = json.loads(resp.read())

    # 2. OpenAPI docs available
    resp = urllib.request.urlopen(f"{base_url}/openapi.json")
    spec = json.loads(resp.read())

    # 3. Verify /chat endpoint exists in spec
    paths = spec.get("paths", {})
    chat_exists = "/chat" in paths
    chat_stream_exists = "/chat/stream" in paths

    # 4. Verify tenant endpoints exist
    tenant_endpoints = [p for p in paths if p.startswith("/tenants")]
    admin_endpoints = [p for p in paths if p.startswith("/admin")]

    return {
        "health": health,
        "openapi_title": spec.get("info", {}).get("title", "unknown"),
        "openapi_version": spec.get("info", {}).get("version", "unknown"),
        "endpoints": list(paths.keys()),
        "chat_endpoint_available": chat_exists,
        "chat_stream_endpoint_available": chat_stream_exists,
        "tenant_endpoints_count": len(tenant_endpoints),
        "admin_endpoints_count": len(admin_endpoints),
        "status": "integration_ok",
    }
