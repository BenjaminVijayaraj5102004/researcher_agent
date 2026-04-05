import os
import httpx
import asyncio
import logging
from typing import List, Optional
from groq import Groq
from api.schemas import FetchAgentOutput, SearchResult, FetchedContent

logger = logging.getLogger(__name__)


class FetchAgent:
    def __init__(self):
        self.groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.serper_api_key = os.getenv("SERPER_API_KEY")
        self.serper_url = "https://google.serper.dev/search"
        self.model = "llama-3.3-70b-versatile"

    async def search_web(self, topic: str, num_results: int = 5) -> List[SearchResult]:
        headers = {
            "X-API-KEY": self.serper_api_key,
            "Content-Type": "application/json"
        }
        payload = {"q": f"{topic} research academic", "num": num_results, "gl": "us", "hl": "en"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.serper_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

            results = []
            for item in data.get("organic", [])[:num_results]:
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    snippet=item.get("snippet", ""),
                    source="serper"
                ))
            return results
        except Exception as e:
            logger.error(f"Serper API error: {e}")
            return self._get_fallback_results(topic)

    def _get_fallback_results(self, topic: str) -> List[SearchResult]:
        return [
            SearchResult(
                title=f"Academic Research on {topic}",
                url=f"https://scholar.google.com/search?q={topic.replace(' ', '+')}",
                snippet=f"Comprehensive academic research covering {topic} including recent developments, methodologies, and findings.",
                source="fallback"
            ),
            SearchResult(
                title=f"{topic} - Overview",
                url=f"https://en.wikipedia.org/wiki/{topic.replace(' ', '_')}",
                snippet=f"{topic} is a significant area of study with wide-ranging implications in technology and society.",
                source="fallback"
            )
        ]

    async def fetch_page_content(self, url: str) -> Optional[FetchedContent]:
        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ResearchBot/1.0)"}
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                html_content = response.text

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            clean_text = "\n".join(lines[:150])
            title = soup.find("title")
            title_text = title.get_text() if title else url

            return FetchedContent(
                url=url,
                title=title_text[:200],
                content=clean_text[:5000],
                word_count=len(clean_text.split())
            )
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

    def extract_key_facts(self, topic: str, search_results: List[SearchResult], contents: List[FetchedContent]) -> dict:
        snippets_text = "\n".join([f"- [{r.title}]: {r.snippet}" for r in search_results])
        content_text = ""
        for c in contents[:3]:
            if c:
                content_text += f"\n\nSource: {c.title}\n{c.content[:1500]}"

        prompt = f"""You are a research assistant. Extract and structure key information about: "{topic}"

SEARCH SNIPPETS:
{snippets_text}

DETAILED CONTENT:
{content_text[:4000]}

Extract and return:
1. key_facts: 8-12 important facts (one per line starting with -)
2. summary: 200-word comprehensive summary
3. references: source titles and URLs

Be factual, precise, and academic."""

        try:
            response = self.groq_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert research analyst. Extract structured academic information from web content."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2000
            )
            content = response.choices[0].message.content
            return self._parse_llm_response(content, search_results)
        except Exception as e:
            logger.error(f"Groq API error in FetchAgent: {e}")
            return {
                "key_facts": [f"Information about {topic} gathered from {len(search_results)} sources."],
                "summary": f"Research on {topic} gathered from multiple academic and web sources.",
                "references": [{"title": r.title, "url": r.url} for r in search_results]
            }

    def _parse_llm_response(self, content: str, search_results: List[SearchResult]) -> dict:
        lines = content.split("\n")
        key_facts = []
        summary_lines = []
        in_summary = False

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if any(line.lower().startswith(k) for k in ["summary", "key_facts", "key facts"]):
                in_summary = "summary" in line.lower()
                continue
            if any(line.lower().startswith(k) for k in ["main_themes", "recent", "references", "3.", "4.", "5."]):
                in_summary = False
                continue
            if line.startswith(("-", "•", "*")):
                fact = line.lstrip("-•* ").strip()
                if fact and len(fact) > 20:
                    key_facts.append(fact)
            elif in_summary:
                summary_lines.append(line)

        return {
            "key_facts": key_facts[:12] if key_facts else [content[:500]],
            "summary": " ".join(summary_lines)[:1000] if summary_lines else content[:500],
            "references": [{"title": r.title, "url": r.url} for r in search_results]
        }

    async def run(self, topic: str, max_sources: int = 5) -> FetchAgentOutput:
        logger.info(f"FetchAgent starting for: {topic}")
        search_results = await self.search_web(topic, num_results=max_sources)

        fetch_tasks = [self.fetch_page_content(r.url) for r in search_results[:3]]
        fetched_raw = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        fetched_contents = [c for c in fetched_raw if isinstance(c, FetchedContent) and c is not None]

        extracted = self.extract_key_facts(topic, search_results, fetched_contents)

        references = [
            {"index": str(i), "title": r.title, "url": r.url, "snippet": r.snippet}
            for i, r in enumerate(search_results, 1)
        ]

        return FetchAgentOutput(
            topic=topic,
            search_results=search_results,
            fetched_contents=fetched_contents,
            key_facts=extracted.get("key_facts", []),
            summary=extracted.get("summary", ""),
            references=references,
            total_sources=len(search_results)
        )
