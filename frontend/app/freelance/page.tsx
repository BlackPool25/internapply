"use client";

import { Container, Title, Text, Card, Badge, Skeleton, Stack, Group, Anchor, Alert } from "@mantine/core";
import { DataTable } from "mantine-datatable";
import { AlertCircle, ExternalLink } from "lucide-react";
import { useMemo } from "react";
import { useFreelanceFeed } from "@/lib/api";
import { AppLayout } from "@/components/AppLayout";

export default function FreelancePage() {
  const { data, isLoading, isError, error } = useFreelanceFeed();

  const records = useMemo(() => data ?? [], [data]);

  const columns = useMemo(() => [
    {
      accessor: "title",
      title: "Title",
      render: (r: Record<string, unknown>) => (
        <Text fw={600} size="sm" maw={260} truncate>
          {(r.title as string) ?? "Untitled"}
        </Text>
      ),
    },
    {
      accessor: "company",
      title: "Client",
      render: (r: Record<string, unknown>) => (
        <Text size="sm" c="dimmed">{(r.company as string) ?? "—"}</Text>
      ),
    },
    {
      accessor: "source_ats",
      title: "Source",
      render: (r: Record<string, unknown>) => (
        <Badge variant="light" color="pink" size="sm">
          {(r.source_ats as string) ?? "freelance"}
        </Badge>
      ),
    },
    {
      accessor: "budget",
      title: "Budget",
      render: (r: Record<string, unknown>) => (
        <Text size="xs">{(r.budget as string) ?? "—"}</Text>
      ),
    },
    {
      accessor: "url",
      title: "Link",
      render: (r: Record<string, unknown>) =>
        r.url ? (
          <Anchor href={r.url as string} target="_blank" size="xs">
            Open <ExternalLink size={10} style={{ display: "inline", verticalAlign: "middle" }} />
          </Anchor>
        ) : (
          <Text size="xs" c="dimmed">—</Text>
        ),
    },
  ], []);

  return (
    <AppLayout>
      <Container fluid>
        <Group justify="space-between" mb="lg">
          <div>
            <Title order={2}>Freelance Feed</Title>
            <Text size="sm" c="dimmed">Read-only feed: Freelancer RSS · Internshala freelance · Upwork webhook</Text>
          </div>
          <Badge variant="light" color="pink">freelance</Badge>
        </Group>

        {isError && (
          <Alert icon={<AlertCircle size={16} />} title="Feed unavailable" color="yellow" mb="lg">
            {error instanceof Error ? error.message : "Freelance feed not available yet."}
          </Alert>
        )}

        {isLoading ? (
          <Stack gap="sm">
            {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} h={48} radius="md" />)}
          </Stack>
        ) : (
          <Card withBorder padding="md" radius="md">
            <DataTable
              columns={columns as unknown as never[]}
              records={records as unknown as never[]}
              noRecordsText="No freelance opportunities yet — feed will appear when data is available."
              withTableBorder={false}
              highlightOnHover
              pinFirstColumn
              idAccessor="id"
            />
          </Card>
        )}
      </Container>
    </AppLayout>
  );
}
