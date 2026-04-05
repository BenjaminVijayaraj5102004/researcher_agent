import uuid
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, AsyncGenerator

from api.schemas import (
    ResearchRequest, ResearchResponse, ResearchStatus, ResearchProgress
)
from api.fetch_agent import FetchAgent
from api.writer_agent import WriterAgent
from api.review_agent import ReviewAgent
from api.database import DatabaseManager

logger = logging.getLogger(__name__)


class ResearchRecord:
    """Simple record object for database saves."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class MainAgent:
    def __init__(self):
        self.fetch_agent = FetchAgent()
        self.writer_agent = WriterAgent()
        self.review_agent = ReviewAgent()
        self.db = DatabaseManager()
        self._progress_store: dict = {}
        self._result_store: dict = {}

    def _make_progress(self, research_id, status, step, pct, message) -> ResearchProgress:
        existing = self._progress_store.get(research_id)
        logs = (existing.logs if existing else []) + [f"[{step}] {message}"]
        p = ResearchProgress(
            research_id=research_id, status=status,
            current_step=step, progress_percentage=pct,
            message=message, logs=logs
        )
        self._progress_store[research_id] = p
        return p

    async def execute_research(self, request: ResearchRequest) -> AsyncGenerator[ResearchProgress, None]:
        research_id = str(uuid.uuid4())

        yield self._make_progress(research_id, ResearchStatus.PENDING, "Initializing", 5,
                                   f"Starting research pipeline for: '{request.topic}'")

        rec = ResearchRecord(
            id=research_id, topic=request.topic,
            status=ResearchStatus.PENDING,
            created_at=datetime.now(timezone.utc).isoformat()
        )
        await self.db.save_research(rec)

        fetch_output = writer_output = review_output = None
        error = None

        try:
            yield self._make_progress(research_id, ResearchStatus.FETCHING, "Sub-Agent 1: Fetch",
                                       15, f"Searching the web for '{request.topic}'...")
            fetch_output = await self.fetch_agent.run(request.topic, request.max_sources)
            yield self._make_progress(research_id, ResearchStatus.FETCHING, "Sub-Agent 1: Fetch",
                                       35, f"Gathered {fetch_output.total_sources} sources, {len(fetch_output.key_facts)} key facts.")
            await self.db.update_research(research_id, {"status": ResearchStatus.FETCHING, "fetch_output": fetch_output.model_dump()})

            yield self._make_progress(research_id, ResearchStatus.WRITING, "Sub-Agent 2: Writer",
                                       45, "Writing IEEE-format research paper...")
            writer_output = await self.writer_agent.run(fetch_output)
            yield self._make_progress(research_id, ResearchStatus.WRITING, "Sub-Agent 2: Writer",
                                       65, f"Paper written: {writer_output.word_count} words, {len(writer_output.sections)} sections.")
            await self.db.update_research(research_id, {"status": ResearchStatus.WRITING, "writer_output": writer_output.model_dump()})

            yield self._make_progress(research_id, ResearchStatus.REVIEWING, "Sub-Agent 3: Review",
                                       75, "Reviewing alignment, checking originality, improving paper...")
            review_output = await self.review_agent.run(writer_output)
            yield self._make_progress(research_id, ResearchStatus.REVIEWING, "Sub-Agent 3: Review",
                                       90, f"Review complete. Quality: {review_output.quality_score:.1f}/10. {len(review_output.improvements_made)} improvements made.")
            await self.db.update_research(research_id, {"status": ResearchStatus.REVIEWING, "review_output": review_output.model_dump()})

        except Exception as e:
            error = str(e)
            logger.error(f"Pipeline error: {e}", exc_info=True)
            yield self._make_progress(research_id, ResearchStatus.FAILED, "Error", 0, f"Error: {error}")
            await self.db.update_research(research_id, {
                "status": ResearchStatus.FAILED, "error": error,
                "completed_at": datetime.now(timezone.utc).isoformat()
            })

        final_paper = ""
        if review_output:
            final_paper = review_output.revised_paper
        elif writer_output:
            final_paper = writer_output.full_paper

        status = ResearchStatus.COMPLETED if not error else ResearchStatus.FAILED
        now = datetime.now(timezone.utc).isoformat()

        result = ResearchResponse(
            research_id=research_id, topic=request.topic, status=status,
            fetch_output=fetch_output, writer_output=writer_output,
            review_output=review_output, final_paper=final_paper,
            error=error, created_at=now, completed_at=now if not error else None
        )
        self._result_store[research_id] = result

        await self.db.update_research(research_id, {
            "status": status, "final_paper": final_paper,
            "completed_at": datetime.now(timezone.utc).isoformat()
        })

        yield self._make_progress(research_id, status, "Complete", 100,
                                   "Research pipeline complete! Your IEEE paper is ready." if not error else f"Failed: {error}")

    def get_result(self, rid: str) -> Optional[ResearchResponse]:
        return self._result_store.get(rid)

    def get_progress(self, rid: str) -> Optional[ResearchProgress]:
        return self._progress_store.get(rid)

    async def get_all_research(self):
        return await self.db.get_all_research()
