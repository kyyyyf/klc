"""KLC-108 step-1 fixture — six declarations that F-002 measured the
literal-text `public-api.yaml` rule against: an unannotated function, two
annotated forms, an async annotated form, a class and a module-scope
constant. The unannotated `plain` and the class/constant were already
captured before this ticket; the three annotated forms were not (F-002)."""


def plain(a, b):
    return a + b


def annotated(args) -> int:
    return args


def typed_args(a: int, b: str = "x") -> dict:
    return {}


async def a_annotated(x: int) -> None:
    return None


class Point:
    pass


MAX_SIZE = 1024
