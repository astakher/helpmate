import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";
import { db } from "../../mocks/handlers";
import { axeViolations, renderWithProviders } from "../../test/render";
import { FolderPage } from "./FolderPage";
import { FoldersPage } from "./FoldersPage";

describe("FoldersPage", () => {
  it("shows PARA and creates a custom folder with typed fields", async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<FoldersPage />);
    expect(await screen.findByRole("link", { name: /Projects/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New folder" }));
    await user.type(screen.getByLabelText("Name"), "Courses");
    await user.click(screen.getByRole("button", { name: "Add field" }));
    await user.type(screen.getByLabelText("Field name"), "Course code");
    await user.click(screen.getByRole("button", { name: "Add field" }));
    const names = screen.getAllByLabelText("Field name");
    await user.type(names[1], "Term");
    await user.selectOptions(screen.getAllByLabelText("Type")[1], "select");
    await user.type(screen.getByLabelText("Choices (comma separated)"), "Fall, Winter");
    expect(await axeViolations(container)).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Create folder" }));

    expect(await screen.findByRole("link", { name: /Courses/ })).toBeInTheDocument();
    expect(db.folders.at(-1)?.fields).toEqual([
      { key: "course_code", label: "Course code", type: "text", options: null },
      { key: "term", label: "Term", type: "select", options: ["Fall", "Winter"] },
    ]);
  });
});

describe("FolderPage", () => {
  it("adds an item using the folder's custom fields", async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(
      <Routes>
        <Route path="/folders/:folderId" element={<FolderPage />} />
      </Routes>,
      { route: "/folders/books" },
    );
    expect(await screen.findByRole("heading", { name: "Books" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("Title"), "Deep Work");
    await user.type(screen.getByLabelText("Author"), "Cal Newport");
    await user.selectOptions(screen.getByLabelText("Status"), "reading");
    await user.click(screen.getByRole("radio", { name: "4 out of 5" }));
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(await screen.findByRole("rowheader", { name: "Deep Work" })).toBeInTheDocument();
    expect(screen.getByText("★★★★☆")).toBeInTheDocument();
    expect(db.items[0].fields).toEqual({ author: "Cal Newport", status: "reading", rating: 4 });
    expect(await axeViolations(container)).toEqual([]);
  });

  it("says so when the folder doesn't exist", async () => {
    renderWithProviders(
      <Routes>
        <Route path="/folders/:folderId" element={<FolderPage />} />
      </Routes>,
      { route: "/folders/nope" },
    );
    expect(await screen.findByRole("heading", { name: "Folder not found" })).toBeInTheDocument();
  });
});
