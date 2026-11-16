import { useEffect, useState } from "react";
import { fetchNotes } from "./api";
import { NoteList } from "./components/NoteList";
import type { Note } from "./types";

/** Корневой компонент: загружает и показывает заметки. */
export function App() {
  const [notes, setNotes] = useState<Note[]>([]);

  useEffect(() => {
    fetchNotes().then(setNotes).catch(() => setNotes([]));
  }, []);

  return (
    <main>
      <h1>Заметки</h1>
      <NoteList notes={notes} />
    </main>
  );
}
