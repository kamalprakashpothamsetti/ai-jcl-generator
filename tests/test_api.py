import pytest
from fastapi.testclient import TestClient
import main
from llm_provider import TokenUsage, estimate_openai_cost

client = TestClient(main.app)
SAMPLE = "//MYJOB JOB (ACCT),'TEST',CLASS=A,MSGCLASS=X\n//STEP01 EXEC PGM=IEFBR14\n//OUTDD DD DSN=USER.TEST,DISP=SHR"

def test_home():
    assert client.get('/').status_code == 200

def test_validate_good():
    response = client.post('/api/validate', json={'jcl': SAMPLE})
    assert response.status_code == 200
    assert response.json()['passed_basic_checks'] is True
    assert 'issues' in response.json()
    assert 'summary' in response.json()
    assert 'disclaimer' in response.json()

def test_validate_missing_exec():
    response = client.post('/api/validate', json={'jcl': '//MYJOB JOB (ACCT)\n'})
    assert any('EXEC' in w for w in response.json()['warnings'])

def test_validate_long_line():
    response = client.post('/api/validate', json={'jcl': SAMPLE + '\n//*' + 'X' * 90})
    assert any('80 columns' in w for w in response.json()['warnings'])

def test_generate_mocked(monkeypatch):
    """Verifies backward compatibility with tests monkeypatching generate_with_gemini."""
    def fake_generate(request):
        return main.GenerateResponse(
            jcl=SAMPLE,
            explanation=['Creates a step'],
            assumptions=[],
            warnings=[],
            provider='gemini',
            model='gemini-2.5-flash'
        )
    monkeypatch.setattr(main, 'generate_with_gemini', fake_generate)
    response = client.post('/api/generate', json={'prompt': 'Create a sample dataset allocation job', 'utility': 'IEFBR14'})
    assert response.status_code == 200
    assert 'IEFBR14' in response.json()['jcl']
    assert isinstance(response.json()['explanation'], list)

def test_generate_openai_mocked(monkeypatch):
    """Verifies default OpenAI generation with token usage and cost estimation."""
    def fake_openai(request):
        usage = TokenUsage(
            input_tokens=150,
            output_tokens=320,
            total_tokens=470,
            estimated_cost_usd=estimate_openai_cost("gpt-5.4-mini", 150, 320),
            provider="openai",
            model="gpt-5.4-mini"
        )
        return main.GenerateResponse(
            jcl=SAMPLE,
            explanation=['OpenAI generated step'],
            assumptions=['Assumed DASD storage'],
            warnings=[],
            usage=usage,
            provider="openai",
            model="gpt-5.4-mini"
        )
    monkeypatch.setattr(main, 'generate_with_openai', fake_openai)
    response = client.post(
        '/api/generate',
        json={'prompt': 'Generate sequential dataset copy using IEBGENER', 'utility': 'IEBGENER', 'provider': 'openai'}
    )
    assert response.status_code == 200
    data = response.json()
    assert data['provider'] == 'openai'
    assert data['model'] == 'gpt-5.4-mini'
    assert data['usage']['input_tokens'] == 150
    assert data['usage']['output_tokens'] == 320
    assert data['usage']['estimated_cost_usd'] > 0

def test_generate_provider_selection(monkeypatch):
    """Verifies that the request can explicitly select Gemini or OpenAI."""
    def fake_openai(request):
        return main.GenerateResponse(jcl=SAMPLE, explanation=[], assumptions=[], warnings=[], provider="openai", model="gpt-5.4-mini")
    def fake_gemini(request):
        return main.GenerateResponse(jcl=SAMPLE, explanation=[], assumptions=[], warnings=[], provider="gemini", model="gemini-2.5-flash")

    monkeypatch.setattr(main, 'generate_with_openai', fake_openai)
    monkeypatch.setattr(main, 'generate_with_gemini', fake_gemini)

    r_openai = client.post('/api/generate', json={'prompt': 'Test prompt with at least 10 chars', 'provider': 'openai'})
    assert r_openai.status_code == 200
    assert r_openai.json()['provider'] == 'openai'

    r_gemini = client.post('/api/generate', json={'prompt': 'Test prompt with at least 10 chars', 'provider': 'gemini'})
    assert r_gemini.status_code == 200
    assert r_gemini.json()['provider'] == 'gemini'

def test_generate_rate_limit_error(monkeypatch):
    """Verifies that OpenAI RateLimitError is converted to HTTP 429."""
    class FakeRateLimitError(Exception):
        pass
    def fake_openai_rate_limited(request):
        raise FakeRateLimitError("RateLimitError: quota exceeded")
    monkeypatch.setattr(main, 'generate_with_openai', fake_openai_rate_limited)

    response = client.post('/api/generate', json={'prompt': 'Test prompt with at least 10 chars', 'provider': 'openai'})
    assert response.status_code == 429
    assert "rate limit or quota" in response.json()['detail'].lower()

def test_generate_timeout_error(monkeypatch):
    """Verifies that OpenAI timeout is converted to HTTP 504."""
    class FakeTimeoutError(Exception):
        pass
    def fake_openai_timeout(request):
        raise FakeTimeoutError("APITimeoutError: Request timed out")
    monkeypatch.setattr(main, 'generate_with_openai', fake_openai_timeout)

    response = client.post('/api/generate', json={'prompt': 'Test prompt with at least 10 chars', 'provider': 'openai'})
    assert response.status_code == 504
    assert "timed out" in response.json()['detail'].lower()

def test_generate_auth_error(monkeypatch):
    """Verifies that invalid API key is converted to HTTP 401."""
    class FakeAuthError(Exception):
        pass
    def fake_openai_auth(request):
        raise FakeAuthError("AuthenticationError: Incorrect API key provided")
    monkeypatch.setattr(main, 'generate_with_openai', fake_openai_auth)

    response = client.post('/api/generate', json={'prompt': 'Test prompt with at least 10 chars', 'provider': 'openai'})
    assert response.status_code == 401
    assert "authentication failed" in response.json()['detail'].lower()

def test_cost_calculation():
    # 1,000,000 input tokens at $0.15 + 1,000,000 output tokens at $0.60 = $0.75
    cost = estimate_openai_cost("gpt-5.4-mini", 1_000_000, 1_000_000)
    assert abs(cost - 0.75) < 1e-5

    # 1,000 in, 500 out
    cost_small = estimate_openai_cost("gpt-5.4-mini", 1000, 500)
    expected = (1000 * 0.15 + 500 * 0.60) / 1_000_000
    assert abs(cost_small - expected) < 1e-6

def test_config_endpoint():
    response = client.get('/api/config')
    assert response.status_code == 200
    data = response.json()
    assert 'provider' in data
    assert 'openai_model' in data
    assert 'openai_configured' in data

def test_short_prompt_rejected():
    response = client.post('/api/generate', json={'prompt': 'sort'})
    assert response.status_code == 422

def test_get_templates():
    response = client.get('/api/templates')
    assert response.status_code == 200
    data = response.json()
    assert 'IEFBR14_ALLOCATE' in data
    assert 'IEBGENER_COPY' in data
    assert 'DFSORT_SORT' in data
    assert 'IDCAMS_DEFINE_CLUSTER' in data

def test_build_manual_endpoint():
    payload = {
        "job": {
            "job_name": "APIJOB01",
            "accounting": "(ACCT#777)",
            "programmer_name": "'DEV'",
            "job_class": "A",
            "msgclass": "X"
        },
        "steps": [
            {
                "step_name": "STEP01",
                "utility": "IEBGENER",
                "dds": [
                    {"dd_name": "SYSUT1", "dsn": "USER.IN", "disp": "SHR"},
                    {"dd_name": "SYSUT2", "dsn": "USER.OUT", "disp": "(NEW,CATLG,DELETE)", "space": "(CYL,(1,1))"},
                    {"dd_name": "SYSPRINT", "sysout": "*"},
                    {"dd_name": "SYSIN", "dummy": True}
                ]
            }
        ]
    }
    response = client.post('/api/build', json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "//APIJOB01 JOB  " in data['jcl']
    assert "EXEC PGM=IEBGENER" in data['jcl']
    assert data['passed_basic_checks'] is True
    assert 'disclaimer' in data
