"""Go-интерфейс с единственной реализацией."""

from __future__ import annotations

from slopcheck.adapters.goiface import single_impl_interfaces

_IFACE = """package svc

type userStore interface {
\tGet(id int) (*User, error)
\tSave(u *User) error
}

type pgStore struct{}

func (s *pgStore) Get(id int) (*User, error) { return nil, nil }
func (s *pgStore) Save(u *User) error        { return nil }
"""


def _names(files: dict[str, str]) -> list[tuple[str, str]]:
    return [(i.name, impl) for i, impl in single_impl_interfaces(files)]


def test_unexported_single_impl_flagged() -> None:
    assert _names({"svc/store.go": _IFACE}) == [("userStore", "pgStore")]


def test_mock_in_tests_justifies_interface() -> None:
    mock = (
        "package svc\n\ntype fakeStore struct{}\n\n"
        "func (f fakeStore) Get(id int) (*User, error) { return nil, nil }\n"
        "func (f fakeStore) Save(u *User) error { return nil }\n"
    )
    assert _names({"svc/store.go": _IFACE, "svc/store_test.go": mock}) == []


def test_exported_library_interface_skipped_but_internal_checked() -> None:
    exported = _IFACE.replace("userStore", "UserStore")
    assert _names({"pkg/store.go": exported}) == []
    assert _names({"internal/svc/store.go": exported}) == [("UserStore", "pgStore")]
    assert _names({"cmd/app/main.go": exported.replace("package svc", "package main")}) == [
        ("UserStore", "pgStore")
    ]


def test_embedding_and_constraints_skipped() -> None:
    embedded = "package x\n\ntype rw interface {\n\tio.Reader\n\tClose() error\n}\n\ntype f struct{}\n\nfunc (f) Close() error { return nil }\n"
    constraint = "package x\n\ntype number interface {\n\t~int | ~float64\n}\n"
    assert _names({"x/a.go": embedded, "x/b.go": constraint}) == []


def test_partial_method_set_is_not_implementation() -> None:
    partial = _IFACE.replace("func (s *pgStore) Save(u *User) error        { return nil }\n", "")
    assert _names({"svc/store.go": partial}) == []
