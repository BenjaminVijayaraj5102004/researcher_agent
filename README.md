# 🧠 Researcher AI — Vercel Deployment

Multi-agent AI system that generates IEEE research papers from any topic.
Frontend + Backend bundled into a single Vercel project.

---

## 📁 Project Structure

```
researcher-ai/
├── api/                    ← Python serverless functions (backend)
│   ├── __init__.py
│   ├── index.py            ← FastAPI app + Mangum (Vercel entry point)
│   ├── schemas.py          ← Pydantic data models
│   ├── main_agent.py       ← Orchestrator agent
│   ├── fetch_agent.py      ← Sub-Agent 1: web search & fetch
│   ├── writer_agent.py     ← Sub-Agent 2: IEEE paper writer
│   ├── review_agent.py     ← Sub-Agent 3: review & rewrite
│   └── database.py         ← Supabase integration
│
├── public/                 ← Static frontend (HTML/CSS/JS)
│   ├── index.html
│   ├── styles.css
│   └── app.js
│
├── vercel.json             ← Vercel routing config
├── requirements.txt        ← Python dependencies
├── .env.example            ← Environment variable template
└── README.md
```

---

## 🚀 Deploy to Vercel in 5 Steps

### Step 1 — Get Your API Keys

| Service | URL | Free Tier |
|---------|-----|-----------|
| **Groq** | [console.groq.com](https://console.groq.com) | 30 req/min |
| **Serper** | [serper.dev](https://serper.dev) | 2,500 searches/mo |
| **Supabase** | [supabase.com](https://supabase.com) | 500MB database |

---

### Step 2 — Push to GitHub

```bash
# In the researcher-ai/ folder:
git init
git add .
git commit -m "Initial commit"

# Create a repo on github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/researcher-ai.git
git push -u origin main
```

---

### Step 3 — Import to Vercel

1. Go to [vercel.com/new](https://vercel.com/new)
2. Click **"Import Git Repository"**
3. Select your `researcher-ai` repo
4. Leave all build settings as default — Vercel auto-detects via `vercel.json`
5. Click **"Deploy"** (first deploy will fail — that's OK, we add env vars next)

---

### Step 4 — Add Environment Variables

In Vercel dashboard → your project → **Settings** → **Environment Variables**:

| Name | Value |
|------|-------|
| `GROQ_API_KEY` | `gsk_your_key_here` |
| `SERPER_API_KEY` | `your_key_here` |
| `SUPABASE_URL` | `https://xxx.supabase.co` *(optional)* |
| `SUPABASE_KEY` | `your_anon_key` *(optional)* |

Set all three environments: **Production**, **Preview**, **Development**.

Then go to **Deployments** → click the three dots on the latest → **Redeploy**.

---

### Step 5 — Set Up Supabase Schema (Optional)

Go to your Supabase project → **SQL Editor** → run:

```sql
CREATE TABLE research_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    fetch_output JSONB,
    writer_output JSONB,
    review_output JSONB,
    final_paper TEXT,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT valid_status CHECK (
        status IN ('pending','fetching','writing','reviewing','completed','failed')
    )
);

CREATE INDEX idx_research_sessions_created_at ON research_sessions(created_at DESC);

ALTER TABLE research_sessions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all for development"
    ON research_sessions FOR ALL
    USING (true) WITH CHECK (true);
```

---

## 🖥️ Local Development

```bash
# Install Python dependencies
pip install -r requirements.txt

# Copy env file and fill in keys
cp .env.example .env
# edit .env with your keys

# Run locally with Vercel CLI (recommended)
npm i -g vercel
vercel dev

# Or run backend directly
cd api
uvicorn index:app --reload --port 8000
# Then open public/index.html in browser
```

---

## 🔗 API Endpoints

Once deployed, all endpoints are available at `https://your-app.vercel.app`:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/research/start` | Start research → get stream ID |
| `GET` | `/api/research/stream/{id}` | SSE live progress |
| `POST` | `/api/research/generate` | Sync generate (waits for result) |
| `GET` | `/api/research/result/{id}` | Get completed result |
| `GET` | `/api/research/history` | Research history |
| `GET` | `/api/docs` | Interactive API docs |

---

## ⚡ Agent Workflow

```
User Topic
    │
    ▼
Main Agent (Orchestrator)
    │
    ├─► Sub-Agent 1: Fetch
    │       Serper search → scrape pages → Groq LLM extracts facts
    │
    ├─► Sub-Agent 2: Writer
    │       Groq LLM writes full IEEE paper from structured facts
    │
    └─► Sub-Agent 3: Review
            Plagiarism check → alignment check → Groq LLM rewrites → quality score
    │
    ▼
Final IEEE Paper (stored in Supabase)
```

---

## ❗ Troubleshooting

**Deployment fails with "Function too large"**
→ Ensure `__pycache__/` is in `.gitignore` and not committed.

**`500 Internal Server Error` on API calls**
→ Check Environment Variables are set correctly in Vercel dashboard.
→ Check Function Logs: Vercel dashboard → Deployments → Functions → Logs.

**Health check shows `groq: false`**
→ Your `GROQ_API_KEY` isn't set. Re-add it in Vercel env vars and redeploy.

**SSE stream stops early on Vercel**
→ Vercel serverless functions have a max execution time of 60s (Pro: 300s).
→ Use **Sync mode** on the frontend for complex topics, or upgrade to Vercel Pro.

**History shows empty on Supabase**
→ Make sure you ran the SQL schema above.
→ Check the `SUPABASE_URL` doesn't have a trailing slash.
→ Verify `SUPABASE_KEY` is the **anon** key (not the service role key).
