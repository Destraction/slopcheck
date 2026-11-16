import type { Note } from "../types";

/** Одна заметка в списке. */
export function NoteItem({ note }: { note: Note }) {
  return (
    <li>
      <h3>{note.title}</h3>
      <p>{note.body}</p>
    </li>
  );
}
