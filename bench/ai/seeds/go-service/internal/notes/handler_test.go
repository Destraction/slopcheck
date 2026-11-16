package notes

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func newServer() *http.ServeMux {
	mux := http.NewServeMux()
	NewHandler(NewMemoryStore()).Register(mux)
	return mux
}

func TestCreateRequiresTitle(t *testing.T) {
	rec := httptest.NewRecorder()
	newServer().ServeHTTP(rec, httptest.NewRequest("POST", "/notes", strings.NewReader(`{"body":"x"}`)))
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestCreateThenGet(t *testing.T) {
	mux := newServer()
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest("POST", "/notes", strings.NewReader(`{"title":"a"}`)))
	if rec.Code != http.StatusCreated {
		t.Fatalf("create status = %d", rec.Code)
	}
	rec = httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest("GET", "/notes/1", nil))
	if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), `"title":"a"`) {
		t.Fatalf("get = %d %s", rec.Code, rec.Body.String())
	}
}
