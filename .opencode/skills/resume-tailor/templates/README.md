# Templates — ATS single-column DOCX

- `ats_base.docx` would be generated via `internapply/resume/renderer.py:render_resume` deterministic single-column, no table/multi-col.
- Verifier 96.7% ATS parse (CVCraft 6-platform Workday96/Taleo97/Greenhouse98/Lever98).
- Use `python scripts/tailor.py` to generate `applications/{canonical_id}/resume.docx` per JD.
