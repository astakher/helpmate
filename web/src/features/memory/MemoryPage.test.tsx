import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { db } from "../../mocks/handlers";
import { axeViolations, renderWithProviders } from "../../test/render";
import { MemoryPage } from "./MemoryPage";

describe("MemoryPage", () => {
  it("stores a suggestion only when approved, shows its source, and can forget it", async () => {
    db.suggestions.push({ id: "s1", text: "my advisor is Dr. Lee", source: "chat:abc", status: "pending", created_at: "2026-09-29T12:00:00Z" });
    const user = userEvent.setup();
    const { container } = renderWithProviders(<MemoryPage />);

    expect(await screen.findByText(/noticed in a chat/)).toBeInTheDocument();
    expect(db.facts).toHaveLength(0);
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Remember: my advisor is Dr. Lee" }));
    expect(await screen.findByRole("button", { name: "Forget: my advisor is Dr. Lee" })).toBeInTheDocument();
    expect(screen.getByText("No suggestions waiting.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Forget: my advisor is Dr. Lee" }));
    await user.click(screen.getByRole("button", { name: "Forget it" }));
    expect(await screen.findByText(/Nothing remembered yet/)).toBeInTheDocument();
    expect(db.facts).toHaveLength(0);
  });

  it("edits a remembered fact in place, and Cancel keeps the original", async () => {
    db.facts.push({ id: "f1", text: "my advisor is Dr. Lee", source: "chat:abc", created_at: "2026-09-29T12:00:00Z" });
    const user = userEvent.setup();
    const { container } = renderWithProviders(<MemoryPage />);

    await user.click(await screen.findByRole("button", { name: "Edit: my advisor is Dr. Lee" }));
    const input = screen.getByLabelText("Edit memory");
    expect(await axeViolations(container)).toEqual([]);
    await user.clear(input);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled(); // empty text can't be saved
    await user.type(input, "my advisor is Dr. Li{Enter}");

    expect(await screen.findByRole("button", { name: "Edit: my advisor is Dr. Li" })).toBeInTheDocument();
    expect(db.facts[0].text).toBe("my advisor is Dr. Li");

    await user.click(screen.getByRole("button", { name: "Edit: my advisor is Dr. Li" }));
    await user.type(screen.getByLabelText("Edit memory"), " (typo)");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Edit: my advisor is Dr. Li" })).toBeInTheDocument();
    expect(db.facts[0].text).toBe("my advisor is Dr. Li");
  });

  it("discarding a suggestion stores nothing", async () => {
    db.suggestions.push({ id: "s2", text: "I like tea", source: "chat:abc", status: "pending", created_at: "2026-09-29T12:00:00Z" });
    const user = userEvent.setup();
    renderWithProviders(<MemoryPage />);
    await user.click(await screen.findByRole("button", { name: "Discard: I like tea" }));
    expect(await screen.findByText("No suggestions waiting.")).toBeInTheDocument();
    expect(db.facts).toHaveLength(0);
  });
});
