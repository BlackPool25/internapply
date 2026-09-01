"use client";

import { useMemo } from "react";
import {
  Container,
  Group,
  Title,
  Text,
  Card,
  Badge,
  TextInput,
  Select,
  Button,
  Stack,
  Skeleton,
  Tooltip,
  Alert,
  Box,
  Switch,
  NumberInput,
  SimpleGrid,
} from "@mantine/core";
import { DataTable } from "mantine-datatable";
import {
  Search,
  RefreshCw,
  AlertCircle,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useQueryState, parseAsString, parseAsInteger, parseAsArrayOf, parseAsBoolean } from "nuqs";
import { useDebouncedValue } from "@mantine/hooks";
import { useOpportunities } from "@/lib/api";
import { AppLayout } from "@/components/AppLayout";
import type { Opportunity } from "@/lib/types";

// ── Design tokens: source badge colors ─────────────────
// ATS blue, Hirist purple, Unstop orange, Internshala teal, JobSpy green, LinkedIn navy, 999 muted, freelance pink, Arbeitnow gray
const SOURCE_BADGE: Record<string, { color: string; label: string }> = {
  greenhouse: { color: "blue", label: "Greenhouse" },
  lever: { color: "blue", label: "Lever" },
  ashby: { color: "blue", label: "Ashby" },
  workday: { color: "blue", label: "Workday" },
  smartrecruiters: { color: "blue", label: "SmartRecruiters" },
  ats: { color: "blue", label: "ATS" },
  hirist: { color: "violet", label: "Hirist" },
  Hirist: { color: "violet", label: "Hirist" },
  unstop: { color: "orange", label: "Unstop" },
  Unstop: { color: "orange", label: "Unstop" },
  internshala: { color: "teal", label: "Internshala" },
  Internshala: { color: "teal", label: "Internshala" },
  jobspy: { color: "green", label: "JobSpy" },
  JobSpy: { color: "green", label: "JobSpy" },
  linkedin: { color: "indigo", label: "LinkedIn" },
  LinkedIn: { color: "indigo", label: "LinkedIn" },
  "999": { color: "gray", label: "999" },
  freelance: { color: "pink", label: "Freelance" },
  Freelancer: { color: "pink", label: "Freelancer" },
  internshala_freelance: { color: "pink", label: "Intl. Freelance" },
  upwork: { color: "pink", label: "Upwork" },
  Upwork: { color: "pink", label: "Upwork" },
  arbeitnow: { color: "gray", label: "Arbeitnow" },
  Arbeitnow: { color: "gray", label: "Arbeitnow" },
};

function sourceBadgeMeta(src?: string | null) {
  if (!src) return { color: "gray", label: "Unknown" };
  const k = src.toLowerCase().trim();
  if (SOURCE_BADGE[src]) return SOURCE_BADGE[src];
  if (SOURCE_BADGE[k]) return SOURCE_BADGE[k];
  return { color: "gray", label: src };
}

function DriftDot({ drift, changeLog }: { drift?: string | null; changeLog?: unknown }) {
  let kind: string | null = drift ?? null;
  if (!kind && changeLog && typeof changeLog === "object") {
    const cl = changeLog as Record<string, unknown>;
    const v = (cl.status ?? cl.kind ?? cl.drift) as string | undefined;
    if (v) kind = v;
  }
  if (!kind) return <Box w={8} h={8} style={{ borderRadius: 999, background: "transparent", display: "inline-block" }} />;
  const normalized = String(kind).toLowerCase();
  let color = "gray";
  let label = kind;
  if (normalized === "new") { color = "green"; label = "new"; }
  else if (normalized === "changed" || normalized === "updated") { color = "yellow"; label = "changed"; }
  else if (normalized === "gone" || normalized === "removed" || normalized === "closed") { color = "red"; label = "gone"; }
  else return <Box w={8} h={8} style={{ borderRadius: 999, background: "transparent", display: "inline-block" }} />;
  return (
    <Tooltip label={label}>
      <Box
        w={10}
        h={10}
        style={{
          borderRadius: 999,
          background: color === "green" ? "var(--mantine-color-green-6)" : color === "yellow" ? "var(--mantine-color-yellow-5)" : "var(--mantine-color-red-6)",
          display: "inline-block",
          border: "1px solid var(--mantine-color-default-border)",
        }}
      />
    </Tooltip>
  );
}

const TIER_OPTIONS = [
  { value: "", label: "All tiers" },
  { value: "A", label: "Tier A" },
  { value: "B", label: "Tier B" },
  { value: "C", label: "Tier C" },
];

const SOURCE_FILTER_OPTIONS = [
  { value: "greenhouse", label: "Greenhouse (ATS)" },
  { value: "hirist", label: "Hirist" },
  { value: "unstop", label: "Unstop" },
  { value: "internshala", label: "Internshala" },
  { value: "jobspy", label: "JobSpy" },
  { value: "linkedin", label: "LinkedIn" },
  { value: "freelance", label: "Freelance" },
  { value: "arbeitnow", label: "Arbeitnow" },
  { value: "999", label: "999" },
];

const POSTED_OPTIONS = [
  { value: "", label: "Any time" },
  { value: "24h", label: "Last 24h" },
  { value: "7d", label: "Last 7 days" },
  { value: "14d", label: "Last 14 days" },
  { value: "30d", label: "Last 30 days" },
];

const PAGE_SIZE = 10;

export default function OpportunitiesPage() {
  const router = useRouter();

  // ── nuqs filters ── shallow:false so URL updates push state, reset page=1 on any filter change
  const [tier, setTier] = useQueryState("tier", parseAsString.withOptions({ shallow: false }).withDefault(""));
  const [source, setSource] = useQueryState("source", parseAsArrayOf(parseAsString).withOptions({ shallow: false }).withDefault([]));
  const [qRaw, setQRaw] = useQueryState("q", parseAsString.withOptions({ shallow: false }).withDefault(""));
  const [stipendGteRaw, setStipendGteRaw] = useQueryState("stipend_gte", parseAsString.withOptions({ shallow: false }).withDefault(""));
  const [remote, setRemote] = useQueryState("remote", parseAsBoolean.withOptions({ shallow: false }));
  const [postedWithin, setPostedWithin] = useQueryState("posted_within", parseAsString.withOptions({ shallow: false }).withDefault(""));
  const [verifierGteRaw, setVerifierGteRaw] = useQueryState("verifier_gte", parseAsString.withOptions({ shallow: false }).withDefault(""));
  const [page, setPage] = useQueryState("page", parseAsInteger.withOptions({ shallow: false }).withDefault(1));
  const stipendGte = stipendGteRaw ? parseInt(stipendGteRaw, 10) : null;
  const verifierGte = verifierGteRaw ? parseInt(verifierGteRaw, 10) : null;
  const setStipendGte = (v: number | null) => setStipendGteRaw(v != null ? String(v) : "");
  const setVerifierGte = (v: number | null) => setVerifierGteRaw(v != null ? String(v) : "");

  // 400ms debounce on q
  const [debouncedQ] = useDebouncedValue(qRaw, 400);

  // Build filters for TanStack query
  const filters = useMemo(() => ({
    tier: tier || null,
    source: source.length ? source : null,
    stipend_gte: stipendGte,
    remote: remote,
    posted_within: postedWithin || null,
    verifier_gte: verifierGte,
    q: debouncedQ || null,
    page,
  }), [tier, source, stipendGte, remote, postedWithin, verifierGte, debouncedQ, page]);

  // Also location filter not in spec explicitly? keeping q + existing but add location via q

  const { data: opportunities, isLoading, isError, error } = useOpportunities(filters as unknown as Record<string, unknown> as Parameters<typeof useOpportunities>[0]);

  // Client-side fallback filtering for mock data that ignores server query (ensures smoke test works offline)
  const filtered = useMemo(() => {
    if (!opportunities) return [];
    return opportunities.filter((o) => {
      if (debouncedQ) {
        const hay = `${o.company} ${o.role} ${o.location} ${o.source_ats ?? o.source}`.toLowerCase();
        if (!hay.includes(debouncedQ.toLowerCase())) return false;
      }
      if (source.length && source.length > 0) {
        const src = (o.source_ats ?? o.source ?? "").toLowerCase();
        if (!source.some((s) => src.includes(s.toLowerCase()))) return false;
      }
      // tier client fallback if server not filtering
      if (tier && (o as unknown as Record<string, unknown>).tier !== tier) {
        // allow if no tier field then skip filtering
        if ((o as unknown as Record<string, unknown>).tier != null) return false;
      }
      if (verifierGte != null && (o.verifier_score ?? o.matchScore ?? 0) < verifierGte) return false;
      if (stipendGte != null && (o.stipend ?? 0) < stipendGte) {
        if (o.stipend != null) return false;
      }
      if (remote === true && o.remote === false) return false;
      return true;
    });
  }, [opportunities, debouncedQ, source, tier, verifierGte, stipendGte, remote]);

  const paginated = useMemo(
    () => filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [filtered, page]
  );

  // per-source counts (from fetched opportunities, before pagination)
  const perSourceCounts = useMemo(() => {
    const m: Record<string, number> = {};
    (opportunities ?? []).forEach((o) => {
      const key = (o.source_ats ?? o.source ?? "other").toString().toLowerCase();
      m[key] = (m[key] ?? 0) + 1;
    });
    return m;
  }, [opportunities]);

  const resetPage = () => setPage(1);

  const columns = useMemo(
    () => [
      {
        accessor: "drift",
        title: "",
        width: 36,
        render: (record: Opportunity) => (
          <DriftDot drift={(record as unknown as Record<string, unknown>).drift as string} changeLog={record.change_log} />
        ),
      },
      {
        accessor: "company",
        title: "Company",
        sortable: true,
        render: (record: Opportunity) => (
          <Text fw={600} size="sm" truncate maw={160}>
            {record.company}
          </Text>
        ),
      },
      {
        accessor: "role",
        title: "Role",
        sortable: true,
        render: (record: Opportunity) => (
          <Text size="sm" c="dimmed" truncate maw={200}>
            {record.role}
          </Text>
        ),
      },
      {
        accessor: "source_ats",
        title: "Source",
        sortable: true,
        render: (record: Opportunity) => {
          const meta = sourceBadgeMeta((record.source_ats ?? record.source) as string);
          return (
            <Badge variant="light" color={meta.color} size="sm">
              {meta.label}
            </Badge>
          );
        },
      },
      {
        accessor: "tier",
        title: "Tier",
        sortable: true,
        width: 70,
        render: (record: Opportunity) => {
          const t = (record as unknown as Record<string, unknown>).tier as string | undefined;
          if (!t) return <Text size="xs" c="dimmed">—</Text>;
          return <Badge variant="outline" size="xs">{t}</Badge>;
        },
      },
      {
        accessor: "verifier",
        title: "Verifier",
        sortable: true,
        textAlign: "center" as const,
        width: 90,
        render: (record: Opportunity) => {
          const v = record.verifier_score ?? record.matchScore;
          if (v == null) return <Text size="xs" c="dimmed">—</Text>;
          const color = v >= 80 ? "green" : v >= 70 ? "yellow" : "red";
          return (
            <Badge variant="light" color={color} size="sm">
              {v}%
            </Badge>
          );
        },
      },
      {
        accessor: "location",
        title: "Location",
        sortable: true,
        visibleMediaQuery: "(min-width: 768px)",
        render: (record: Opportunity) => (
          <Text size="xs" c="dimmed" truncate maw={120}>{record.location}{record.remote ? " · Remote" : ""}</Text>
        ),
      },
      {
        accessor: "date",
        title: "Posted",
        sortable: true,
        render: (record: Opportunity) => {
          const d = record.posted_at ?? record.date;
          return (
            <Text size="xs" c="dimmed">
              {d ? new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "—"}
            </Text>
          );
        },
      },
    ],
    []
  );

  return (
    <AppLayout>
      <Container fluid>
        <Group justify="space-between" mb="lg">
          <div>
            <Title order={2}>Opportunities</Title>
            <Text size="sm" c="dimmed">
              Track and manage your internship applications
            </Text>
          </div>
          <Button
            variant="subtle"
            color="gray"
            leftSection={<RefreshCw size={16} />}
            onClick={() => window.location.reload()}
          >
            Refresh
          </Button>
        </Group>

        {/* Per-source counts */}
        {Object.keys(perSourceCounts).length > 0 && (
          <Group gap={8} mb="md" wrap="wrap">
            {Object.entries(perSourceCounts)
              .sort((a, b) => b[1] - a[1])
              .map(([src, count]) => {
                const meta = sourceBadgeMeta(src);
                return (
                  <Badge key={src} variant="light" color={meta.color} size="sm">
                    {meta.label}: {count}
                  </Badge>
                );
              })}
          </Group>
        )}

        {isError && (
          <Alert icon={<AlertCircle size={16} />} title="Backend API unavailable" color="red" mb="lg">
            {error instanceof Error ? error.message : "Backend API is not available. Start the Docker containers first."}
          </Alert>
        )}

        {/* Full filter bar */}
        <Card withBorder padding="md" radius="md" mb="lg">
          <Stack gap="sm">
            <Group gap="md" align="end" wrap="wrap">
              <TextInput
                placeholder="Search roles, companies..."
                leftSection={<Search size={16} />}
                value={qRaw}
                onChange={(e) => {
                  setQRaw(e.currentTarget.value);
                  resetPage();
                }}
                style={{ flex: 1, minWidth: 200 }}
              />
              <Select
                label="Tier"
                data={TIER_OPTIONS}
                value={tier}
                onChange={(v) => {
                  setTier(v ?? "");
                  resetPage();
                }}
                placeholder="All tiers"
                clearable
                w={140}
              />
              <Select
                label="Source"
                data={SOURCE_FILTER_OPTIONS}
                value={source[0] ?? ""}
                onChange={(v) => {
                  if (!v) setSource([]);
                  else setSource([v]);
                  resetPage();
                }}
                placeholder="All sources"
                clearable
                w={180}
              />
              <Select
                label="Posted within"
                data={POSTED_OPTIONS}
                value={postedWithin}
                onChange={(v) => {
                  setPostedWithin(v ?? "");
                  resetPage();
                }}
                placeholder="Any time"
                clearable
                w={160}
              />
            </Group>

            <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }} spacing="md">
              <NumberInput
                label="Stipend ≥ (₹)"
                placeholder="e.g. 5000"
                value={stipendGte ?? undefined}
                onChange={(v) => {
                  const n = typeof v === "number" ? v : v === "" ? null : Number(v);
                  setStipendGte(Number.isFinite(n as number) ? (n as number) : null);
                  resetPage();
                }}
                min={0}
              />
              <NumberInput
                label="Verifier ≥"
                placeholder="e.g. 80"
                value={verifierGte ?? undefined}
                onChange={(v) => {
                  const n = typeof v === "number" ? v : v === "" ? null : Number(v);
                  setVerifierGte(Number.isFinite(n as number) ? (n as number) : null);
                  resetPage();
                }}
                min={0}
                max={100}
              />
              <Box>
                <Text size="xs" fw={500} mb={6}>Remote only</Text>
                <Switch
                  checked={remote === true}
                  onChange={(e) => {
                    setRemote(e.currentTarget.checked ? true : null);
                    resetPage();
                  }}
                  label={remote ? "Yes" : "Any"}
                />
              </Box>
              <Group align="end">
                {(tier || source.length || qRaw || stipendGte != null || remote || postedWithin || verifierGte != null) && (
                  <Button
                    variant="subtle"
                    color="gray"
                    onClick={() => {
                      setTier("");
                      setSource([]);
                      setQRaw("");
                      setStipendGte(null);
                      setRemote(null);
                      setPostedWithin("");
                      setVerifierGte(null);
                      setPage(1);
                    }}
                  >
                    Clear filters
                  </Button>
                )}
                <Text size="xs" c="dimmed">
                  Drift: <Box component="span" w={8} h={8} style={{ display: "inline-block", borderRadius: 999, background: "var(--mantine-color-green-6)", verticalAlign: "middle" }} /> new{" "}
                  <Box component="span" w={8} h={8} style={{ display: "inline-block", borderRadius: 999, background: "var(--mantine-color-yellow-5)", verticalAlign: "middle" }} /> changed{" "}
                  <Box component="span" w={8} h={8} style={{ display: "inline-block", borderRadius: 999, background: "var(--mantine-color-red-6)", verticalAlign: "middle" }} /> gone
                </Text>
              </Group>
            </SimpleGrid>
          </Stack>
        </Card>

        {isLoading ? (
          <Stack gap="sm">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} h={48} radius="md" />
            ))}
          </Stack>
        ) : (
          <Card withBorder padding="md" radius="md">
            <DataTable
              columns={columns}
              records={paginated}
              totalRecords={filtered.length}
              recordsPerPage={PAGE_SIZE}
              page={page}
              onPageChange={setPage}
              onRowClick={({ record }: { record: Opportunity }) =>
                router.push(`/opportunities/${record.id}`)
              }
              pinFirstColumn
              highlightOnHover
              withTableBorder={false}
              withColumnBorders={false}
              borderRadius="sm"
              verticalSpacing="sm"
              horizontalSpacing="md"
              fetching={isLoading}
              noRecordsText="No opportunities found"
              idAccessor="id"
              textSelectionDisabled
            />
          </Card>
        )}
      </Container>
    </AppLayout>
  );
}
