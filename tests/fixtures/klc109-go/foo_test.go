package foo

import "testing"

func TestFoo(t *testing.T) {
    if Foo() != 42 {
        t.Fatal("expected 42")
    }
}
