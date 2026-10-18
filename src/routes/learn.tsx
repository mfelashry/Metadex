import { createFileRoute } from "@tanstack/react-router";
import { LearnPage } from "@/components/evidex/LearnPage";

export const Route = createFileRoute("/learn")({
  head: () => ({
    meta: [
      { title: "Learn · Metadex" },
      {
        name: "description",
        content: "Discover the invisible information inside digital images, how it works, and why it matters.",
      },
    ],
  }),
  component: LearnPage,
});
