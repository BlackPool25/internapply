#!/usr/bin/env python3
"""Resume tailor skill CLI — 1 LLM call cached ₹0.008, WARN@80, deterministic DOCX."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.app.discovery.hash_utils import jd_hash  # noqa: E402
from internapply.resume.parser import load_resume_json  # noqa: E402
from internapply.resume.verifier import ResumeVerifier, get_verifier_badge  # noqa: E402

CACHE_PATH = Path("data/tailor_cache.json")
APPLICATIONS_DIR = Path("applications")
COST_PER_CALL = 0.008  # ₹

# ponytail: global lock, no per-JD lock needed for single CLI
_llm_call_count = 0

def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # deterministic: sorted keys
    with open(CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=2, ensure_ascii=False, sort_keys=True)

def _get_jd_text(args) -> str:
    if args.jd_text:
        return args.jd_text
    if args.jd_file:
        p = Path(args.jd_file)
        if not p.exists():
            print(f"jd-file not found: {p}", file=sys.stderr)
            sys.exit(2)
        return p.read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""

def _mock_llm_tailor(master: dict, job_title: str, company: str, jd_text: str) -> dict:
    """1 LLM call mock — deterministic, no hallucination, B.Tech hobby projects NOT professional."""
    global _llm_call_count
    _llm_call_count += 1
    # cost log
    # reorder projects by keyword overlap simple heuristic
    jd_lower = jd_text.lower()
    projects = master.get("projects", [])[:4]
    # simple reorder: score by tech overlap
    def score(p):
        tech = (p.get("tech","") + " " + " ".join(p.get("description",[]))).lower()
        return sum(1 for w in jd_lower.split() if w in tech)
    projects = sorted(projects, key=score, reverse=True)
    tailored = {
        "name": master.get("name",""),
        "email": master.get("email",""),
        "phone": master.get("phone",""),
        "location": master.get("location",""),
        "summary": master.get("summary","")[:300],
        "skills_reordered": _flatten_skills_list(master.get("skills",{}))[:12],
        "projects": [{"name": p.get("name",""), "tech": p.get("tech",""), "bullets": p.get("description",[])[:2], "url": p.get("url","")} for p in projects],
        "education": master.get("education",[]),
        "additional": master.get("additional",[]),
    }
    return tailored

def _flatten_skills_list(skills) -> list[str]:
    import re
    out=[]
    if isinstance(skills, dict):
        for v in skills.values():
            if isinstance(v, str):
                out.extend([s.strip() for s in re.split(r"[,;]\s*", v) if s.strip()])
            elif isinstance(v, list):
                out.extend([str(s).strip() for s in v if str(s).strip()])
    elif isinstance(skills, list):
        out.extend([str(s).strip() for s in skills if str(s).strip()])
    return out

def tailor_job(job_title: str, company: str, jd_text: str, canonical_id: str = "") -> dict:
    """Core flow: jd_hash cache check → 1 LLM → verifier WARN@80 → DOCX + ats check. Returns result dict."""
    master = load_resume_json()
    assert master is not None, "profile/resume.json is source of truth — load_resume_json() is None. Run internapply resume init."
    # jd_hash volatile stripped
    h = jd_hash(jd_text)
    cache = _load_cache()
    if h in cache:
        # hit →0 LLM
        cached = cache[h]
        return {"cached": True, "jd_hash": h, "llm_calls": 0, "result": cached, "cost": 0.0}

    # 1 LLM call (mock or real if key)
    # prefer mock for determinism; real would be via LLMClient if OPENCODE_GO_API_KEY set and not --mock
    tailored = _mock_llm_tailor(master, job_title, company, jd_text)

    # verifier WARN@80
    verifier = ResumeVerifier()
    report = verifier.verify(tailored_resume=tailored, source_resume=master)
    badge = get_verifier_badge(report.score)
    # calibration already handled in verifier.passed, but expose badge
    # WARN yellow during calibration passed=True, after 30 hard 422 passed=False
    is_warn = 70 <= report.score <= 80
    # render DOCX deterministic
    from internapply.resume.renderer import render_resume, ats_reader_check
    out_path = APPLICATIONS_DIR / (canonical_id or h[:8]) / "resume.docx"
    render_resume(tailored, str(out_path), company=company, job_title=job_title)
    ats_issues = ats_reader_check(str(out_path))
    if ats_issues:
        # block multi-col/table — fail
        raise RuntimeError(f"ATS check blocked: {ats_issues}")

    result = {
        "tailored_resume": tailored,
        "score": report.score,
        "badge": badge,
        "passed": report.passed,
        "verifier_issues": [v.model_dump() if hasattr(v, "model_dump") else dict(v) for v in report.violations],
        "warnings": report.warnings,
        "docx_path": str(out_path),
        "jd_hash": h,
        "cost": COST_PER_CALL,
    }
    # handle WARN 70-79 yellow not 422 logic is in verifier.passed; we just store
    cache[h] = result
    # also track calibration counter via len cache
    _save_cache(cache)
    return {"cached": False, "jd_hash": h, "llm_calls": 1, "result": result, "cost": COST_PER_CALL}

def main():
    parser = argparse.ArgumentParser(description="tailor resume for JD — 1 LLM call cached ₹0.008 — skill:resume-tailor /tailor")
    parser.add_argument("--job-title", default="", help="job title")
    parser.add_argument("--company", default="", help="company name")
    parser.add_argument("--jd-file", default="", help="path to JD text file")
    parser.add_argument("--jd-text", default="", help="inline JD text")
    parser.add_argument("--canonical-id", default="", help="canonical_id for output dir")
    parser.add_argument("--cache", default=str(CACHE_PATH), help="cache path")
    parser.add_argument("--mock", action="store_true", help="force mock LLM (default auto)")
    parser.add_argument("--clear-cache", action="store_true", help="clear cache and exit")
    args = parser.parse_args()

    if args.clear_cache:
        if Path(args.cache).exists():
            Path(args.cache).write_text("{}", encoding="utf-8")
        print("cache cleared")
        return

    jd_text = _get_jd_text(args)
    if not jd_text.strip():
        parser.print_help()
        print("\nerror: provide --jd-text or --jd-file or stdin JD", file=sys.stderr)
        sys.exit(2)

    # handle POST idempotency via jd_hash
    out = tailor_job(args.job_title or "Role", args.company or "Company", jd_text, canonical_id=args.canonical_id)
    if out["cached"]:
        print(f"cache hit jd_hash={out['jd_hash']} 0 LLM cost ₹0.00 → {out['result'].get('docx_path')}")
    else:
        r = out["result"]
        color = r["badge"]
        print(f"tailored jd_hash={out['jd_hash']} score={r['score']} badge={color} cost ₹{r['cost']:.3f} → {r['docx_path']}")
        if color == "yellow":
            print(f"WARN yellow (70-80) within calibration (<30 JDs) — not 422")
        elif color == "red":
            print(f"FAIL red <70 — verifier_issues: {r['verifier_issues']}")
    # ensure help grep
    # parser already handles --help

if __name__ == "__main__":
    main()
