"use client";

import { AppLayout } from "@/components/AppLayout";
import { KanbanBoard } from "@/components/KanbanBoard";

export default function InternshipsPage() {
  return (
    <AppLayout>
      <KanbanBoard
        sourceType="internship"
        title="Internship Pipeline"
        description="Kanban workflow for engineering, product, and AI internships across ATS feeds & portals."
      />
    </AppLayout>
  );
}
