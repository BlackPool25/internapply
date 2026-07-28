"""Resume parser that extracts structured data from the JS DOCX generator.

The canonical source of resume data is ``profile/resume.json``.
This module provides functions to parse the JS generator file, persist to
JSON, load it back, and produce a human-readable summary.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants — default paths relative to the project root
# ---------------------------------------------------------------------------

_DEFAULT_PROFILE_DIR = Path("profile")
_DEFAULT_RESUME_PATH = _DEFAULT_PROFILE_DIR / "resume.json"


# ---------------------------------------------------------------------------
# JS parser
# ---------------------------------------------------------------------------

def parse_from_js_script(filepath: str) -> dict[str, Any]:
    """Parse a ``generate_resume_ai.js`` file and return a structured resume dict.

    The returned dict matches the schema expected by :class:`internapply.models.Resume`:

    .. code-block:: python

        {
            "name": str,
            "email": str,
            "phone": str,
            "location": str,
            "summary": str,
            "education": list[dict],
            "skills": dict[str, str],
            "projects": list[dict],
            "additional": list[dict],
        }

    Args:
        filepath: Absolute or relative path to the JS generator file.

    Returns:
        A dictionary with the keys listed above.
    """
    with open(filepath, encoding="utf-8") as fh:
        text = fh.read()

    data: dict[str, Any] = {}

    data["name"] = _extract_name(text)
    data["email"], data["phone"], data["location"] = _extract_contact(text)
    data["summary"] = _extract_summary(text)
    data["education"] = _extract_education(text)
    data["skills"] = _extract_skills(text)
    data["projects"] = _extract_projects(text)
    data["additional"] = _extract_additional(text)

    return data


def _extract_name(text: str) -> str:
    """Extract name from the size-40 TextRun."""
    m = re.search(r'TextRun\(\{[^}]*text:\s*"([^"]+)"[^}]*size:\s*40[,}]', text)
    if m:
        return m.group(1).strip()
    m = re.search(r'"([A-Z]+ [A-Z]\.? [A-Z]+)"', text)
    return m.group(1) if m else "Unknown"


def _extract_contact(text: str) -> tuple[str, str, str]:
    """Extract email, phone, location from the contact line."""
    email = phone = location = ""

    m = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', text)
    if m:
        email = m.group(1)

    m = re.search(r'(\+?\d{1,3}[\s-]?\d{6,15})', text)
    if m:
        phone = m.group(1)

    # Location begins with "Bangalore"
    m = re.search(r'"([^"]*Bangalore[^"]*)"', text)
    if m:
        raw = m.group(1)
        # Take everything before the first "|" that precedes linkedin/github
        location = raw.split("|")[0].strip().rstrip(" |")
    else:
        location = "Bangalore, India"

    return email, phone, location or "Bangalore, India"


def _extract_summary(text: str) -> str:
    """Extract the professional summary paragraph text."""
    # The summary is in a TextRun under "Professional Summary" section
    # Use  re.DOTALL so . matches newlines across the multi-line TextRun
    m = re.search(
        r'TextRun\(\{\s*text:\s*"([^"]*AI/ML[^"]*)"\s*,\s*size:\s*20,\s*color:\s*BLACK',
        text,
        re.DOTALL,
    )
    if m:
        return m.group(1)

    # Broader fallback via sectionHeading marker
    m = re.search(
        r'sectionHeading\("Professional Summary"\).*?text:\s*"([^"]+)"',
        text,
        re.DOTALL,
    )
    return m.group(1) if m else ""


def _extract_education(text: str) -> list[dict[str, str]]:
    """Extract education entries by finding the Education section and grouping
    consecutive TextRun blocks into entries."""
    entries: list[dict[str, str]] = []

    # Isolate the Education section
    parts = re.split(r'sectionHeading\("Education"\)', text)
    if len(parts) < 2:
        return entries

    edu_section = parts[1]
    # Stop before the next section heading
    edu_section = re.split(
        r'sectionHeading\("(?:Technical Skills|Projects)"\)', edu_section
    )[0]

    # Find all TextRun objects in the education section
    tr_pattern = r'TextRun\(\{([^}]+)\}\)'
    textruns = re.findall(tr_pattern, edu_section)

    # Group every 4 consecutive TextRuns into one education entry
    # Pattern per entry: degree | institution | CGPA | expected
    for i in range(0, len(textruns) - len(textruns) % 4, 4):
        entry: dict[str, str] = {}

        # Each tr is the inner content of TextRun({...})
        for offset, key in [(0, "degree"), (1, "institution"), (2, "cgpa"), (3, "expected")]:
            if i + offset >= len(textruns):
                continue
            inner = textruns[i + offset]
            # Extract the text value
            tm = re.search(r'text:\s*"([^"]*)"', inner)
            if not tm:
                continue
            raw = tm.group(1).strip()
            # Remove leading "  |  " separator if present
            raw = re.sub(r'^\s*\|\s*', "", raw).strip()

            if key == "cgpa":
                # e.g. "CGPA: 9.39 / 10" -> "9.39"
                cm = re.search(r"CGPA:\s*([\d.]+)", raw)
                if cm:
                    entry[key] = cm.group(1)
            elif key == "expected":
                # e.g. "Expected: May 2027"
                em = re.search(r"Expected:\s*(.+)", raw)
                if em:
                    entry[key] = em.group(1).strip()
            elif key in ("degree", "institution"):
                entry[key] = raw

        if entry:
            entries.append(entry)

    return entries


def _extract_skills(text: str) -> dict[str, str]:
    """Extract ``skillLine("Category", "value")`` entries."""
    skills: dict[str, str] = {}
    for m in re.finditer(r'skillLine\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)', text):
        skills[m.group(1).strip()] = m.group(2).strip()
    return skills


def _extract_projects(text: str) -> list[dict[str, Any]]:
    """Extract projects with name, description bullets, tech stack, and URL."""
    projects: list[dict[str, Any]] = []

    # Isolate the Projects section
    parts = re.split(r'sectionHeading\("Projects"\)', text)
    if len(parts) < 2:
        return projects

    proj_section = parts[1]
    proj_section = re.split(
        r'sectionHeading\("Additional Information"\)', proj_section
    )[0]

    # Find all projectHeading(...) calls with their positions
    heading_pattern = r'projectHeading\(\s*"([^"]+?)"\s*(?:,\s*"([^"]*?)"\s*)?\)'
    headings = list(re.finditer(heading_pattern, proj_section))

    for i, hm in enumerate(headings):
        block_start = hm.end()
        block_end = headings[i + 1].start() if i + 1 < len(headings) else len(proj_section)
        block = proj_section[block_start:block_end]

        project: dict[str, Any] = {}
        full_title = hm.group(1).strip()
        project["url"] = hm.group(2) or ""

        # Name is the part before " | " (or the whole string)
        name_parts = full_title.split(" | ")
        project["name"] = name_parts[0].strip()

        # Tech stack
        tech_m = re.search(r'techLine\(\s*"([^"]+)"\s*\)', block)
        project["tech"] = tech_m.group(1).strip() if tech_m else ""

        # Description bullets — use bracket-depth parsing
        project["description"] = _extract_bullets(block)

        projects.append(project)

    return projects


def _extract_bullets(block: str) -> list[str]:
    """Extract bullet-point text from a project block.

    Handles nested bracket structures by counting depth.
    """
    bullets: list[str] = []

    # Find all `bullet([` openings and match to their `])` closing
    start_search = 0
    while True:
        bstart = block.find("bullet([", start_search)
        if bstart == -1:
            break

        # Find the matching `])` by counting bracket depth
        depth = 1
        pos = bstart + len("bullet([")
        while pos < len(block) and depth > 0:
            ch = block[pos]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
            pos += 1

        if depth == 0:
            # Extract content between `bullet([` and `])`
            inner = block[bstart + len("bullet([") : pos - 1]
            # Extract all text values from TextRun objects
            texts = re.findall(r'text:\s*"([^"]*)"', inner)
            bullet_text = "".join(texts)
            if bullet_text.strip():
                bullets.append(bullet_text.strip())
            start_search = pos
        else:
            start_search = bstart + 1

    return bullets


def _extract_additional(text: str) -> list[dict[str, str]]:
    """Extract additional information items."""
    additional: list[dict[str, str]] = []

    parts = re.split(r'sectionHeading\("Additional Information"\)', text)
    if len(parts) < 2:
        return additional

    add_section = parts[1]

    # Collect all text-producing blocks in the section using bracket-depth
    # parsing — covers both bullet([...]) and new Paragraph({...}).
    texts: list[str] = []
    search_from = 0
    while search_from < len(add_section):
        # Find next marker: bullet([ or new Paragraph({
        bullet_pos = add_section.find("bullet([", search_from)
        para_pos = add_section.find("new Paragraph({", search_from)

        # Pick whichever marker comes first
        markers = []
        if bullet_pos != -1:
            markers.append((bullet_pos, "bullet", "bullet([", "]"))
        if para_pos != -1:
            markers.append((para_pos, "paragraph", "new Paragraph({", "}"))

        if not markers:
            break

        markers.sort()
        pos, name, open_marker, _close_char = markers[0]

        # Find matching close by bracket depth
        depth = 1
        inner_start = pos + len(open_marker)
        p = inner_start
        while p < len(add_section) and depth > 0:
            ch = add_section[p]
            # For paragraphs, track both { and }
            if name == "paragraph":
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
            else:  # bullet
                if ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
            p += 1

        if depth == 0:
            inner = add_section[inner_start : p - 1]
            # Extract all text from TextRun objects in this block.
            # Bullets have raw '{ text: "..." }' inside, paragraphs have 'TextRun({ text: "..." })'
            # Use a simple pattern that catches both: 'text: "..."'
            block_texts = re.findall(r'text:\s*"([^"]*)"', inner)
            full = "".join(block_texts).strip()
            if full:
                texts.append(full)
            search_from = p
        else:
            search_from = pos + 1

    # Convert collected texts to label/value pairs
    for t in texts:
        if ": " in t:
            label, value = t.split(": ", 1)
            item = {"label": label.strip(), "value": value.strip()}
        else:
            item = {"label": t, "value": ""}
        if not any(a["label"] == item["label"] for a in additional):
            additional.append(item)

    return additional


# ---------------------------------------------------------------------------
# JSON persistence
# ---------------------------------------------------------------------------


def save_resume_json(
    data: dict[str, Any],
    filepath: str | Path = "",
) -> str:
    """Save structured resume *data* to a JSON file.

    Args:
        data: The resume dictionary.
        filepath: Path to write to.  If empty or ``None``, uses
            ``profile/resume.json`` relative to the project root.

    Returns:
        The absolute path of the saved file.
    """
    path = _resolve_path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)

    return str(path.resolve())


def load_resume_json(
    filepath: str | Path = "",
) -> dict[str, Any] | None:
    """Load structured resume data from a JSON file.

    Args:
        filepath: Path to read from.  If empty or ``None``, uses
            ``profile/resume.json``.

    Returns:
        The resume dictionary, or ``None`` if the file does not exist.
    """
    path = _resolve_path(filepath)
    if not path.exists():
        return None

    with open(path, encoding="utf-8") as fh:
        return json.load(fh)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Summary formatting
# ---------------------------------------------------------------------------


def get_resume_summary(data: dict[str, Any]) -> str:
    """Return a human-readable text summary of the resume for terminal display.

    Args:
        data: A resume dictionary produced by ``parse_from_js_script()``
            or loaded via ``load_resume_json()``.

    Returns:
        A formatted multi-line string.
    """
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append(f"  {data.get('name', 'N/A')}")
    lines.append("=" * 60)

    location = data.get("location", "")
    email = data.get("email", "")
    phone = data.get("phone", "")
    contacts = " | ".join(filter(None, [location, email, phone]))
    if contacts:
        lines.append(f"  {contacts}")
    lines.append("")

    # Summary
    summary = data.get("summary", "")
    if summary:
        lines.append("  PROFESSIONAL SUMMARY")
        lines.append("  " + "-" * 40)
        lines.append(f"  {summary}")
        lines.append("")

    # Education
    edu = data.get("education", [])
    if edu:
        lines.append("  EDUCATION")
        lines.append("  " + "-" * 40)
        for e in edu:
            parts = [
                e.get("degree", ""),
                f"@ {e.get('institution', '')}" if e.get("institution") else "",
                f"CGPA: {e['cgpa']}" if e.get("cgpa") else "",
                e.get("expected", ""),
            ]
            line = "  " + " | ".join(p for p in parts if p)
            lines.append(line)
        lines.append("")

    # Skills
    skills = data.get("skills", {})
    if skills:
        lines.append("  TECHNICAL SKILLS")
        lines.append("  " + "-" * 40)
        for cat, val in skills.items():
            lines.append(f"  {cat}: {val}")
        lines.append("")

    # Projects
    projects = data.get("projects", [])
    if projects:
        lines.append("  PROJECTS")
        lines.append("  " + "-" * 40)
        for proj in projects:
            name = proj.get("name", "?")
            url = proj.get("url", "")
            tech = proj.get("tech", "")
            header = f"  {name}"
            if url:
                header += f"  ({url})"
            lines.append(header)
            if tech:
                lines.append(f"    Tech: {tech}")
            desc = proj.get("description", [])
            for d in desc:
                lines.append(f"    * {d}")
            lines.append("")

    # Additional
    additional = data.get("additional", [])
    if additional:
        lines.append("  ADDITIONAL INFORMATION")
        lines.append("  " + "-" * 40)
        for item in additional:
            label = item.get("label", "")
            value = item.get("value", "")
            if label and value:
                lines.append(f"  * {label}: {value}")
            elif label:
                lines.append(f"  * {label}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_path(filepath: str | Path) -> Path:
    """Resolve a possibly-empty filepath to an absolute :class:`Path`."""
    if not filepath:
        return _DEFAULT_RESUME_PATH.resolve()

    p = Path(filepath)
    if p.is_absolute():
        return p
    return p.resolve()


__all__ = [
    "get_resume_summary",
    "load_resume_json",
    "parse_from_js_script",
    "save_resume_json",
]
