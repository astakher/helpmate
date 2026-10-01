import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { db } from "../../mocks/handlers";
import { axeViolations, renderWithProviders } from "../../test/render";
import { DocumentsPage } from "./DocumentsPage";

const files = () => screen.getByRole("region", { name: "Your files" });

describe("the documents page", () => {
  it("uploads a file, answers from it with a cited source, and deletes it", async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<DocumentsPage />);
    expect(await within(files()).findByText("No documents yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled(); // nothing to ask yet

    const file = new File(["The late penalty is 10 percent per day. Office hours are Fridays."], "syllabus.txt", {
      type: "text/plain",
    });
    await user.upload(screen.getByLabelText("File to upload"), file);
    await user.click(within(files()).getByRole("button", { name: "Upload" }));
    expect(await within(files()).findByRole("link", { name: "syllabus.txt" })).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/api\/documents\/\w+\/file$/),
    );

    await user.type(screen.getByLabelText("Question"), "what is the late penalty?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    const answer = await screen.findByRole("status");
    expect(answer).toHaveTextContent("The late penalty is 10 percent per day.");
    expect(within(answer).getByRole("link", { name: "source 1" })).toHaveAttribute("href", "#source-1");
    expect(within(answer).getByRole("heading", { name: "Sources" })).toBeInTheDocument();
    expect(within(answer).getByRole("link", { name: "syllabus.txt" })).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(within(files()).getByRole("button", { name: "Delete syllabus.txt" }));
    await user.click(within(files()).getByRole("button", { name: "Delete" }));
    expect(await within(files()).findByText("No documents yet.")).toBeInTheDocument();
    expect(db.documents).toHaveLength(0);
  });

  it("explains a file it can't take, and says when the answer isn't in the documents", async () => {
    const user = userEvent.setup({ applyAccept: false }); // the server, not only the picker, refuses it
    renderWithProviders(<DocumentsPage />);
    await user.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a file first.");
    await user.upload(screen.getByLabelText("File to upload"), new File(["x"], "photo.jpg", { type: "image/jpeg" }));
    await user.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Upload a PDF, a Word .docx");

    db.documents.push({
      file: {
        id: "d1",
        name: "recipes.md",
        content_type: "text/markdown",
        size: 10,
        pages: null,
        passages: 1,
        note: null,
        storage_key: "documents/d1",
        created_at: new Date().toISOString(),
      },
      text: "Mix flour and butter.",
    });
    renderWithProviders(<DocumentsPage />);
    const [, second] = screen.getAllByLabelText("Question");
    await user.type(second, "when is the midterm?");
    await user.click(screen.getAllByRole("button", { name: "Ask" })[1]);
    expect(await screen.findByText("I couldn't find that in your documents.")).toBeInTheDocument();
  });
});
