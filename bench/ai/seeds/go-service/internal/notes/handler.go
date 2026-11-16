package notes

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"
)

// Handler — HTTP-API заметок.
type Handler struct {
	store *MemoryStore
}

// NewHandler создаёт API поверх хранилища.
func NewHandler(store *MemoryStore) *Handler {
	return &Handler{store: store}
}

// Register вешает маршруты на mux.
func (h *Handler) Register(mux *http.ServeMux) {
	mux.HandleFunc("GET /notes", h.list)
	mux.HandleFunc("POST /notes", h.create)
	mux.HandleFunc("GET /notes/{id}", h.get)
	mux.HandleFunc("DELETE /notes/{id}", h.delete)
}

func (h *Handler) list(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, h.store.List())
}

func (h *Handler) create(w http.ResponseWriter, r *http.Request) {
	var n Note
	if err := json.NewDecoder(r.Body).Decode(&n); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json")
		return
	}
	if strings.TrimSpace(n.Title) == "" {
		writeError(w, http.StatusBadRequest, "title is required")
		return
	}
	writeJSON(w, http.StatusCreated, h.store.Create(n))
}

func (h *Handler) get(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid id")
		return
	}
	n, err := h.store.Get(id)
	if errors.Is(err, ErrNotFound) {
		writeError(w, http.StatusNotFound, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, n)
}

func (h *Handler) delete(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid id")
		return
	}
	if err := h.store.Delete(id); err != nil {
		writeError(w, http.StatusNotFound, err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
	}
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
