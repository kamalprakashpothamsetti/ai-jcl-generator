from fastapi.testclient import TestClient
import main

client = TestClient(main.app)

def test_app_endpoints_and_html_ids():
    # 1. Test GET /
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    required_ids = [
        "prompt", "utility", "generate", "status", "output", "validate",
        "copy", "download", "validation", "explanation", "notes",
        "tabAiMode", "tabManualMode", "buildManual"
    ]
    for rid in required_ids:
        assert f'id="{rid}"' in html or f"id='{rid}'" in html, f"Missing ID: {rid}"

    # 2. Test GET /api/templates
    t = client.get("/api/templates")
    assert t.status_code == 200
    templates = t.json()
    assert "IEFBR14_ALLOCATE" in templates
    assert "IEBGENER_COPY" in templates
    assert "DFSORT_SORT" in templates
    assert "IDCAMS_DEFINE_CLUSTER" in templates

    # 3. Test POST /api/build
    tmpl = templates["IEFBR14_ALLOCATE"]["request"]
    b = client.post("/api/build", json=tmpl)
    assert b.status_code == 200
    build_data = b.json()
    assert build_data["passed_basic_checks"] is True
    assert "ALLOCJOB" in build_data["jcl"]
    assert "IEFBR14" in build_data["jcl"]

    # 4. Test POST /api/validate
    v = client.post("/api/validate", json={"jcl": build_data["jcl"]})
    assert v.status_code == 200
    val_data = v.json()
    assert val_data["passed_basic_checks"] is True
    assert len(val_data["warnings"]) == 0
