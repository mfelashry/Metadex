import { createFileRoute, Link } from "@tanstack/react-router";
import { Moon, Sun } from "lucide-react";
import { useState } from "react";
import { EvidenceSearch } from "@/components/evidex/EvidenceSearch";

export const Route = createFileRoute("/search")({
  head: () => ({
    meta: [
      { title: "Metadex — Evidence search" },
      {
        name: "description",
        content:
          "Search an evidence case by describing an image. Ranking is visual similarity, shown next to Metadex forensic findings.",
      },
    ],
  }),
  component: SearchPage,
});

function SearchPage() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  return (
    <div className="app-shell" data-theme={theme}>
      <header className="site-nav">
        <div className="nav-start">
          <Link to="/" className="back-link" aria-label="Back">
            ←
          </Link>
          <Link to="/" className="brand" aria-label="Metadex">
            METADEX
          </Link>
        </div>
        <nav className="nav-controls" aria-label="Case tools">
          <Link to="/report" className="nav-link">
            Case report
          </Link>
          <Link to="/search" className="nav-link" aria-current="page">
            Image search
          </Link>
          <button
            className="theme-toggle"
            type="button"
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
          >
            {theme === "dark" ? <Sun size={20} /> : <Moon size={20} />}
          </button>
        </nav>
      </header>
      <EvidenceSearch />
    </div>
  );
}
