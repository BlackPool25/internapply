"use client";

import {
  Container,
  SimpleGrid,
  Card,
  Group,
  Text,
  Title,
  ThemeIcon,
  Stack,
  Badge,
  Skeleton,
  Box,
  Paper,
  Alert,
} from "@mantine/core";
import {
  Briefcase,
  Clock,
  Layers,
  Mail,
  ArrowRight,
  AlertCircle,
  CheckCircle2,
  Send,
  FileText,
  TrendingUp,
  Activity,
  Database,
  Hash,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { useDashboardStats, useOpportunities, useRecentActivity } from "@/lib/api";
import { AppLayout } from "@/components/AppLayout";


const STATUS_ICONS: Record<string, React.ElementType> = {
  pending_review: Clock,
  batch_ready: Layers,
  saved: AlertCircle,
  applied: Send,
};

const STATUS_COLORS: Record<string, string> = {
  pending_review: "yellow",
  batch_ready: "teal",
  saved: "gray",
  applied: "blue",
  interview_scheduled: "violet",
  rejected: "red",
  offer: "green",
};

function getTimeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function driftStats(opps: unknown[] | undefined) {
  if (!opps) return { newToday: 0, changed: 0, jdHit: 0 };
  let newToday = 0;
  let changed = 0;
  let withHash = 0;
  let hit = 0;
  const today = new Date().toISOString().slice(0, 10);
  for (const o of opps) {
    const r = o as Record<string, unknown>;
    const cl = r.change_log as Record<string, unknown> | null | undefined;
    const drift = (r.drift ?? cl?.status ?? cl?.kind) as string | undefined;
    const d = (r.posted_at ?? r.date) as string | undefined;
    if (drift === "new" && d?.slice(0, 10) === today) newToday++;
    // alternative: if no drift but posted today count as new
    if (drift === "changed" || drift === "updated") changed++;
    if (r.jd_hash ?? cl?.jd_hash) {
      withHash++;
      if (cl?.jd_hash) hit++;
    } else if (cl && Object.keys(cl).length > 0) {
      withHash++;
      hit++;
    }
  }
  // fallback: if no drift fields, estimate newToday as posted today
  if (newToday === 0 && opps.length) {
    newToday = opps.filter((o) => {
      const r = o as Record<string, unknown>;
      const d = (r.posted_at ?? r.date) as string | undefined;
      return d?.slice(0, 10) === today;
    }).length;
  }
  const pct = withHash ? Math.round((hit / withHash) * 100) : 0;
  return { newToday, changed, jdHit: pct };
}

export default function DashboardPage() {
  const router = useRouter();
  const { data: stats, isLoading: statsLoading, isError: statsError, error: statsErrorObj } = useDashboardStats();
  const { data: opportunities, isLoading: oppsLoading, isError: oppsError } = useOpportunities();
  const { data: activity, isLoading: activityLoading, isError: activityError } = useRecentActivity();

  const apiError = statsError || oppsError || activityError;
  const apiErrorMessage = apiError
    ? (statsErrorObj instanceof Error ? statsErrorObj.message : "Backend API is not available. Start the Docker containers first.")
    : null;

  const drift = useMemo(() => driftStats(opportunities as unknown[]), [opportunities]);
  const workingBoards = stats?.workingBoards ?? 0;

  const KPI_CARDS = [
    {
      label: "New today",
      value: stats?.newToday ?? drift.newToday,
      icon: TrendingUp,
      color: "green",
      hint: "from change_log",
    },
    {
      label: "Changed JDs",
      value: stats?.changedJds ?? drift.changed,
      icon: Activity,
      color: "yellow",
      hint: "drift changed",
    },
    {
      label: "Working boards",
      value: stats?.workingBoards ?? workingBoards,
      suffix: workingBoards >= 100 ? "✓" : "",
      icon: Database,
      color: workingBoards >= 100 ? "green" : "gray",
      hint: `${workingBoards} ≥100 ok`,
    },
    {
      label: "JD hash hit%",
      value: `${stats?.jdHashHitPct ?? drift.jdHit}%`,
      icon: Hash,
      color: "blue",
      hint: "change_log",
    },
    {
      label: "Total Opportunities",
      value: stats?.totalOpportunities ?? opportunities?.length ?? 0,
      icon: Briefcase,
      color: "blue",
    },
    {
      label: "Pending Review",
      value: stats?.pendingReview ?? 0,
      icon: Clock,
      color: "yellow",
    },
    {
      label: "Batch Ready",
      value: stats?.batchReady ?? 0,
      icon: Layers,
      color: "teal",
    },
    {
      label: "Emails to Send",
      value: stats?.emailsToSend ?? 0,
      icon: Mail,
      color: "violet",
    },
  ];

  const pendingItems =
    opportunities?.filter(
      (o) => o.status === "pending_review" || o.status === "batch_ready"
    ) ?? [];

  return (
    <AppLayout>
      <Container fluid>
        <Group justify="space-between" mb="xl">
          <div>
            <Title order={2}>Dashboard</Title>
            <Text size="sm" c="dimmed">
              Overview of your internship application pipeline
            </Text>
          </div>
        </Group>

        {apiError && (
          <Alert
            icon={<AlertCircle size={16} />}
            title="Backend API unavailable"
            color="red"
            mb="lg"
            withCloseButton
            onClose={() => {}}
          >
            {apiErrorMessage}
          </Alert>
        )}

        <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} mb="xl">
          {KPI_CARDS.map((kpi) => (
            <Card
              key={kpi.label}
              withBorder
              padding="lg"
              radius="md"
              shadow="sm"
            >
              <Group justify="space-between" mb="xs">
                <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
                  {kpi.label}
                </Text>
                <ThemeIcon variant="light" color={kpi.color} size="lg" radius="md">
                  <kpi.icon size={18} />
                </ThemeIcon>
              </Group>
              {statsLoading && kpi.label.startsWith("New") ? (
                <Skeleton h={36} w={80} />
              ) : (
                <Group gap={6} align="end">
                  <Text fw={700} size="xl" lh={1}>
                    {kpi.value}{" "}
                    {(kpi as unknown as Record<string, string>).suffix ?? ""}
                  </Text>
                  {kpi.hint && (
                    <Text size="xs" c="dimmed">
                      {kpi.hint}
                    </Text>
                  )}
                </Group>
              )}
            </Card>
          ))}
        </SimpleGrid>

        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
          <Box>
            <Group justify="space-between" mb="md">
              <Title order={4}>What Needs Attention</Title>
              <Badge
                variant="light"
                color="blue"
                style={{ cursor: "pointer" }}
                onClick={() => router.push("/opportunities")}
              >
                View all
              </Badge>
            </Group>

            {oppsLoading ? (
              <Stack gap="sm">
                <Skeleton h={80} radius="md" />
                <Skeleton h={80} radius="md" />
                <Skeleton h={80} radius="md" />
              </Stack>
            ) : pendingItems.length === 0 ? (
              <Paper withBorder p="xl" radius="md" ta="center" c="dimmed">
                <CheckCircle2 size={36} style={{ margin: "0 auto 8px" }} />
                <Text size="sm">Nothing needs attention right now!</Text>
              </Paper>
            ) : (
              <Stack gap="sm">
                {pendingItems.slice(0, 5).map((item) => {
                  const Icon = STATUS_ICONS[item.status] ?? FileText;
                  const color = STATUS_COLORS[item.status] ?? "gray";
                  return (
                    <Card
                      key={item.id}
                      withBorder
                      padding="md"
                      radius="md"
                      style={{ cursor: "pointer" }}
                      onClick={() =>
                        router.push(`/opportunities/${item.id}`)
                      }
                    >
                      <Group justify="space-between" wrap="nowrap">
                        <Group gap="sm" wrap="nowrap">
                          <ThemeIcon variant="light" color={color} size="lg" radius="md">
                            <Icon size={18} />
                          </ThemeIcon>
                          <div style={{ minWidth: 0 }}>
                            <Text size="sm" fw={600} truncate>
                              {item.company}
                            </Text>
                            <Text size="xs" c="dimmed" truncate>
                              {item.role}
                            </Text>
                          </div>
                        </Group>
                        <Group gap="xs" wrap="nowrap">
                          <Badge
                            variant="light"
                            color={color}
                            size="sm"
                            tt="capitalize"
                          >
                            {item.status.replace(/_/g, " ")}
                          </Badge>
                          <ArrowRight size={14} />
                        </Group>
                      </Group>
                    </Card>
                  );
                })}
              </Stack>
            )}
          </Box>

          <Box>
            <Title order={4} mb="md">
              Recent Activity
            </Title>

            {activityLoading ? (
              <Stack gap="sm">
                <Skeleton h={60} radius="md" />
                <Skeleton h={60} radius="md" />
                <Skeleton h={60} radius="md" />
                <Skeleton h={60} radius="md" />
              </Stack>
            ) : (
              <Stack gap="xs">
                {activity?.map((act) => {
                  const iconMap: Record<string, React.ElementType> = {
                    application: Send,
                    status_change: Clock,
                    note: FileText,
                    email: Mail,
                  };
                  const Icon = iconMap[act.type] ?? FileText;
                  return (
                    <Card
                      key={act.id}
                      withBorder
                      padding="sm"
                      radius="md"
                      style={{ cursor: "pointer" }}
                      onClick={() =>
                        router.push(`/opportunities/${act.opportunityId}`)
                      }
                    >
                      <Group gap="sm" wrap="nowrap">
                        <ThemeIcon variant="light" color="gray" size="sm" radius="xl">
                          <Icon size={12} />
                        </ThemeIcon>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <Text size="sm" truncate>
                            {act.message}
                          </Text>
                        </div>
                        <Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>
                          {getTimeAgo(act.timestamp)}
                        </Text>
                      </Group>
                    </Card>
                  );
                })}
              </Stack>
            )}
          </Box>
        </SimpleGrid>
      </Container>
    </AppLayout>
  );
}
