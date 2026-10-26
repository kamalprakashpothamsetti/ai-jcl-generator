"""Automated tests for JCL Studio AI — GitHub Pages & Render Deployment Security.

Verifies:
1. Health check endpoint (/health)
2. CORS headers and explicit origin controls
3. Relative frontend asset paths and no hardcoded production URLs
4. Configurable API base URL & runtime config support (config.js)
5. Zero exposed secrets or API keys in code or responses
6. Studio Access Key authentication on paid AI endpoints
7. Unrestricted access to deterministic/offline endpoints
8. In-memory sliding-window rate limiting
9. Daily spend quota guardrails
10. Render deployment blueprint (render.yaml) & GitHub Actions workflow validity
"""

import os
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

import main
from backend.security import rate_limiter, spend_tracker
from llm_provider import TokenUsage

client = TestClient(main.app)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def reset_security_state():
    """Reset rate limiter and spend tracker state before and after each test."""
    rate_limiter.reset_for_tests()
    spend_tracker.reset_for_tests()
    yield
    rate_limiter.reset_for_tests()
    spend_tracker.reset_for_tests()


# -----------------------------------------------------------------------------
# 1. Health Endpoint Tests
# -----------------------------------------------------------------------------

def test_health_endpoint():
    """Verify lightweight /health endpoint returns 200 OK and service metadata."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["service"] == "jcl-studio-ai"
    assert "version" in data


# -----------------------------------------------------------------------------
# 2. CORS Behavior Tests
# -----------------------------------------------------------------------------

def test_cors_allowed_origins():
    """Verify CORS preflight and headers for configured frontend origins."""
    assert "https://kamalprakashpothamsetti.github.io" in main.allowed_origins
    for origin in main.allowed_origins:
        headers = {
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,X-Studio-Access-Key",
        }
        res = client.options("/api/validate", headers=headers)
        assert res.status_code == 200
        assert res.headers.get("access-control-allow-origin") == origin
        assert res.headers.get("access-control-allow-credentials") == "true"


def test_cors_unauthorized_origin_rejected():
    """Verify unauthorized external origins do not receive CORS allow headers."""
    headers = {
        "Origin": "https://unauthorized-evil-domain.com",
        "Access-Control-Request-Method": "POST",
    }
    res = client.options("/api/validate", headers=headers)
    assert res.headers.get("access-control-allow-origin") != "https://unauthorized-evil-domain.com"


# -----------------------------------------------------------------------------
# 3. Frontend Asset Paths & Configurable API Base URL
# -----------------------------------------------------------------------------

def test_frontend_asset_paths_relative():
    """Verify static/index.html uses relative paths for scripts and no hardcoded production endpoints."""
    html_path = PROJECT_ROOT / "static" / "index.html"
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")

    # Script tag uses relative path
    assert '<script src="config.js">' in content
    # No hardcoded localhost API endpoints in client fetch calls
    assert "http://localhost:8000/api" not in content
    assert "http://127.0.0.1:8000/api" not in content
    # Helper for friendly error formatting and Render cold starts exists
    assert "function formatApiError" in content
    assert "isLocalHost" in content


def test_runtime_config_file_exists():
    """Verify static/config.js exists and defines window.APP_CONFIG with the deployed Render backend."""
    config_path = PROJECT_ROOT / "static" / "config.js"
    assert config_path.exists()
    content = config_path.read_text(encoding="utf-8")
    assert "window.APP_CONFIG" in content
    assert "API_BASE_URL" in content
    assert "https://ai-jcl-generator-api.onrender.com" in content


def test_api_config_and_settings_modal_in_html():
    """Verify static/index.html contains API_CONFIG, apiFetch, and the settings modal."""
    html_path = PROJECT_ROOT / "static" / "index.html"
    content = html_path.read_text(encoding="utf-8")
    assert "const API_CONFIG" in content
    assert "async function apiFetch" in content
    assert 'id="settingsModal"' in content
    assert 'id="settingApiBaseUrl"' in content
    assert 'id="settingAccessKey"' in content


# -----------------------------------------------------------------------------
# 4. Secret Protection & No Exposed Keys
# -----------------------------------------------------------------------------

def test_no_api_keys_exposed_in_responses():
    """Ensure /api/config and /health never expose API keys or secrets."""
    res_config = client.get("/api/config")
    assert res_config.status_code == 200
    config_data = res_config.json()
    assert "auth_required" in config_data
    # Ensure boolean flags are returned, not real keys
    assert isinstance(config_data["openai_configured"], bool)
    assert isinstance(config_data["gemini_configured"], bool)
    assert "OPENAI_API_KEY" not in config_data
    assert "GEMINI_API_KEY" not in config_data
    assert "STUDIO_API_KEY" not in config_data


def test_gitignore_excludes_secrets():
    """Verify .gitignore properly excludes .env, virtualenvs, and secrets."""
    gitignore_path = PROJECT_ROOT / ".gitignore"
    assert gitignore_path.exists()
    content = gitignore_path.read_text(encoding="utf-8")
    assert ".env" in content
    assert ".venv/" in content
    assert "__pycache__/" in content


# -----------------------------------------------------------------------------
# 5. Access Key Authentication on Paid AI Endpoints
# -----------------------------------------------------------------------------

def test_auth_required_when_studio_api_key_configured():
    """Verify paid AI endpoints reject requests without key when STUDIO_API_KEY is configured."""
    with patch.dict(os.environ, {"STUDIO_API_KEY": "secret-studio-passphrase-123"}):
        # 1. /api/generate without key -> 401
        res = client.post("/api/generate", json={"prompt": "Create JCL to copy dataset"})
        assert res.status_code == 401
        assert "Access key required" in res.json()["detail"]

        # 2. /api/generate with wrong key -> 401
        res_wrong = client.post(
            "/api/generate",
            json={"prompt": "Create JCL to copy dataset"},
            headers={"X-Studio-Access-Key": "wrong-key"}
        )
        assert res_wrong.status_code == 401

        # 3. /api/jcl/modify without key -> 401
        res_mod = client.post(
            "/api/jcl/modify",
            json={"jcl": "//JOB1 JOB (1)\n//STEP1 EXEC PGM=IEFBR14\n", "instruction": "Add DD"}
        )
        assert res_mod.status_code == 401

        # 4. /api/jcl/explain-error with use_ai=True without key -> 401
        res_err = client.post(
            "/api/jcl/explain-error",
            json={"log_text": "IEF450I PAYJOB STEP1 - ABEND=S806", "use_ai": True}
        )
        assert res_err.status_code == 401


def test_auth_success_with_valid_key():
    """Verify paid AI endpoints succeed when valid access key is provided via header."""
    mock_res = {
        "jcl": "//MOCKJOB JOB ...\n",
        "explanation": ["Mock explanation"],
        "assumptions": ["Mock assumption"],
        "warnings": [],
        "usage": TokenUsage(input_tokens=10, output_tokens=10, total_tokens=20, estimated_cost_usd=0.00001),
        "model": "gpt-5.4-mini",
    }

    with patch.dict(os.environ, {"STUDIO_API_KEY": "valid-token-xyz"}):
        with patch("main.generate_with_openai_provider", return_value=type("Obj", (), mock_res)()):
            # Test with X-Studio-Access-Key
            res = client.post(
                "/api/generate",
                json={"prompt": "Generate a test IEFBR14 JCL card", "provider": "openai"},
                headers={"X-Studio-Access-Key": "valid-token-xyz"}
            )
            assert res.status_code == 200

            # Test with Authorization: Bearer <token>
            res_bearer = client.post(
                "/api/generate",
                json={"prompt": "Generate a test IEFBR14 JCL card", "provider": "openai"},
                headers={"Authorization": "Bearer valid-token-xyz"}
            )
            assert res_bearer.status_code == 200


def test_deterministic_endpoints_unrestricted_without_key():
    """Verify free deterministic endpoints remain accessible even when STUDIO_API_KEY is active."""
    with patch.dict(os.environ, {"STUDIO_API_KEY": "secret-studio-passphrase-123"}):
        # 1. Static JCL Validate
        val_res = client.post("/api/jcl/validate", json={"jcl": "//JOB1 JOB (1)\n//STEP1 EXEC PGM=IEFBR14\n"})
        assert val_res.status_code == 200

        # 2. Manual Builder
        bld_res = client.post("/api/build", json={
            "job": {"job_name": "TESTJOB"},
            "steps": [{"step_name": "STEP1", "utility": "IEFBR14", "dds": []}]
        })
        assert bld_res.status_code == 200

        # 3. Preset Templates
        tmpl_res = client.get("/api/templates")
        assert tmpl_res.status_code == 200

        # 4. Error Explainer offline (use_ai=False)
        err_res = client.post("/api/jcl/explain-error", json={
            "log_text": "IEF450I PAYJOB STEP1 - ABEND=S806 U0000 REASON=00000004",
            "use_ai": False
        })
        assert err_res.status_code == 200
        assert err_res.json()["ai_used"] is False


# -----------------------------------------------------------------------------
# 6. Rate Limiting Tests
# -----------------------------------------------------------------------------

def test_rate_limiter_blocks_excessive_traffic():
    """Verify rate limiter triggers HTTP 429 when client exceeds requests per minute."""
    with patch.dict(os.environ, {"RATE_LIMIT_PER_MINUTE": "5"}):
        for i in range(5):
            res = client.get("/health")
            # Health endpoint does not enforce rate limit directly unless passed through middleware
            # Let's test on /api/validate which enforces rate_limiter
            res = client.post("/api/jcl/validate", json={"jcl": "//J JOB\n"})
            assert res.status_code == 200

        # 6th request should exceed limit
        res_blocked = client.post("/api/jcl/validate", json={"jcl": "//J JOB\n"})
        assert res_blocked.status_code == 429
        assert "Rate limit exceeded" in res_blocked.json()["detail"]
        assert "Retry-After" in res_blocked.headers


# -----------------------------------------------------------------------------
# 7. Daily Spend Limit Guardrail Tests
# -----------------------------------------------------------------------------

def test_daily_spend_limit_exceeded():
    """Verify AI endpoints block new calls with 429 when daily spending quota is reached."""
    with patch.dict(os.environ, {"DAILY_SPEND_LIMIT_USD": "0.05"}):
        # Artificially record spend that exceeds $0.05
        spend_tracker.record_cost(0.06)

        res = client.post("/api/generate", json={"prompt": "Generate a test IEFBR14 JCL card"})
        assert res.status_code == 429
        assert "Daily AI spending limit" in res.json()["detail"]


# -----------------------------------------------------------------------------
# 8. Render Blueprint & GitHub Actions Workflow Tests
# -----------------------------------------------------------------------------

def test_render_yaml_configuration():
    """Verify render.yaml contains required Blueprint configurations."""
    render_file = PROJECT_ROOT / "render.yaml"
    assert render_file.exists()
    content = render_file.read_text(encoding="utf-8")
    assert "type: web" in content
    assert "runtime: python" in content
    assert "uvicorn main:app" in content
    assert "--host 0.0.0.0" in content
    assert "healthCheckPath: /health" in content


def test_github_pages_workflow_configuration():
    """Verify .github/workflows/deploy-pages.yml exists and isolates static assets."""
    workflow_file = PROJECT_ROOT / ".github" / "workflows" / "deploy-pages.yml"
    assert workflow_file.exists()
    content = workflow_file.read_text(encoding="utf-8")
    assert "actions/upload-pages-artifact" in content
    assert "path: 'static'" in content
    assert "actions/deploy-pages" in content
