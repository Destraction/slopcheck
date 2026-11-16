package main

import (
	"log"
	"net/http"
	"os"

	"example.com/notes/internal/notes"
)

func main() {
	addr := os.Getenv("NOTES_ADDR")
	if addr == "" {
		addr = ":8080"
	}
	store := notes.NewMemoryStore()
	mux := http.NewServeMux()
	notes.NewHandler(store).Register(mux)
	log.Printf("listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}
