import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FolderScan } from "@/components/evidex/FolderScan";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const defaults = {
  cards: null,
  label: "Photos",
  count: { done: 0, total: 24 },
};

describe("Folder scan loading states", () => {
  it("cycles previews without claiming analysis has finished", () => {
    vi.useFakeTimers();
    render(<FolderScan {...defaults} />);
    expect(screen.getByText("00")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(2300));
    expect(screen.getByText("00")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("0 images processed");
    expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
  });

  it("only marks completion after receiving a completed count", () => {
    const { rerender } = render(<FolderScan {...defaults} />);
    rerender(<FolderScan {...defaults} count={{ done: 24, total: 24 }} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    expect(screen.getByRole("status")).toHaveTextContent("Analysis complete");
  });

  it("shows uploaded previews and their own preview count", () => {
    render(<FolderScan {...defaults} cards={[{ name: "actual.png", preview: "blob:actual" }]} />);
    expect(screen.queryByText("YOUR PHOTOS")).not.toBeInTheDocument();
    expect(screen.queryByText("LOOKING CLOSER")).not.toBeInTheDocument();
    expect(screen.queryByText("Original photos stay untouched")).not.toBeInTheDocument();
    expect(document.querySelector('image[href="blob:actual"]')).toBeInTheDocument();
    expect(screen.getByText("/ 24")).toBeInTheDocument();
  });

  it("restores scrolling after the scan closes", () => {
    const { unmount } = render(<FolderScan {...defaults} />);
    expect(document.body.style.overflow).toBe("hidden");
    unmount();
    expect(document.body.style.overflow).toBe("");
  });
});
