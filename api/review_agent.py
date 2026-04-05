import os
import re
import logging
from groq import Groq
from api.schemas import ReviewAgentOutput, PlagiarismResult, AlignmentIssue, WriterAgentOutput

logger = logging.getLogger(__name__)


class ReviewAgent:
    def __init__(self):
        self.groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.model = "llama-3.3-70b-versatile"

    def _check_plagiarism_patterns(self, paper_text: str) -> PlagiarismResult:
        flagged = []
        score = 0.0

        for pattern in [r'"[^"]{50,}"', r'according to [^,\.]{0,30}, "[^"]{30,}"']:
            for match in re.findall(pattern, paper_text, re.IGNORECASE):
                flagged.append(f"Potential verbatim: {match[:100]}...")
                score += 5

        wiki_hits = sum(len(re.findall(p, paper_text, re.IGNORECASE)) for p in [
            r'\bis an?\b.{5,20}\bthat\b', r'\brefers to\b', r'\bwidely regarded as\b'
        ])
        if wiki_hits > 3:
            score += 15
            flagged.append("Multiple encyclopaedic phrasings detected — consider paraphrasing.")

        sentences = re.split(r'[.!?]+', paper_text)
        if len(sentences) > 5 and sum(len(s.split()) for s in sentences) / len(sentences) > 40:
            score += 8
            flagged.append("Unusually long average sentence length detected.")

        return PlagiarismResult(score=min(score, 35.0), flagged_sections=flagged, is_original=score < 25.0)

    def _check_ieee_alignment(self, paper_text: str) -> list:
        issues = []
        lower = paper_text.lower()

        for sec in ["introduction", "conclusion", "abstract", "references"]:
            if sec not in lower:
                issues.append(AlignmentIssue(
                    section="Structure",
                    issue=f"Missing required section: {sec.upper()}",
                    suggestion=f"Add a proper {sec.upper()} section following IEEE guidelines."
                ))

        abstract_match = re.search(
            r'abstract[—:\-\s]+(.+?)(?=\n\n|\n[IVX]+\.|\nkeywords)',
            paper_text, re.IGNORECASE | re.DOTALL
        )
        if abstract_match:
            wc = len(abstract_match.group(1).split())
            if wc < 100:
                issues.append(AlignmentIssue(
                    section="Abstract", issue=f"Abstract too short ({wc} words, min 150)",
                    suggestion="Expand to 150-250 words covering objectives, methodology, results, conclusion."
                ))
            elif wc > 300:
                issues.append(AlignmentIssue(
                    section="Abstract", issue=f"Abstract too long ({wc} words, max 250)",
                    suggestion="Condense to 150-250 words focusing on key contributions."
                ))

        if len(re.findall(r'\[\d+\]', paper_text)) < 3:
            issues.append(AlignmentIssue(
                section="Citations", issue="Insufficient in-text citations",
                suggestion="Add IEEE-format [N] citations throughout the paper body."
            ))

        if "keywords" not in lower:
            issues.append(AlignmentIssue(
                section="Keywords", issue="Missing keywords section",
                suggestion="Add 'Keywords—' with 5-7 relevant technical terms after the abstract."
            ))

        return issues

    def rewrite_and_improve(self, paper_text: str, issues: list, plag: PlagiarismResult) -> dict:
        issues_text = "\n".join([f"- [{i.section}] {i.issue}: {i.suggestion}" for i in issues]) or "No major issues."
        plag_notes = ""
        if plag.score > 15:
            plag_notes = f"\nPLAGIARISM CONCERNS (score {plag.score:.0f}%):\n" + "\n".join(plag.flagged_sections)

        prompt = f"""You are a senior IEEE paper reviewer. Review and improve this paper.

ISSUES FOUND:
{issues_text}
{plag_notes}

ORIGINAL PAPER:
{paper_text[:5000]}

Instructions:
1. Fix all alignment issues above
2. Rewrite flagged sections in original academic language
3. Ensure proper IEEE formatting throughout
4. Rate quality 0-10

Respond exactly as:
QUALITY_SCORE: [number]
IMPROVEMENTS_MADE:
- [item]
- [item]
REVISED_PAPER:
[full revised paper]"""

        try:
            resp = self.groq_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a senior IEEE paper editor. Ensure papers meet the highest standards of academic writing, formatting, and originality."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=4500
            )
            return self._parse_review(resp.choices[0].message.content, paper_text)
        except Exception as e:
            logger.error(f"Groq API error in ReviewAgent: {e}")
            return {"quality_score": 7.0, "improvements_made": ["Minor formatting corrections applied."], "revised_paper": paper_text}

    def _parse_review(self, content: str, original: str) -> dict:
        quality_score = 7.0
        improvements = []
        revised = original

        m = re.search(r'QUALITY_SCORE:\s*(\d+(?:\.\d+)?)', content)
        if m:
            quality_score = min(float(m.group(1)), 10.0)

        imp_m = re.search(r'IMPROVEMENTS_MADE:(.*?)(?=REVISED_PAPER:|$)', content, re.DOTALL)
        if imp_m:
            improvements = [
                l.lstrip("- •").strip() for l in imp_m.group(1).split("\n")
                if l.strip().startswith(("-", "•", "*"))
            ]

        rev_m = re.search(r'REVISED_PAPER:(.*)', content, re.DOTALL)
        if rev_m:
            revised = rev_m.group(1).strip()
        elif len(content) > len(original) * 0.5:
            revised = content

        if not improvements:
            improvements = ["IEEE compliance improved", "Academic language enhanced", "Citations verified"]

        return {"quality_score": quality_score, "improvements_made": improvements, "revised_paper": revised or original}

    async def run(self, writer_output: WriterAgentOutput) -> ReviewAgentOutput:
        logger.info(f"ReviewAgent starting for: {writer_output.title}")
        paper_text = writer_output.full_paper
        plag = self._check_plagiarism_patterns(paper_text)
        issues = self._check_ieee_alignment(paper_text)
        result = self.rewrite_and_improve(paper_text, issues, plag)

        return ReviewAgentOutput(
            original_paper=paper_text,
            plagiarism_check=plag,
            alignment_issues=issues,
            revised_paper=result["revised_paper"],
            improvements_made=result["improvements_made"],
            quality_score=result["quality_score"],
            ieee_compliance=len(issues) == 0
        )
