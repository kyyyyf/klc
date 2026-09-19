#pragma once

class Widget { int x; };

void MakeLocal() {
    class LocalC { int y; };
    struct LocalS { int z; };
}
