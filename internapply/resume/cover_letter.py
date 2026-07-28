"""Cover letter generator with two-pass generation and humanization.

Generates professional cold emails for internship applications using a
draft-then-humanize pipeline with scoring and regeneration.

Usage::

    from internapply.resume.cover_letter import CoverLetterGen

    gen = CoverLetterGen()
    letter, score = await gen.generate(
        title="Software Engineer Intern",
        company="Acme Corp",
        jd_summary="Python backend role",
        top_skills=["Python", "Django"],
        summary="B.Tech student with full-stack experience",
    )
"""

from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

from internapply.llm import LLMClient
from internapply.resume.parser import load_resume_json
from internapply.resume.tailor import _sanitize_path_component
from internapply.resume.verifier import _CLICHE_PATTERNS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_APPLICATIONS_DIR = Path("applications")

# Robotic/redundant phrasing patterns to replace during humanization.
# Each entry is (compiled_pattern, replacement_string).
# An empty replacement removes the phrase entirely.
_ROBOTIC_REPLACEMENTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bI would like to request\b", re.IGNORECASE), "Could we"),
    (re.compile(r"\bI am writing to\b", re.IGNORECASE), ""),
    (re.compile(r"\bI am writing this (?:email|letter) to\b", re.IGNORECASE), ""),
    (re.compile(r"\bI believe that\b", re.IGNORECASE), "I think"),
    (re.compile(r"\bIf possible, I would\b", re.IGNORECASE), "I'd"),
    (re.compile(r"\bI am confident that\b", re.IGNORECASE), ""),
    (re.compile(r"\bI am excited about\b", re.IGNORECASE), ""),
    (re.compile(r"\bI am thrilled\b", re.IGNORECASE), "I'm excited"),
    (re.compile(r"\bI would love to\b", re.IGNORECASE), "I'd like to"),
    (re.compile(r"\bPlease find (?:attached|enclosed|below)\b", re.IGNORECASE),
     "I've attached"),
]

# Hedging phrases to remove entirely.
_HEDGING_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bjust\b", re.IGNORECASE),
    re.compile(r"\bmaybe\b", re.IGNORECASE),
    re.compile(r"\bperhaps\b", re.IGNORECASE),
    re.compile(r"\bif that's okay\b", re.IGNORECASE),
    re.compile(r"\bif that is okay\b", re.IGNORECASE),
    re.compile(r"\bif possible\b", re.IGNORECASE),
    re.compile(r"\bhopefully\b", re.IGNORECASE),
]

# Submissive or overly deferential language (tone check).
_SUBMISSIVE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bwith your kind\b", re.IGNORECASE),
    re.compile(r"\bif you don't mind\b", re.IGNORECASE),
    re.compile(r"\bsorry to bother\b", re.IGNORECASE),
    re.compile(r"\bI apologize for\b", re.IGNORECASE),
    re.compile(r"\bI hate to bother\b", re.IGNORECASE),
]

# Overly formal / archaic language (tone check).
_OVERLY_FORMAL_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bhereby\b", re.IGNORECASE),
    re.compile(r"\bwherein\b", re.IGNORECASE),
    re.compile(r"\bwhereas\b", re.IGNORECASE),
    re.compile(r"\bthusly\b", re.IGNORECASE),
    re.compile(r"\bwhomsoever\b", re.IGNORECASE),
]

_MAX_REGENERATION_ATTEMPTS = 3
_MIN_SCORE = 80
_MIN_WORDS = 80
_MAX_WORDS = 120


# ---------------------------------------------------------------------------
# Humanisation helpers
# ---------------------------------------------------------------------------


def _count_cliches(text: str) -> int:
    """Return the number of **distinct** AI-cliché patterns found in *text*."""
    return sum(1 for pat in _CLICHE_PATTERNS if pat.search(text))


def _sentence_starters(text: str) -> list[str]:
    """Return the first word of each sentence in *text*.

    Splits on ``.``, ``!``, and ``?``, then extracts the first alphabetic
    token (stripping leading quotes or parentheses).
    """
    sentences = re.split(r"[.!?]+", text)
    starters: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        words = sentence.split()
        if words:
            first = words[0].strip("\"'(")
            if first:
                starters.append(first)
    return starters


def _count_hedging(text: str) -> int:
    """Return the total number of hedging-phrase occurrences in *text*."""
    return sum(len(pat.findall(text)) for pat in _HEDGING_PATTERNS)


def _has_natural_phrasing(text: str) -> bool:
    """Return ``True`` if *text* reads as peer-to-peer (no submissive or overly formal language).

    Checks for submissive patterns (apologetic / deferential language) and
    overly formal / archaic constructions.
    """
    for pat in _SUBMISSIVE_PATTERNS:
        if pat.search(text):
            return False
    for pat in _OVERLY_FORMAL_PATTERNS:
        if pat.search(text):
            return False
    return True


def _humanize(text: str) -> str:
    """Run the humanisation pipeline on *text*.

    Steps
    -----
    1. Strip recognised AI cliché phrases (reuse patterns from verifier.py).
    2. Replace robotic patterns with natural alternatives.
    3. Remove hedging language.
    4. Clean up whitespace artifacts left by removals.
    """
    result = text

    # 1. Strip clichés — remove the phrase entirely
    for pat in _CLICHE_PATTERNS:
        result = pat.sub("", result)

    # 2. Replace robotic patterns
    for pat, replacement in _ROBOTIC_REPLACEMENTS:
        result = pat.sub(replacement, result)

    # 3. Remove hedging
    for pat in _HEDGING_PATTERNS:
        result = pat.sub("", result)

    # 4. Clean up whitespace artifacts from removals
    result = re.sub(r"\s{2,}", " ", result)
    result = re.sub(r"\s+\.", ".", result)
    result = re.sub(r"\s+,", ",", result)
    result = result.strip()

    return result


def _humanization_score(text: str) -> int:
    """Compute a humanisation score (0-100) for *text*.

    Five equally-weighted criteria (20 points each):

    +20  **No clichés** — zero AI-cliché pattern matches.
    +20  **Varied sentence starters** — fewer than 40 % of sentences
         begin with "I".
    +20  **No hedging** — zero hedging-phrase occurrences.
    +20  **Natural phrasing** — no submissive or overly formal language.
    +20  **Word count sweet spot** — between 80 and 120 words inclusive.
    """
    score = 0

    # +20: No clichés
    if _count_cliches(text) == 0:
        score += 20

    # +20: Varied sentence starters
    starters = _sentence_starters(text)
    if starters:
        i_count = sum(1 for s in starters if s.lower() == "i")
        if i_count / len(starters) < 0.4:
            score += 20

    # +20: No hedging
    if _count_hedging(text) == 0:
        score += 20

    # +20: Natural phrasing
    if _has_natural_phrasing(text):
        score += 20

    # +20: Word count in sweet spot
    word_count = len(text.split())
    if _MIN_WORDS <= word_count <= _MAX_WORDS:
        score += 20

    return score


def _build_draft_prompt(
    title: str,
    company: str,
    jd_summary: str,
    top_skills: list[str],
    summary: str,
    name: str,
    feedback: str | None = None,
) -> str:
    """Build the LLM prompt for cover letter draft generation.

    Parameters
    ----------
    title:
        Job title.
    company:
        Company name.
    jd_summary:
        Brief description of the role / job description.
    top_skills:
        Candidate's top relevant skills.
    summary:
        Candidate's professional background summary.
    name:
        Candidate's name.
    feedback:
        Optional feedback from a previous attempt to guide regeneration.

    Returns
    -------
    A plain-text prompt string.
    """
    skills_str = ", ".join(top_skills) if top_skills else "relevant skills"

    prompt = (
        f"Write a professional cold email (80-120 words) to the hiring manager "
        f"at {company} for the {title} role. "
        f"Your name is {name}, a computer science student (B.Tech AI/ML, B.Sc CS). "
        f"Background: {summary}. "
        f"Relevant skills: {skills_str}.\n\n"
        f"The email should:\n"
        f"1) Reference something specific about the company or job description "
        f"to show research\n"
        f"2) State you've applied and why you're a strong fit (1-2 specific "
        f"achievements)\n"
        f"3) Ask for a 15-minute conversation\n\n"
        f"Tone: professional, confident, concise — like a peer, not a "
        f"subordinate. Plain text format, no placeholders, under 120 words.\n\n"
        f"NO clichés: 'I am writing to apply', 'I am excited about', "
        f"'proven track record', 'team player', 'keen interest'."
    )

    if feedback:
        prompt += f"\n\nFeedback from previous attempt:\n{feedback}"

    return prompt


# ---------------------------------------------------------------------------
# CoverLetterGen
# ---------------------------------------------------------------------------


class CoverLetterGen:
    """Two-pass cover letter generator with humanisation scoring and regeneration.

    **Pass 1 — Draft:** Calls the LLM (``async_complete`` with temperature
    0.7) to produce a raw cold-email draft.

    **Pass 2 — Humanisation:** Runs the draft through a deterministic pipeline
    that strips clichés, replaces robotic phrasing, removes hedging, and
    computes a 0-100 humanisation score.  If the score is below 80 the draft
    is regenerated with explicit feedback, up to 3 attempts.

    The final letter is saved to
    ``applications/{sanitised_company}_{sanitised_title}/cover_letter.md``.

    Usage::

        from internapply.resume.cover_letter import CoverLetterGen

        gen = CoverLetterGen()
        letter, score = await gen.generate(
            title="Software Engineer Intern",
            company="Acme Corp",
            jd_summary="Python backend role",
            top_skills=["Python", "Django"],
            summary="B.Tech student with full-stack experience",
        )
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        """Initialise with an optional custom LLM client.

        Args:
            llm_client: An :class:`LLMClient` instance.  Defaults to a fresh
                client using the global config.
        """
        self._llm = llm_client or LLMClient()

    async def generate(
        self,
        title: str,
        company: str,
        jd_summary: str,
        top_skills: list[str],
        summary: str,
        name: str | None = None,
        max_regeneration_attempts: int = _MAX_REGENERATION_ATTEMPTS,
    ) -> tuple[str, int]:
        """Generate a cover letter with two-pass humanisation.

        Parameters
        ----------
        title:
            The job title (e.g. ``"Software Engineer Intern"``).
        company:
            The company name (e.g. ``"Acme Corp"``).
        jd_summary:
            A brief description of the role / job description
            (e.g. ``"Python backend role"``).
        top_skills:
            Top relevant skills for this role
            (e.g. ``["Python", "Django"]``).
        summary:
            The candidate's professional background summary
            (e.g. ``"B.Tech student with full-stack experience"``).
        name:
            The candidate's name.  If ``None``, attempts to load it from
            ``profile/resume.json``.
        max_regeneration_attempts:
            Maximum number of draft+humanise cycles if the humanisation
            score stays below 80 (default 3).

        Returns
        -------
        A tuple of ``(cover_letter_text: str, humanization_score: int)``.
        """
        # ── Resolve name ──────────────────────────────────────────────
        if not name:
            resume = load_resume_json()
            if resume and resume.get("name"):
                name = resume["name"]
            else:
                name = "the candidate"

        best_letter = ""
        best_score = 0

        # ── Regeneration loop ─────────────────────────────────────────
        for attempt in range(max_regeneration_attempts):
            # Build feedback from the *previous* attempt's analysis
            feedback = None
            if attempt > 0 and best_letter:
                parts: list[str] = []
                if _count_cliches(best_letter) > 0:
                    parts.append("- Remove ALL cliché phrases from the email")
                if _count_hedging(best_letter) > 0:
                    parts.append(
                        "- Remove all hedging language "
                        "(just, maybe, perhaps, if possible)",
                    )
                starters = _sentence_starters(best_letter)
                if starters:
                    i_ratio = sum(1 for s in starters if s.lower() == "i") / len(starters)
                    if i_ratio > 0.4:
                        parts.append(
                            "- Vary your sentence starters — don't begin "
                            "every sentence with 'I'",
                        )
                if not _has_natural_phrasing(best_letter):
                    parts.append(
                        "- Write as a peer, not a subordinate — be confident "
                        "and direct",
                    )
                wc = len(best_letter.split())
                if wc < _MIN_WORDS or wc > _MAX_WORDS:
                    parts.append(
                        f"- Keep the email between {_MIN_WORDS}-{_MAX_WORDS} "
                        f"words (was {wc})",
                    )
                if parts:
                    feedback = "\n".join(parts)

            prompt = _build_draft_prompt(
                title, company, jd_summary, top_skills, summary, name, feedback,
            )

            # Pass 1: Draft — creative, so higher temperature
            letter = await self._llm.async_complete(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=512,
            )

            # Pass 2: Humanisation pipeline
            letter = _humanize(letter)

            # Score
            score = _humanization_score(letter)

            # Track best across attempts
            if score > best_score:
                best_letter = letter
                best_score = score

            logger.info(
                "Cover letter attempt {}/{} — score={} words={}",
                attempt + 1,
                max_regeneration_attempts,
                score,
                len(letter.split()),
            )

            if score >= _MIN_SCORE:
                logger.info("Cover letter passed humanisation with score {}/100", score)
                break

        # ── Warn if final score is still below threshold ───────────────
        if best_score < _MIN_SCORE:
            logger.warning(
                "Cover letter score {} is below threshold {} — "
                "returning best-effort result",
                best_score,
                _MIN_SCORE,
            )

        # ── Save to disk ──────────────────────────────────────────────
        save_path = self._save(company, title, best_letter)
        logger.info("Cover letter saved to {}", save_path)

        return best_letter, best_score

    # ── Internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _save(company: str, title: str, content: str) -> Path:
        """Save the cover letter to ``applications/{slug}/cover_letter.md``.

        Args:
            company: Company name (used for directory naming).
            title: Job title (used for directory naming).
            content: Cover letter text.

        Returns:
            The absolute path of the saved file.
        """
        safe_company = _sanitize_path_component(company)
        safe_title = _sanitize_path_component(title)
        output_dir = (_APPLICATIONS_DIR / f"{safe_company}_{safe_title}").resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        path = output_dir / "cover_letter.md"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)

        return path


__all__ = ["CoverLetterGen"]
