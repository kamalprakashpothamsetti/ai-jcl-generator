# AI Mainframe JCL Studio (FastAPI + OpenAI & Gemini)

An intelligent IBM z/OS JCL generator, visual builder, and static syntax validator powered by OpenAI (default) and Google Gemini (optional). Generated code is illustrative and must be reviewed in a non-production z/OS test environment before execution.

## Setup (Windows PowerShell / Antigravity Terminal)

1. Open this repository in Antigravity or your terminal:
2. Activate your virtual environment and install dependencies:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and set your API keys:
   ```powershell
   Copy-Item .env.example .env
   ```
   Configure `.env`:
   ```env
   # Provider: 'openai' (default) or 'gemini'
   LLM_PROVIDER=openai

   # OpenAI Configuration (Default provider)
   OPENAI_API_KEY=your_openai_api_key_here
   OPENAI_MODEL=gpt-5.4-mini

   # Google Gemini Configuration (Optional provider)
   GEMINI_API_KEY=your_gemini_api_key_here
   GEMINI_MODEL=gemini-3.8-flash
   ```
4. Start the application:
   ```powershell
   uvicorn main:app --reload
   ```
5. Open your browser at `http://127.0.0.1:8000`.
6. Run automated test suite:
   ```powershell
   pytest -q
   ```
   *(All tests run hermetically using mocked responses without spending API credits).*

## Key Features

- **Multi-Provider LLM Integration**:
  - **OpenAI (Default)**: Uses official `openai` Python SDK and the Responses API with structured JSON output schema and `gpt-5.4-mini`.
  - **Google Gemini (Optional)**: Uses official `google-genai` SDK with structured schema.
  - **Configurable**: Switch providers seamlessly via `LLM_PROVIDER=openai` in `.env` or select dynamically per request.
  - **Token Tracking & Cost Estimation**: Automatically logs input, output, and total tokens and estimates OpenAI API cost in USD.
  - **Robust Error Handling**: Captures rate limits (429), timeouts (504), auth failures (401), and connectivity issues (502) with sanitized error messages.
- **Dual Studio Modes**:
  - **AI Prompt Generator**: Natural-language prompts to compliant JCL with 1-click prompt presets for common mainframe jobs.
  - **Manual Visual Builder**: Step-by-step card builder with custom JOB parameters, step managers, utility-specific DD presets, and in-stream control card editors.
- **Supported IBM Utilities**:
  - `IEFBR14`: Dataset allocation and deletion on DASD with SPACE checking.
  - `IEBGENER`: Sequential copy with SYSUT1, SYSUT2, SYSPRINT, SYSIN verification.
  - `DFSORT`: High-performance sorting, filtering, and merging with SORTIN, SORTOUT, SYSOUT, SORTWK, and SYSIN control cards.
  - `IDCAMS`: VSAM cluster definitions (KSDS, ESDS, RRDS), REPRO copy, and delete services.
- **Static JCL Validation Engine (`backend/validation/`)**:
  - `parser.py`: Physical-line parsing, logical statement assembly, column 71/72/73-80 conventions, continuation syntax, quoted strings, and in-stream delimiter tracking (`DD *`, `DD DATA`, `DLM=xx`).
  - `rules.py`: General JCL structure, duplicate step names, duplicate DD names within steps (while preserving valid unnamed concatenations), DISP syntax, SPACE parameters, DCB parameters (RECFM/LRECL/BLKSIZE divisibility), and DSN naming conventions (supporting GDGs, PDS members, temporary datasets, and symbolic qualifiers).
  - `utilities.py`: Utility-specific rules:
    - `IEFBR14`: No SYSPRINT/SYSIN required; SPACE validation on NEW dataset allocation.
    - `IEBGENER`: Requires SYSUT1, SYSUT2, SYSPRINT, SYSIN (allowing DUMMY or in-stream).
    - `DFSORT`: Requires SORTIN, SORTOUT (or OUTFIL alternatives), SYSOUT, SYSIN; validates `SORT FIELDS=(start,len,fmt,ord)` and boundary check against known LRECL.
    - `IDCAMS`: Requires SYSPRINT, SYSIN; supports DEFINE CLUSTER, DELETE, REPRO (validating INFILE/OUTFILE DD references), and LISTCAT.
  - `validator.py`: Orchestrator returning `ValidationResult` with error, warning, and info counts, line/column coordinates, rule IDs, and suggested fixes.
- **Validation & Modification Endpoints**:
  - `POST /api/jcl/modify`: Conversational JCL editing endpoint returning `{ original_jcl, modified_jcl, summary, changes, diff_lines, validation, original_validation, new_errors_introduced, usage }`.
  - `POST /api/jcl/validate`: Primary structured diagnostics endpoint returning `{ valid, validation_level: "static", executable_verified: false, diagnostics, counts, disclaimer }`.
  - `POST /api/validate`: Backward-compatible validation endpoint.
- **Hybrid JCL Studio UI**:
  - **Conversational AI Edit Mode**: Natural-language modification input with quick-edit chips (e.g. change sort order, add secondary sort key, modify SPACE, change DISP), server-side diff viewer with line numbers and color-coded changes (+ additions / - removals), validation error warnings on proposed JCL, stale proposal detection, apply with undo protection, and discard controls.
  - **3-Column Desktop Layout**: Left column (AI prompt / Manual card builder / AI edit), Center column (Shared JCL code editor), Right column (Static validation & explanation/assumptions inspector).
  - **Mobile Responsive Layout**: Tabbed navigation switching between Generator, Editor, and Validation panels on screens below 1100px.
  - **Dark / Light Theme**: Professional theme toggle with high-contrast accessible styling, persisting user preference.
  - **Shared JCL Code Studio**:
    - Line-numbered synchronized gutter with clickable line navigation.
    - 80-column visual guide boundary line and real-time overflow detector.
    - Full Undo (`↩️`) and Redo (`↪️`) history stack.
    - Unsaved-changes awareness badge (`● Saved` vs `● Unsaved edits`) with overwrite protection confirmation dialogs.
    - One-click copy exact JCL, download as `.jcl`, format uppercase, and clear editor.
  - **AI Generator Mode**:
    - Pre-configured quick-start templates for `IEFBR14` (allocate), `IEBGENER` (copy), `DFSORT` (sort ascending), and `IDCAMS` (define KSDS).
    - Client-side and server-side minimum prompt validation (<10 chars).
    - Duplicate submission prevention and loading spinners.
  - **Manual Visual Card Builder**:
    - Complete JOB card configuration (`JOBNAME`, `ACCT`, `PROGRAMMER`, `CLASS`, `MSGCLASS`, `MSGLEVEL`, `NOTIFY`, `REGION`).
    - Complete EXEC step configuration (`STEPNAME`, `UTILITY`, `PGM Override`, `PARM`, `REGION`, `COND`, `Comments`).
    - DD statement configuration (`DSN`, `DISP`, `UNIT`, `SPACE`, `RECFM`, `LRECL`, `BLKSIZE`, `SYSOUT`, `DUMMY`, `In-stream SYSIN` with `DLM`).
    - Interactive DD statement management with reordering (`⬆️ Move Up`, `⬇️ Move Down`), deletion, and auto-population.
  - **Real-Time Static Validation & Stale Tracking**:
    - Real-time debounced syntax checks against `POST /api/jcl/validate`.
    - Immediate `⚠️ Stale (Editing...)` marking upon keystrokes until debounced validation finishes.
    - Filterable diagnostics by severity (`All`, `Errors`, `Warnings`, `Info`) with clickable line jumps (`goToLine`) and suggested fixes.
  - **Explanation & Assumptions Inspector**:
    - Dedicated panels displaying statement-by-statement utility breakdown, LLM assumptions, and environment prerequisites without requiring extra API credits.
- **Security & Safety**:
  - API keys stay strictly on the server and are never exposed to frontend code or client network payloads.
  - Studio Access Key (`STUDIO_API_KEY`) authentication protects paid AI endpoints from public abuse.
  - In-memory sliding-window rate limiter prevents request floods.
  - Daily spending ceiling (`DAILY_SPEND_LIMIT_USD`) guards against cloud LLM credit exhaustion.
  - Illustrative disclaimer banner included in generated JCL comment headers, validation responses, and UI badges.

---

## Production Deployment (GitHub Pages + Render)

JCL Studio AI is engineered for a decoupled cloud architecture:
- **Frontend**: Static single-page application hosted globally on **GitHub Pages**.
- **Backend**: High-performance FastAPI service hosted on **Render** (Python 3.11/3.13).

```mermaid
graph LR
    User[User Browser]
    GH[GitHub Pages<br/>Static Assets & config.js]
    Render[Render Web Service<br/>FastAPI Backend]
    LLM[OpenAI / Gemini APIs]

    User -->|1. Load UI| GH
    User -->|2. API Calls (HTTPS + CORS)| Render
    Render -->|3. JCL Validation & Manual Builder| Render
    Render -->|4. Authenticated AI Requests| LLM
```

---

### 1. Backend Deployment: Render Web Service

#### Method A: Render Blueprint (Recommended)
The repository includes a production-ready [`render.yaml`](file:///render.yaml):
1. Push your repository to GitHub.
2. Sign in to your [Render Dashboard](https://dashboard.render.com).
3. Click **New +** -> **Blueprint**.
4. Select your `ai-jcl-generator-gemini` repository.
5. Render detects [`render.yaml`](file:///render.yaml) and creates the `jcl-studio-ai-backend` web service.
6. Under the service **Environment Variables**, provide your secret keys:
   - `OPENAI_API_KEY`: Your production OpenAI secret key (`sk-...`).
   - `STUDIO_API_KEY`: A strong random token (e.g., `openssl rand -hex 24`) used to authorize paid AI requests from authorized studio users.
   - `ALLOWED_ORIGINS`: Your GitHub Pages URL (e.g., `https://your-username.github.io`).
7. Click **Apply**. Render will install requirements, run health checks against `/health`, and deploy your backend to `https://jcl-studio-ai-backend.onrender.com`.

#### Method B: Manual Web Service Setup
1. In Render, select **New +** -> **Web Service**.
2. Connect your GitHub repository.
3. Configure settings:
   - **Name**: `jcl-studio-ai-backend`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Health Check Path**: `/health`
4. Add the required environment variables (see table below).
5. Deploy service.

---

### 2. Frontend Deployment: GitHub Pages

The frontend is completely static and located in the [`static/`](file:///static/) folder.

#### Automated Deployment with GitHub Actions
The repository includes [`.github/workflows/deploy-pages.yml`](file:///.github/workflows/deploy-pages.yml).
1. Go to your GitHub repository -> **Settings** -> **Pages**.
2. Under **Build and deployment** -> **Source**, select **GitHub Actions**.
3. In your local repository or via GitHub web interface, edit [`static/config.js`](file:///static/config.js) to set your Render backend URL:
   ```javascript
   window.APP_CONFIG = {
     API_BASE_URL: "https://your-service-name.onrender.com"
   };
   ```
4. Push your changes to the `main` branch.
5. The GitHub Action will automatically:
   - Verify backend source code and `.env` files are excluded.
   - Upload *only* the `static/` directory as Pages artifact.
   - Publish your site to `https://<YOUR-USERNAME>.github.io/<REPO-NAME>/`.

#### Runtime API & Access Key Configuration via UI
Users can also configure or override the backend URL and Studio Access Key directly from the browser without modifying code:
1. Click the **⚙️ Settings** icon in the header.
2. Enter your Render backend URL (e.g., `https://your-backend.onrender.com`).
3. Enter your **Studio Access Key** (matches `STUDIO_API_KEY` on Render).
4. Click **Test Connection** to verify end-to-end connectivity and latency.
5. Click **Save Settings** (persisted securely in browser `localStorage`).

---

### 3. Environment Variables Reference

| Variable | Required in Production | Default | Purpose |
| :--- | :--- | :--- | :--- |
| `LLM_PROVIDER` | No | `openai` | Active AI provider (`openai` or `gemini`). |
| `OPENAI_API_KEY` | Yes (if OpenAI used) | — | OpenAI secret API key. Never exposed to clients. |
| `OPENAI_MODEL` | No | `gpt-5.4-mini` | OpenAI model identifier. |
| `GEMINI_API_KEY` | Optional | — | Google Gemini API key. |
| `GEMINI_MODEL` | No | `gemini-3.8-flash` | Gemini model identifier. |
| `ALLOWED_ORIGINS` | Yes | `*` | Comma-separated list of allowed frontend origins (e.g. `https://username.github.io`). |
| `STUDIO_API_KEY` | Recommended | *(disabled)* | Shared studio access key required for AI generation and conversational editing. |
| `RATE_LIMIT_PER_MINUTE`| No | `60` | Max requests per IP per minute across API endpoints. |
| `DAILY_SPEND_LIMIT_USD`| No | `15.0` | Maximum estimated daily LLM spend before AI endpoints return 429. |
| `ENVIRONMENT` | Recommended | `development` | Set to `production` to disable `/docs` and debug outputs. |
| `DOCS_ENABLED` | No | `true` | Explicitly toggle FastAPI Swagger UI (`/docs`, `/redoc`). |
| `PORT` | Auto-set by Render | `8000` | Port for the uvicorn web server. |
| `HOST` | No | `0.0.0.0` | Binding host address. |

---

### 4. Security & Public API Protections

- **Secret Isolation**: All API keys (`OPENAI_API_KEY`, `GEMINI_API_KEY`) exist solely in the server environment. The frontend only communicates with your backend.
- **Studio Access Key Authentication**: Protects high-cost AI endpoints (`/api/generate`, `/api/jcl/modify`, `/api/jcl/explain-error`) via `X-Studio-Access-Key` or `Authorization: Bearer <key>` headers.
- **Unrestricted Deterministic Endpoints**: Static syntax validation (`/api/jcl/validate`), manual visual building, and system health checks (`/health`) remain fast, free, and unrestricted.
- **Sliding-Window Rate Limiting**: In-memory rate limiting tracks requests per client IP to mitigate abusive scraping or denial-of-service traffic.
- **Daily Spending Guardrail**: Tracks estimated token costs across all requests. Once the daily ceiling is reached, AI endpoints gracefully return `429 Too Many Requests` with a descriptive message to prevent unexpected bills.
- **Payload Size Limits**: Request bodies are capped (128 KB for AI prompts, 512 KB for JCL inputs) to block memory exhaustion attacks.
- **Strict CORS Policy**: In production, `ALLOWED_ORIGINS` must specify your exact GitHub Pages origin (e.g. `https://username.github.io`). Wildcard CORS (`*`) with credentials is explicitly prohibited.

---

### 5. Verification & Testing

Before deploying, run the hermetic test suite:
```powershell
pytest
```
All 166 unit and integration tests run hermetically using mocked API responses with zero API spending.

To verify deployment configurations specifically:
```powershell
pytest tests/test_deployment_security.py -v
```

#### Post-Deployment Smoke Test Checklist
1. **Health Check**: Open `https://<YOUR-RENDER-APP>.onrender.com/health` in your browser. Verify `{"status": "ok", "service": "jcl-studio-ai"}`.
2. **CORS Check**: Check response headers on `OPTIONS https://<YOUR-RENDER-APP>.onrender.com/health` with `Origin: https://<YOUR-USERNAME>.github.io` to ensure `Access-Control-Allow-Origin` matches.
3. **Frontend Asset Load**: Navigate to your GitHub Pages URL `https://<YOUR-USERNAME>.github.io/<REPO-NAME>/`. Ensure all stylesheets, SVG icons, and `config.js` load with HTTP 200 without subpath 404s.
4. **Settings Modal**: Open Settings, input your Render URL and Studio Key, and click **Test Connection**. Verify green status badge.
5. **Static Validation**: Paste sample JCL into the editor and confirm immediate, line-aware validation diagnostics without errors.
6. **AI Features**: Run an AI generation or AI edit and confirm successful JCL generation.

---

## Notes & Disclaimers

- Generated JCL is illustrative and must be validated in an actual z/OS mainframe test environment before production execution.
- Static validation checks syntax, card-image length, continuation rules, and utility DD requirements. It does NOT guarantee z/OS JES execution success or live catalog resource availability.
