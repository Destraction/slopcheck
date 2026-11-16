import type { Note } from "./types";

/** Список заметок с сервера. */
export async function fetchNotes(): Promise<Note[]> {
  const res = await fetch("/api/notes");
  if (!res.ok) throw new Error(`GET /api/notes: ${res.status}`);
  return res.json();
}

/** Создать заметку. */
export async function createNote(title: string, body: string): Promise<Note> {
  const res = await fetch("/api/notes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, body, tags: [] }),
  });
  if (!res.ok) throw new Error(`POST /api/notes: ${res.status}`);
  return res.json();
}
