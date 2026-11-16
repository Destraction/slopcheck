import type { Note } from "../types";
import { NoteItem } from "./NoteItem";

/** Список заметок; пустой — подсказка. */
export function NoteList({ notes }: { notes: Note[] }) {
  if (notes.length === 0) return <p>Заметок пока нет.</p>;
  return (
    <ul>
      {notes.map((note) => (
        <NoteItem key={note.id} note={note} />
      ))}
    </ul>
  );
}
