"use client";

import {
  AppShell,
  Burger,
  Group,
  NavLink,
  Text,
  Title,
  useMantineColorScheme,
  ActionIcon,
  Tooltip,
  Container,
  Box,
  Divider,
} from "@mantine/core";

import { useDisclosure } from "@mantine/hooks";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Briefcase,
  FileText,
  Building2,
  Send,
  Layers,
  Settings,
  Moon,
  Sun,
  Gem,
} from "lucide-react";

const NAV_ITEMS = [
  { label: "Dashboard", icon: LayoutDashboard, href: "/dashboard" },
  { label: "Opportunities", icon: Briefcase, href: "/opportunities" },
  { label: "Freelance", icon: Gem, href: "/freelance" },
  { label: "Applications", icon: FileText, href: "/applications" },
  { label: "Companies", icon: Building2, href: "/companies" },
  { label: "Outreach", icon: Send, href: "/outreach" },
  { label: "Batch", icon: Layers, href: "/batch" },
  { label: "Settings", icon: Settings, href: "/settings" },
];

export function AppLayout({ children }: { children: React.ReactNode }) {
  const [opened, { toggle }] = useDisclosure(true);
  const pathname = usePathname();
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const isDark = colorScheme === "dark";

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{
        width: 260,
        breakpoint: "sm",
        collapsed: { mobile: !opened, desktop: !opened },
      }}
      padding="lg"
    >
      <AppShell.Header withBorder>
        <Group h="100%" px="lg" justify="space-between">
          <Group gap="xs">
            <Burger opened={opened} onClick={toggle} size="sm" />
            <Title order={4}>InternApply</Title>
          </Group>
          <Group gap="sm">
            <Text size="sm" c="dimmed" visibleFrom="sm">
              Track · Apply · Succeed
            </Text>
            <Tooltip label={isDark ? "Light mode" : "Dark mode"}>
              <ActionIcon
                variant="subtle"
                size="lg"
                onClick={() => setColorScheme(isDark ? "light" : "dark")}
              >
                {isDark ? <Sun size={18} /> : <Moon size={18} />}
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar withBorder p="xs">
        <Box py="sm">
          {NAV_ITEMS.map((item) => {
            const isActive =
              pathname === item.href ||
              (item.href !== "/" && pathname.startsWith(item.href + "/"));

            return (
              <NavLink
                key={item.href}
                component={Link}
                href={item.href}
                label={item.label}
                leftSection={<item.icon size={18} />}
                active={isActive}
                variant="light"
                color="blue"
                style={{ borderRadius: "var(--mantine-radius-md)" }}
                mb={4}
              />
            );
          })}
        </Box>
        <Divider my="sm" />
        <Box px="md" py="sm">
          <Text size="xs" c="dimmed">
            InternApply v0.2
          </Text>
        </Box>
      </AppShell.Navbar>

      <AppShell.Main
        style={{
          paddingTop: "calc(56px + var(--mantine-spacing-lg))",
          paddingInlineStart: opened
            ? "calc(260px + var(--mantine-spacing-lg))"
            : "var(--mantine-spacing-lg)",
        }}
      >
        <Container size="xl" py="lg">
          {children}
        </Container>
      </AppShell.Main>
    </AppShell>
  );
}
