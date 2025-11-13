
from classtools import declare


class Example:
    @declare
    def face_normal(self, x, y) -> tuple[float, float]: ...

    @declare
    def face_tangent(self, x, y) -> tuple[float, float]: ...


@Example.face_normal
def _(self, x, y) -> tuple[float, float]:
    print(f"{self!r} - called face_normal")
    return (x, y)

@Example.face_tangent
def _(self, x, y) -> tuple[float, float]:
    print(f"{self!r} - called face_tangent")
    return (x, y)


class Example2(Example):
    pass


@Example2.face_normal
def _(self, x, y) -> tuple[float, float, float]:
    print(f"{self!r} - called face_normal (overridden)")
    return (x, y)


if __name__ == "__main__":
    ex = Example()
    print(ex.face_normal(1, 2))
    print(ex.face_tangent(1, 2))

    ex2 = Example2()
    print(ex2.face_normal(1, 2))
    print(ex2.face_tangent(1, 2))
