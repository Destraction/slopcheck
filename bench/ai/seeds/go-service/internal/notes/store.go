// Package notes хранит заметки и отдаёт их по HTTP.
package notes

import (
	"errors"
	"sort"
	"sync"
	"time"
)

// ErrNotFound — заметки с таким id нет.
var ErrNotFound = errors.New("note not found")

// Note — заметка пользователя.
type Note struct {
	ID        int       `json:"id"`
	Title     string    `json:"title"`
	Body      string    `json:"body"`
	Tags      []string  `json:"tags"`
	CreatedAt time.Time `json:"created_at"`
}

// MemoryStore держит заметки в памяти процесса.
type MemoryStore struct {
	mu     sync.RWMutex
	nextID int
	notes  map[int]Note
}

// NewMemoryStore создаёт пустое хранилище.
func NewMemoryStore() *MemoryStore {
	return &MemoryStore{nextID: 1, notes: map[int]Note{}}
}

// Create сохраняет заметку и возвращает её с присвоенным id.
func (s *MemoryStore) Create(n Note) Note {
	s.mu.Lock()
	defer s.mu.Unlock()
	n.ID = s.nextID
	n.CreatedAt = time.Now().UTC()
	s.nextID++
	s.notes[n.ID] = n
	return n
}

// Get возвращает заметку по id.
func (s *MemoryStore) Get(id int) (Note, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	n, ok := s.notes[id]
	if !ok {
		return Note{}, ErrNotFound
	}
	return n, nil
}

// List возвращает все заметки по возрастанию id.
func (s *MemoryStore) List() []Note {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]Note, 0, len(s.notes))
	for _, n := range s.notes {
		out = append(out, n)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

// Delete удаляет заметку по id.
func (s *MemoryStore) Delete(id int) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.notes[id]; !ok {
		return ErrNotFound
	}
	delete(s.notes, id)
	return nil
}
