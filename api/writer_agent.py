import os
import re
import logging
from groq import Groq
from api.schemas import WriterAgentOutput, IEEESection, FetchAgentOutput

logger = logging.getLogger(__name__)

IEEE_TEMPLATE = """Write a complete IEEE-format research paper on the given topic.

IEEE FORMAT:
- Title: Concise, ≤12 words
- Abstract: 150-250 words (objective, method, results, conclusion)
- Keywords: 5-7 technical keywords after abstract
- Sections: I. INTRODUCTION, II. RELATED WORK, III. METHODOLOGY, IV. RESULTS AND DISCUSSION, V. CONCLUSION
- References: IEEE format [N] Author, "Title," Journal, vol., pp., year.
- Use [1],[2] in-text citations
- Subsections as: A. Subsection Title
- Each section: 200-400 words
"""


class WriterAgent:
    def __init__(self):
        self.groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.model = "llama-3.3-70b-versatile"

    def _build_context(self, fetch_output: FetchAgentOutput) -> str:
        parts = [
            f"TOPIC: {fetch_output.topic}",
            f"\nSUMMARY:\n{fetch_output.summary}",
            "\nKEY FACTS:"
        ]
        for i, fact in enumerate(fetch_output.key_facts, 1):
            parts.append(f"{i}. {fact}")
        parts.append("\nSOURCES:")
        for ref in fetch_output.references[:8]:
            parts.append(f"- [{ref.get('index','?')}] {ref.get('title','')} — {ref.get('url','')}")
        if fetch_output.search_results:
            parts.append("\nSNIPPETS:")
            for r in fetch_output.search_results[:5]:
                parts.append(f"• {r.title}: {r.snippet}")
        return "\n".join(parts)

    def write_paper(self, fetch_output: FetchAgentOutput) -> str:
        context = self._build_context(fetch_output)
        prompt = f"""{IEEE_TEMPLATE}

RESEARCH INFORMATION:
{context}

Write a comprehensive IEEE paper (~2500 words) using ALL the information above.
Format citations as [1],[2] and include a complete References section."""

        try:
            response = self.groq_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert academic writer specializing in IEEE-format papers. Write rigorous, well-structured, properly cited papers."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4,
                max_tokens=4000
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Groq API error in WriterAgent: {e}")
            return self._fallback_paper(fetch_output)

    def _fallback_paper(self, fetch_output: FetchAgentOutput) -> str:
        topic = fetch_output.topic
        facts = "\n".join(fetch_output.key_facts[:5])
        refs = "\n".join([
            f"[{r.get('index',i+1)}] \"{r.get('title','Source')}\" Available: {r.get('url','')}"
            for i, r in enumerate(fetch_output.references[:5])
        ])
        return f"""Title: A Comprehensive Study of {topic}

Abstract—This paper presents a systematic study of {topic}, examining key aspects, methodologies, and implications. Through review of current literature and available data, this work contributes to the understanding of {topic} and its applications.

Keywords—{topic.lower()}, research, analysis, study, review

I. INTRODUCTION
{topic} represents a significant area of contemporary research [1]. This paper provides a comprehensive examination of the subject.

II. RELATED WORK
Key findings from literature include:
{facts}

III. METHODOLOGY
This research employs a systematic review examining multiple primary and secondary sources [2].

IV. RESULTS AND DISCUSSION
Analysis reveals important insights regarding {topic} [3]. These findings have broad implications for both research and practice.

V. CONCLUSION
This paper presented a comprehensive overview of {topic}. Future work should focus on empirical validation and practical applications.

REFERENCES
{refs}"""

    def _parse_sections(self, text: str):
        title, abstract, keywords, sections, references = "", "", [], [], []
        current_section = None
        current_content = []
        in_abstract = False
        in_refs = False

        for line in text.split("\n"):
            s = line.strip()
            if not s:
                if current_content:
                    current_content.append("")
                continue

            if not title and len(s) > 10 and not s.lower().startswith(("abstract", "i.", "ii.", "iii.")):
                title = s.replace("Title:", "").replace("title:", "").strip()[:200]
                continue

            if re.match(r'^abstract', s, re.IGNORECASE):
                in_abstract = True
                rest = re.sub(r'^abstract[—:\-\s]*', '', s, flags=re.IGNORECASE).strip()
                if rest:
                    abstract += " " + rest
                continue

            if re.match(r'^keywords', s, re.IGNORECASE):
                in_abstract = False
                kw = re.sub(r'^keywords[—:\-\s]*', '', s, flags=re.IGNORECASE).strip()
                keywords = [k.strip() for k in kw.split(",") if k.strip()]
                continue

            if re.match(r'^REFERENCES', s) and len(s) < 25:
                in_abstract = False
                in_refs = True
                if current_section and current_content:
                    sections.append(IEEESection(title=current_section, content="\n".join(current_content).strip()))
                current_section = None
                current_content = []
                continue

            if in_refs and s.startswith("["):
                references.append(s)
                continue

            if re.match(r'^[IVX]+\.?\s+[A-Z]', s) and len(s) < 70:
                in_abstract = False
                if current_section and current_content:
                    sections.append(IEEESection(title=current_section, content="\n".join(current_content).strip()))
                current_section = s
                current_content = []
                continue

            if in_abstract:
                abstract += " " + s
            elif current_section:
                current_content.append(s)

        if current_section and current_content:
            sections.append(IEEESection(title=current_section, content="\n".join(current_content).strip()))

        return title.strip(), abstract.strip(), keywords, sections, references

    async def run(self, fetch_output: FetchAgentOutput) -> WriterAgentOutput:
        logger.info(f"WriterAgent starting for: {fetch_output.topic}")
        paper_text = self.write_paper(fetch_output)
        title, abstract, keywords, sections, references = self._parse_sections(paper_text)

        if not title or len(title) < 5:
            title = f"A Comprehensive Study of {fetch_output.topic}"
        if not abstract or len(abstract) < 50:
            abstract = fetch_output.summary[:500] or f"This paper examines {fetch_output.topic}."
        if not keywords:
            keywords = fetch_output.topic.split()[:5]
        if not references:
            references = [
                f"[{r.get('index', i+1)}] \"{r.get('title','Source')}\" Available: {r.get('url','')}"
                for i, r in enumerate(fetch_output.references[:8])
            ]

        return WriterAgentOutput(
            title=title, abstract=abstract, keywords=keywords,
            sections=sections, references=references,
            full_paper=paper_text, word_count=len(paper_text.split())
        )
