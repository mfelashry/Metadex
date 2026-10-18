import { Link, useRouterState } from "@tanstack/react-router";

export function LearnLink() {
  const current = useRouterState({ select: (state) => state.location.pathname === "/learn" });
  return (
    <Link to="/learn" className="learn-nav" aria-label="Learn" aria-current={current ? "page" : undefined}>
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
        <path
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          d="M4 5.5h6.2a2.3 2.3 0 0 1 2.3 2.3V19a1.8 1.8 0 0 0-1.8-1.8H4zM20 5.5h-6.2A2.3 2.3 0 0 0 11.5 7.8V19a1.8 1.8 0 0 1 1.8-1.8H20z"
        />
      </svg>
      <span>Learn</span>
    </Link>
  );
}
