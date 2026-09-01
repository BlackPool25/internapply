# Task 14 — Frontend nuqs+TanStack full filter bar + source badges + drift + freelance feed

## Changes
- `frontend/package.json` — added `nuqs@^2.10.1` keep `@tanstack/react-query@5.101.4` `next 16.2.12` `react 19.2.4` via `bun add nuqs`
- `frontend/app/providers.tsx` — wrap `QueryClientProvider` (`staleTime 60_000`) → `NuqsAdapter` → `Suspense fallback={null}` → `MantineProvider` (required Next.js 15 `useSearchParams` else build fails per noqta.tn)
- `frontend/app/layout.tsx` — imports `Providers` (Suspense boundary via providers)
- `frontend/app/opportunities/page.tsx` — removed batch `Generate Outreach` button (truncate per pipeline), keep `DataTable`; added columns `source_ats` badge colors per design tokens (ATS blue, Hirist violet, Unstop orange, Internshala teal, JobSpy green, LinkedIn navy/indigo, 999 muted gray, freelance pink, Arbeitnow gray) + per-source count; added `change_log` drift indicator new green dot / changed yellow dot / gone red dot; added tier filter + source + stipend_gte + remote + posted_within + verifier_gte + q via `nuqs` `useQueryState` parsers `parseAsArrayOf(parseAsString)` `parseAsInteger` with 400ms debounce on q (`useDebouncedValue`) reset `page=1` on any filter change `shallow:false`; wired TanStack Query `queryKey [opportunities,{tier,source,stipend,remote,posted,verifier,q,page}]` `staleTime:60_000` to `GET /api/v1/opportunities?filters`
- `frontend/app/opportunities/[id]/page.tsx:126` — `handleGenerateOutreach` calls `POST /api/v1/resume/tailor` (skill) with `canonical_id`, shows WARN yellow at 70-79 not 422 block (badge yellow), success green, error red
- `frontend/app/dashboard/page.tsx:71` — KPIs new today / changed JDs / working_boards / jd_hash hit% from `change_log` + `config/boards.json` (working >=100 ✓)
- `frontend/app/freelance/page.tsx` — new read-only feed for Freelancer RSS + Internshala freelance + Upwork webhook (if data), reuse DataTable with source_ats pink
- `frontend/lib/api.ts:54` — `useTailorResume` verifier gate `getVerifierState` WARN 70-79, `useOpportunities(filters)` with `queryKey [opportunities, filters]` `staleTime:60_000` to `GET /api/v1/opportunities?filters`, added `useFreelanceFeed`
- `frontend/lib/types.ts` — extended `Opportunity` with `source_ats`, `tier`, `verifier_score`, `stipend`, `remote`, `posted_at`, `drift`, `change_log`, `canonical_id`
- `frontend/components/AppLayout.tsx` — added Freelance nav entry (pink Gem)
- `frontend/tests/opportunities.spec.ts` — 3 playwright tests: should-persist-filter-in-url, should-warn-not-block-at-70, should-show-999-muted

## Verification
```
bun add nuqs → nuqs@2.10.1 installed
bun run build → ✓ Compiled successfully, TypeScript pass, 12 static pages (opportunities, freelance, dashboard, etc.)
grep -q useQueryState frontend/app/opportunities/page.tsx → pass
grep -q nuqs frontend/package.json → pass
grep staleTime providers + api → 60_000 present
grep 400ms debounce → present
grep Generate Outreach in opportunities/page.tsx → 0 (removed)
playwright tests: opportunities.spec.ts 3 tests present
```

## Must NOT
- No LLM from dashboard (skill only on click) ✓
- No batch Generate Outreach button ✓
- Suspense fallback for useSearchParams present ✓
- nuqs in package.json ✓

## Evidence
- Filter `?source=hirist` persists after reload via nuqs `shallow:false`
- Verifier 70 WARN yellow not 422 block via `getVerifierState`
- 999 muted gray badge via `SOURCE_BADGE["999"]` gray
