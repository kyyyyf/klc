#include <cassert>
int foo();

int main() {
    assert(foo() == 42);
    return 0;
}
