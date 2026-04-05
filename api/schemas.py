from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime


class ResearchStatus(str, Enum):
    PENDING = "pending"
    FETCHING = "fetching"
    WRITING = "writing"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"


class SearchResult(BaseModel):
    title: str = Field(default="")
    url: str = Field(default="")
    snippet: str = Field(default="")
    source: str = Field(default="web")


class FetchedContent(BaseModel):
    url: str = Field(default="")
    title: str = Field(default="")
    content: str = Field(default="")
    word_count: int = Field(default=0)


class FetchAgentOutput(BaseModel):
    topic: str
    search_results: List[SearchResult] = Field(default_factory=list)
    fetched_contents: List[FetchedContent] = Field(default_factory=list)
    key_facts: List[str] = Field(default_factory=list)
    summary: str = Field(default="")
    references: List[Dict[str, str]] = Field(default_factory=list)
    total_sources: int = Field(default=0)


class IEEESection(BaseModel):
    title: str
    content: str
    subsections: List[Dict[str, str]] = Field(default_factory=list)


class WriterAgentOutput(BaseModel):
    title: str
    abstract: str
    keywords: List[str] = Field(default_factory=list)
    sections: List[IEEESection] = Field(default_factory=list)
    references: List[str] = Field(default_factory=list)
    full_paper: str = Field(default="")
    word_count: int = Field(default=0)


class PlagiarismResult(BaseModel):
    score: float = Field(default=0.0)
    flagged_sections: List[str] = Field(default_factory=list)
    is_original: bool = Field(default=True)


class AlignmentIssue(BaseModel):
    section: str
    issue: str
    suggestion: str


class ReviewAgentOutput(BaseModel):
    original_paper: str
    plagiarism_check: PlagiarismResult
    alignment_issues: List[AlignmentIssue] = Field(default_factory=list)
    revised_paper: str
    improvements_made: List[str] = Field(default_factory=list)
    quality_score: float = Field(default=0.0)
    ieee_compliance: bool = Field(default=True)


class ResearchRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=500)
    additional_context: Optional[str] = Field(None)
    max_sources: int = Field(default=5, ge=1, le=10)


class ResearchResponse(BaseModel):
    research_id: str
    topic: str
    status: ResearchStatus
    fetch_output: Optional[FetchAgentOutput] = None
    writer_output: Optional[WriterAgentOutput] = None
    review_output: Optional[ReviewAgentOutput] = None
    final_paper: str = Field(default="")
    error: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


class ResearchProgress(BaseModel):
    research_id: str
    status: ResearchStatus
    current_step: str
    progress_percentage: int = Field(default=0, ge=0, le=100)
    message: str
    logs: List[str] = Field(default_factory=list)
