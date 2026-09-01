"use client";

import { use, useState } from "react";
import {
  Container,
  Grid,
  Card,
  Group,
  Text,
  Title,
  Badge,
  Button,
  Stack,
  Skeleton,
  ThemeIcon,
  Divider,
  Paper,
  Anchor,
  TextInput,
  Textarea,
  ActionIcon,
  Tooltip,
  Alert,
  CopyButton,
} from "@mantine/core";
import {
  ArrowLeft,
  Building2,
  MapPin,
  DollarSign,
  Globe,
  Users,
  FileText,
  Mail,
  Plus,
  ExternalLink,
  Edit3,
  Eye,
  CheckCheck,
  Send,
  Linkedin,
  Briefcase,
  Sparkles,
  Loader2,
  Check,
  Copy,
  AlertTriangle,
} from "lucide-react";
import { useRouter } from "next/navigation";
import {
  useOpportunity,
  useTailorResume,
  useCoverLetter,
  getVerifierState,
} from "@/lib/api";
import { AppLayout } from "@/components/AppLayout";
import type { Opportunity } from "@/lib/types";
import { notifications } from "@mantine/notifications";

const STATUS_COLORS: Record<string, string> = {
  saved: "gray",
  applied: "blue",
  pending_review: "yellow",
  batch_ready: "teal",
  interview_scheduled: "violet",
  rejected: "red",
  offer: "green",
  accepted: "emerald",
};

function DetailSkeleton() {
  return (
    <Container fluid>
      <Skeleton h={20} w={120} mb="lg" />
      <Grid>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Skeleton h={400} radius="md" />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Skeleton h={400} radius="md" />
        </Grid.Col>
      </Grid>
    </Container>
  );
}

function OpportunityNotFound() {
  const router = useRouter();
  return (
    <Container fluid>
      <Button
        variant="subtle"
        leftSection={<ArrowLeft size={16} />}
        onClick={() => router.push("/opportunities")}
        mb="lg"
      >
        Back to opportunities
      </Button>
      <Paper withBorder p="xl" radius="md" ta="center">
        <Text size="lg" fw={600} mb="sm">
          Opportunity not found
        </Text>
        <Text size="sm" c="dimmed">
          The opportunity you&apos;re looking for doesn&apos;t exist or has been removed.
        </Text>
      </Paper>
    </Container>
  );
}

export default function OpportunityDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const { data: opportunity, isLoading, isError, error } = useOpportunity(id);

  // ── Outreach generation state ──
  const tailorMutation = useTailorResume();
  const coverLetterMutation = useCoverLetter();
  const [tailoredSummary, setTailoredSummary] = useState<string | null>(null);
  const [generatedSubject, setGeneratedSubject] = useState<string>("");
  const [generatedBody, setGeneratedBody] = useState<string>("");
  const [verifierScore, setVerifierScore] = useState<number | null>(null);

  const handleGenerateOutreach = () => {
    const jobTitle = opportunity?.role ?? "";
    const company = opportunity?.company ?? "";
    const jobDescription =
      opportunity?.researchSummary ?? opportunity?.notes ?? "";
    const contactName = opportunity?.contactName ?? "";
    const canonical_id = (opportunity as unknown as Record<string, unknown>)?.canonical_id as string | undefined ?? opportunity?.id ?? id;

    // Step 1: Tailor the resume via skill (POST /api/v1/resume/tailor) with canonical_id
    tailorMutation.mutate(
      { job_title: jobTitle, company, job_description: jobDescription, canonical_id },
      {
        onSuccess: (tailorData) => {
          setTailoredSummary(tailorData.summary);
          const score = tailorData.verifier_score ?? null;
          setVerifierScore(score);
          const state = getVerifierState(score);
          // WARN 70-79 yellow not blocked, success green, error red
          if (state === "warn") {
            notifications.show({
              title: "WARN: verifier 70-79",
              message: `Tailored with warnings (score: ${score}). Review before sending.`,
              color: "yellow",
            });
          } else if (state === "success") {
            notifications.show({
              title: "Resume tailored",
              message: `Verifier score: ${score}/100`,
              color: "green",
            });
          } else if (score !== null && score < 70) {
            notifications.show({
              title: "Verifier low",
              message: `Score ${score} — needs review but not blocked (only <60 would retry).`,
              color: "red",
            });
          }

          // Step 2: Generate cover letter
          coverLetterMutation.mutate(
            {
              title: jobTitle,
              company,
              jd_summary: jobDescription || "No description available.",
              top_skills: tailorData.skills_reordered,
              summary: tailorData.summary,
              name: contactName,
            },
            {
              onSuccess: (clData) => {
                setGeneratedSubject(
                  `Application for ${jobTitle} Position`,
                );
                setGeneratedBody(clData.letter);
                notifications.show({
                  title: "Outreach generated",
                  message: `Cover letter ready (score: ${clData.humanization_score}/100)`,
                  color: "green",
                });
              },
              onError: (err) => {
                notifications.show({
                  title: "Cover letter failed",
                  message:
                    err instanceof Error ? err.message : "Unknown error",
                  color: "red",
                });
              },
            },
          );
        },
        onError: (err) => {
          notifications.show({
            title: "Resume tailoring failed",
            message: err instanceof Error ? err.message : "Unknown error",
            color: "red",
          });
        },
      },
    );
  };

  const isGenerating = tailorMutation.isPending || coverLetterMutation.isPending;
  const hasGenerated = tailoredSummary !== null || generatedBody !== "";

  if (isLoading) {
    return (
      <AppLayout>
        <DetailSkeleton />
      </AppLayout>
    );
  }

  if (isError) {
    return (
      <AppLayout>
        <Container fluid>
          <Button
            variant="subtle"
            leftSection={<ArrowLeft size={16} />}
            onClick={() => router.push("/opportunities")}
            mb="lg"
          >
            Back to opportunities
          </Button>
          <Alert
            icon={<AlertTriangle size={16} />}
            title="Failed to load opportunity"
            color="red"
          >
            {error instanceof Error
              ? error.message
              : "Backend API is not available. Start the Docker containers first."}
          </Alert>
        </Container>
      </AppLayout>
    );
  }

  if (!opportunity) {
    return (
      <AppLayout>
        <OpportunityNotFound />
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      <Container fluid>
        {/* Back button */}
        <Button
          variant="subtle"
          leftSection={<ArrowLeft size={16} />}
          onClick={() => router.push("/opportunities")}
          mb="lg"
        >
          Back to opportunities
        </Button>

        {/* Header card */}
        <Card withBorder padding="lg" radius="md" mb="lg">
          <Group justify="space-between" align="flex-start">
            <Group gap="lg">
              <ThemeIcon
                size={56}
                radius="md"
                variant="light"
                color="blue"
              >
                <Building2 size={28} />
              </ThemeIcon>
              <div>
                <Group gap="sm" mb={4}>
                  <Title order={3}>{opportunity.company}</Title>
                  <Badge
                    variant="light"
                    color={STATUS_COLORS[opportunity.status] ?? "gray"}
                    size="lg"
                    tt="capitalize"
                  >
                    {opportunity.status.replace(/_/g, " ")}
                  </Badge>
                </Group>
                <Text size="lg" c="dimmed">
                  {opportunity.role}
                </Text>
                <Group gap="md" mt="sm">
                  <Group gap={4}>
                    <MapPin size={14} />
                    <Text size="sm" c="dimmed">
                      {opportunity.location}
                    </Text>
                  </Group>
                  {opportunity.salary && (
                    <Group gap={4}>
                      <DollarSign size={14} />
                      <Text size="sm" c="dimmed">
                        {opportunity.salary}
                      </Text>
                    </Group>
                  )}
                  <Group gap={4}>
                    <ThemeIcon
                      variant="light"
                      color={
                        opportunity.matchScore >= 85
                          ? "green"
                          : opportunity.matchScore >= 70
                            ? "yellow"
                            : "red"
                      }
                      size="sm"
                      radius="xl"
                    >
                      <Briefcase size={10} />
                    </ThemeIcon>
                    <Text size="sm" fw={500}>
                      {opportunity.matchScore}% match
                    </Text>
                  </Group>
                </Group>
              </div>
            </Group>

            <Group gap="xs">
              {opportunity.jobUrl && (
                <Button
                  variant="light"
                  rightSection={<ExternalLink size={14} />}
                  component="a"
                  href={opportunity.jobUrl}
                  target="_blank"
                >
                  View Job
                </Button>
              )}
              <Button
                variant="filled"
                color={hasGenerated ? "green" : "blue"}
                leftSection={
                  isGenerating ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Sparkles size={14} />
                  )
                }
                onClick={handleGenerateOutreach}
                loading={isGenerating}
              >
                {isGenerating
                  ? "Generating…"
                  : hasGenerated
                    ? "Regenerate Outreach"
                    : "Generate Outreach"}
              </Button>
            </Group>
          </Group>
        </Card>

        {/* Two-column layout */}
        <Grid>
          {/* Left column — Job & Company Details */}
          <Grid.Col span={{ base: 12, md: 6 }}>
            <Stack gap="md">
              {/* Company description */}
              {opportunity.companyDescription && (
                <Card withBorder padding="lg" radius="md">
                  <Group gap="sm" mb="sm">
                    <Building2 size={18} />
                    <Title order={5}>About {opportunity.company}</Title>
                  </Group>
                  <Text size="sm" c="dimmed" lh={1.7}>
                    {opportunity.companyDescription}
                  </Text>
                  <Group gap="lg" mt="md">
                    {opportunity.industry && (
                      <div>
                        <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
                          Industry
                        </Text>
                        <Text size="sm">{opportunity.industry}</Text>
                      </div>
                    )}
                    {opportunity.companySize && (
                      <div>
                        <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
                          Company Size
                        </Text>
                        <Text size="sm">{opportunity.companySize}</Text>
                      </div>
                    )}
                  </Group>
                </Card>
              )}

              {/* Contact */}
              <Card withBorder padding="lg" radius="md">
                <Group gap="sm" mb="sm">
                  <Users size={18} />
                  <Title order={5}>Contact</Title>
                </Group>
                <Group gap="sm">
                  <ThemeIcon variant="light" color="blue" size="lg" radius="xl">
                    <Text fw={600}>
                      {opportunity.contactName
                        .split(" ")
                        .map((n) => n[0])
                        .join("")}
                    </Text>
                  </ThemeIcon>
                  <div>
                    <Text size="sm" fw={500}>
                      {opportunity.contactName}
                    </Text>
                    <Anchor
                      href={`mailto:${opportunity.contactEmail}`}
                      size="sm"
                    >
                      {opportunity.contactEmail}
                    </Anchor>
                  </div>
                </Group>
              </Card>

              {/* Notes */}
              {opportunity.notes && (
                <Card withBorder padding="lg" radius="md">
                  <Group gap="sm" mb="sm">
                    <FileText size={18} />
                    <Title order={5}>Notes</Title>
                  </Group>
                  <Text size="sm" c="dimmed" lh={1.7}>
                    {opportunity.notes}
                  </Text>
                </Card>
              )}
            </Stack>
          </Grid.Col>

          {/* Right column — Research Summary */}
          <Grid.Col span={{ base: 12, md: 6 }}>
            <Stack gap="md">
              {opportunity.researchSummary && (
                <Card withBorder padding="lg" radius="md">
                  <Group gap="sm" mb="sm">
                    <Globe size={18} />
                    <Title order={5}>Company Research</Title>
                  </Group>
                  <Text size="sm" c="dimmed" lh={1.7}>
                    {opportunity.researchSummary}
                  </Text>
                </Card>
              )}

              {/* People found */}
              {opportunity.people && opportunity.people.length > 0 && (
                <Card withBorder padding="lg" radius="md">
                  <Group gap="sm" mb="md">
                    <Users size={18} />
                    <Title order={5}>
                      People at {opportunity.company}
                    </Title>
                  </Group>
                  <Stack gap="sm">
                    {opportunity.people.map((person, idx) => (
                      <Group key={idx} gap="sm">
                        <ThemeIcon
                          variant="light"
                          color="violet"
                          size="md"
                          radius="xl"
                        >
                          <Text fw={600} size="xs">
                            {person.name
                              .split(" ")
                              .map((n) => n[0])
                              .join("")}
                          </Text>
                        </ThemeIcon>
                        <div style={{ flex: 1 }}>
                          <Text size="sm" fw={500}>
                            {person.name}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {person.role}
                          </Text>
                        </div>
                        {person.profileUrl && (
                          <ActionIcon
                            variant="subtle"
                            color="blue"
                            component="a"
                            href={person.profileUrl}
                            target="_blank"
                          >
                            <Linkedin size={14} />
                          </ActionIcon>
                        )}
                      </Group>
                    ))}
                  </Stack>
                </Card>
              )}
            </Stack>
          </Grid.Col>
        </Grid>

        {/* Resume & Cover sections */}
        <Grid mt="md">
          {/* Resume section */}
          <Grid.Col span={{ base: 12, md: 6 }}>
            <Card withBorder padding="lg" radius="md">
              <Group justify="space-between" mb="sm">
                <Group gap="sm">
                  <FileText size={18} />
                  <Title order={5}>Resume</Title>
                </Group>
                {opportunity.resume && (
                  <Group gap="xs">
                    <Button
                      size="compact-sm"
                      variant="light"
                      leftSection={<Eye size={12} />}
                    >
                      Preview
                    </Button>
                    <Button
                      size="compact-sm"
                      variant="light"
                      leftSection={<Edit3 size={12} />}
                    >
                      Edit
                    </Button>
                  </Group>
                )}
              </Group>
              {tailoredSummary ? (
                <div>
                    <Group gap="xs" mb="xs">
                      <Badge size="sm" variant="light" color="blue">
                        AI Tailored
                      </Badge>
                      {verifierScore !== null && (
                        <Badge
                          size="sm"
                          variant="light"
                          color={getVerifierState(verifierScore) === "success" ? "green" : getVerifierState(verifierScore) === "warn" ? "yellow" : "red"}
                        >
                          {getVerifierState(verifierScore) === "warn" ? `WARN ${verifierScore}` : `${verifierScore}%`}
                        </Badge>
                      )}
                    </Group>
                   <Text size="sm" style={{ whiteSpace: "pre-wrap" }} lh={1.6}>
                     {tailoredSummary}
                   </Text>
                </div>
              ) : opportunity.resume ? (
                <div>
                  <Group gap="xs" mb="xs">
                    <ThemeIcon variant="light" color="gray" size="sm" radius="sm">
                      <FileText size={12} />
                    </ThemeIcon>
                    <Text size="sm">{opportunity.resume.filename}</Text>
                    <Badge size="sm" variant="dot" color="green">
                      Uploaded{" "}
                      {new Date(
                        opportunity.resume.uploadedAt
                      ).toLocaleDateString()}
                    </Badge>
                  </Group>
                  <Text size="xs" c="dimmed" lh={1.6}>
                    {opportunity.resume.content}
                  </Text>
                </div>
              ) : (
                <Button variant="light" fullWidth leftSection={<Plus size={14} />}>
                  Upload Resume
                </Button>
              )}
            </Card>
          </Grid.Col>

          {/* Cover email section */}
          <Grid.Col span={{ base: 12, md: 6 }}>
            <Card withBorder padding="lg" radius="md">
              <Group justify="space-between" mb="sm">
                <Group gap="sm">
                  <Mail size={18} />
                  <Title order={5}>Cover Email</Title>
                </Group>
                {opportunity.coverEmail && (
                  <Group gap="xs">
                    <Button
                      size="compact-sm"
                      variant="light"
                      leftSection={<Eye size={12} />}
                    >
                      Preview
                    </Button>
                    <Button
                      size="compact-sm"
                      variant="light"
                      leftSection={<Edit3 size={12} />}
                    >
                      Edit
                    </Button>
                    {opportunity.coverEmail.status === "approved" && (
                      <Button
                        size="compact-sm"
                        variant="filled"
                        color="green"
                        leftSection={<Send size={12} />}
                      >
                        Send
                      </Button>
                    )}
                  </Group>
                )}
              </Group>
              {generatedBody ? (
                <div>
                  <Group gap="xs" mb="xs">
                    <Badge size="sm" variant="light" color="green">
                      AI Generated
                    </Badge>
                    <CopyButton value={generatedBody} timeout={2000}>
                      {({ copied, copy }) => (
                        <Button
                          size="compact-xs"
                          variant="subtle"
                          leftSection={copied ? <Check size={12} /> : <Copy size={12} />}
                          onClick={copy}
                        >
                          {copied ? "Copied" : "Copy"}
                        </Button>
                      )}
                    </CopyButton>
                  </Group>
                  <Text size="sm" fw={500} mb={4}>
                    {generatedSubject}
                  </Text>
                  <Text
                    size="xs"
                    c="dimmed"
                    lh={1.6}
                    style={{ whiteSpace: "pre-wrap" }}
                  >
                    {generatedBody}
                  </Text>
                </div>
              ) : opportunity.coverEmail ? (
                <div>
                  <Group gap="sm" mb="xs">
                    <Badge
                      variant="light"
                      color={
                        opportunity.coverEmail.status === "approved"
                          ? "green"
                          : opportunity.coverEmail.status === "sent"
                            ? "blue"
                            : "yellow"
                      }
                      size="sm"
                      tt="capitalize"
                    >
                      {opportunity.coverEmail.status}
                    </Badge>
                    <Text size="sm" fw={500} truncate>
                      {opportunity.coverEmail.subject}
                    </Text>
                  </Group>
                  <Text
                    size="xs"
                    c="dimmed"
                    lh={1.6}
                    lineClamp={3}
                    style={{ whiteSpace: "pre-line" }}
                  >
                    {opportunity.coverEmail.body}
                  </Text>
                </div>
              ) : (
                <Button variant="light" fullWidth leftSection={<Plus size={14} />}>
                  Create Cover Email
                </Button>
              )}
            </Card>
          </Grid.Col>
        </Grid>
      </Container>
    </AppLayout>
  );
}
