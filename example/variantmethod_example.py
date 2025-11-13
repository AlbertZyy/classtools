from classtools import variantmethod, signalmethod


class Example:
    def __init__(self):
        self.changed.connect(self.calculate.set)

    def common_method(self):
        pass

    @variantmethod("add")
    def calculate(self, x, y):
        return x + y

    @calculate.register("sub")
    def _(self, x, y):
        return x - y

    @calculate.register("mul")
    def _(self, x, y):
        return x * y

    @calculate.register("div")
    def _(self, x, y):
        return x / y

    @signalmethod
    def changed(self, val: str):
        print("variant method set to:", val)


if __name__ == "__main__":
    e = Example()

    print(e.calculate(1, 2))
    e.calculate.set("sub")
    print(e.calculate(1, 2))
    e.changed.emit("mul")
    print(e.calculate(1, 2))
    print(e.calculate["div"](1, 2))
