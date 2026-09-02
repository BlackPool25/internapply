"use client";

import { AppLayout } from "@/components/AppLayout";
import { KanbanBoard } from "@/components/KanbanBoard";

export default function FreelancePage() {
  return (
    <AppLayout>
      <KanbanBoard
        sourceType="freelance"
        title="Freelance & Contract Pipeline"
        description="Kanban workflow for direct freelance leads, hourly gigs, and contract tasks (Freelancer RSS, Upwork, Internshala)."
      />
    </AppLayout>
  );
}
