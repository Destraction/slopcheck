import { render, screen } from "@testing-library/react";
import { NoteList } from "./NoteList";

test("пустой список показывает подсказку", () => {
  render(<NoteList notes={[]} />);
  expect(screen.getByText("Заметок пока нет.")).toBeInTheDocument();
});

test("заметки выводятся заголовками", () => {
  render(<NoteList notes={[{ id: 1, title: "a", body: "b", tags: [], created_at: "" }]} />);
  expect(screen.getByRole("heading", { name: "a" })).toBeInTheDocument();
});
