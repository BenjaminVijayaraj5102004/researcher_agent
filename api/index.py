"""
Vercel Serverless Entry Point
Uses Mangum to wrap FastAPI for AWS Lambda / Vercel serverless functions
"""
import os
import json
import uuid
import logging
import asyncio
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from mangum import Mangum

from api.schemas import ResearchRequest, ResearchStatus
from api.main_agent import MainAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Researcher AI — Multi-Agent System",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single global agent instance (lives for duration of warm lambda)
_agent: MainAgent = None


def get_agent() -> MainAgent:
    global _agent
    if _agent is None:
        _agent = MainAgent()
        logger.info("MainAgent initialized")
    return _agent


# ── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
@app.get("/api/health")
async def health():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "agents": {"main": "active", "fetch": "active", "writer": "active", "review": "active"},
        "services": {
            "groq": bool(os.getenv("GROQ_API_KEY")),
            "serper": bool(os.getenv("SERPER_API_KEY")),
            "supabase": bool(os.getenv("SUPABASE_URL"))
        }
    }


# ── Start (returns ID for SSE stream) ────────────────────────────────────────

@app.post("/api/research/start")
async def start_research(request: ResearchRequest):
    agent = get_agent()
    research_id = str(uuid.uuid4())
    agent._pending_requests = getattr(agent, "_pending_requests", {})
    agent._pending_requests[research_id] = request
    return {
        "research_id": research_id,
        "topic": request.topic,
        "status": "pending",
        "stream_url": f"/api/research/stream/{research_id}",
        "result_url": f"/api/research/result/{research_id}",
        "message": "Connect to stream_url for live progress updates."
    }


# ── SSE Stream ────────────────────────────────────────────────────────────────

@app.get("/api/research/stream/{research_id}")
async def stream_research(research_id: str):
    agent = get_agent()
    pending = getattr(agent, "_pending_requests", {})
    request = pending.get(research_id)

    if not request:
        raise HTTPException(status_code=404, detail="Research task not found or already started.")

    async def event_gen():
        try:
            async for progress in agent.execute_research(request):
                data = progress.model_dump()
                yield f"data: {json.dumps(data)}\n\n"
                await asyncio.sleep(0.05)
                if progress.status in [ResearchStatus.COMPLETED, ResearchStatus.FAILED]:
                    yield f"data: {json.dumps({'type': 'done', 'research_id': research_id})}\n\n"
                    break
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            pending.pop(research_id, None)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
    )


# ── Synchronous generate (single request, waits for result) ──────────────────

@app.post("/api/research/generate")
async def generate_research(request: ResearchRequest):
    agent = get_agent()
    try:
        last_progress = None
        async for progress in agent.execute_research(request):
            last_progress = progress
            logger.info(f"  {progress.progress_percentage}% — {progress.message}")

        if last_progress:
            result = agent.get_result(last_progress.research_id)
            if result:
                return result.model_dump()

        raise HTTPException(status_code=500, detail="Research generation failed.")
    except Exception as e:
        logger.error(f"Generate error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ── Result ────────────────────────────────────────────────────────────────────

@app.get("/api/research/result/{research_id}")
async def get_result(research_id: str):
    agent = get_agent()
    result = agent.get_result(research_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found or not yet complete.")
    return result.model_dump()


# ── Progress ──────────────────────────────────────────────────────────────────

@app.get("/api/research/progress/{research_id}")
async def get_progress(research_id: str):
    agent = get_agent()
    progress = agent.get_progress(research_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Progress not found.")
    return progress.model_dump()


# ── History ───────────────────────────────────────────────────────────────────

@app.get("/api/research/history")
async def get_history():
    agent = get_agent()
    records = await agent.get_all_research()
    return {"records": records, "total": len(records)}


# ── Root ──────────────────────────────────────────────────────────────────────

@app.get("/")
@app.get("/api")
async def root():
    return {
        "name": "Researcher AI — Multi-Agent System",
        "version": "1.0.0",
        "docs": "/api/docs",
        "health": "/api/health"
    }


# ── Vercel / Lambda handler ───────────────────────────────────────────────────
handler = Mangum(app, lifespan="off")
