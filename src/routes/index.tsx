import { createFileRoute } from "@tanstack/react-router";
import { ScrollStory } from "@/components/evidex/ScrollStory";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Metadex" },
      {
        name: "description",
        content:
          "Explore how Metadex brings image metadata, file structure, and steganography indicators into a readable investigation.",
      },
      { property: "og:title", content: "Metadex — Every file leaves a trace" },
      {
        property: "og:description",
        content:
          "Follow an image through metadata, file structure, pixel clues, and a plain-English report.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Index,
});

function Index() {
  return (
    <main className="bg-background">
      <ScrollStory />
    </main>
  );
}
