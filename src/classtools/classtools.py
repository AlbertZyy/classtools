
__all__ = [
    'immutable_property',
    'descriptor',
    'variantmethod',
    'Signal',
    'signalmethod',
    'declare'
]

import types
from typing import overload, Concatenate, Protocol, Self, Any
from collections.abc import Callable


### Attribute

class immutable_property[T, VT]: # Similar to the cached_property in functools.py
    """An immutable property reference.

    The __get__ method of this descriptor runs as a default factory at the first
    access to the attribute, and then stores the result in the instance, which
    is similar to the cached_property in functools.py.

    This type of property references cannot be changed after the first access,
    but can be deleted to reverted to the default value, and the referenced
    objects can still be mutable."""
    __slots__ = ('__name__', '_default', '_default_factory')

    def __init__(self, fnew: Callable[[T], VT]) -> None:
        self.__name__ = None
        self._default_factory = fnew

    def __set_name__(self, owner: type[T], name: str, /):
        if self.__name__ is None:
            self.__name__ = name
        elif name != self.__name__ and not name.startswith('_'):
            raise TypeError(
                "Cannot assign the same attribute to two different names "
                f"({self.__name__!r} and {name!r})."
            )

    @overload
    def __get__(self, obj: None, objtype: type, /) -> Self: ...
    @overload
    def __get__(self, obj: T, objtype: type[T], /) -> VT: ...
    def __get__(self, obj, objtype, /):
        if obj is None:
            return self
        assert self.__name__ is not None

        storage = self._get_storage(obj)

        if self.__name__ in storage:
            return storage[self.__name__]
        else:
            value = self._default_factory.__get__(obj, objtype)()
            storage[self.__name__] = value
            return value

    def __set__(self, obj: T, value: VT, /) -> None:
        raise TypeError("can not assign to an immutable property")

    def __delete__(self, obj: T, /) -> None:
        storage = self._get_storage(obj)

        if self.__name__ in storage:
            del storage[self.__name__]

    def _get_storage(self, obj: T):
        try:
            return obj.__dict__
        except AttributeError as e:
            raise TypeError(
                f"No '__dict__' attribute on {type(obj).__name__!r} "
                f"instance to save {self.__name__!r} property."
            ) from e


def descriptor[**P, VT](factory: Callable[P, VT], /) -> Callable[P, immutable_property[Any, VT]]:
    def wrapper(*args, **kwargs):
        return immutable_property(lambda _: factory(*args, **kwargs))
    return wrapper


# ------------------------------
# Variant Methods
# ------------------------------

class _Variant[KT, T, **P, R]:
    def __init__(
        self,
        curr_key: KT,
        obj: T,
        vt_ref: dict[KT, Callable[Concatenate[T, P], R]]
    ):
        self._vt_ref = vt_ref # read-only
        self.curr_key = curr_key
        self.instance = obj

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        try:
            impl = self._vt_ref[self.curr_key]
        except KeyError:
            raise AttributeError(f"no variant was registered by {self.curr_key}")

        return impl.__get__(self.instance)(*args, **kwargs)

    def __len__(self) -> int:
        return len(self._vt_ref)

    def __getitem__(self, val: KT) -> Callable[P, R]:
        func = self._vt_ref[val]
        return func.__get__(self.instance)

    def __contains__(self, item: KT) -> bool:
        return item in self._vt_ref

    def set(self, val: KT, /) -> None:
        self.curr_key = val

    def mapping(self):
        return types.MappingProxyType(self._vt_ref)


class variantmethod[KT, T, **P, R](immutable_property[T, _Variant[KT, T, P, R]]):
    """Variant method decorator class for implementing a key-based method
    dispatch mechanism.

    This class allows registering and calling different method implementations
    through different keys, forming a virtual method table.
    When accessing this property, it determines which specific implementation
    to call based on the object's state and the registered key.

    Generic parameters:
        KT: The type of the key, used to distinguish different method variants
        T: The type of the object that owns this property
        **P: The type of the method parameters
        R: The return type of the method

    Examples:
    ```
    class MyClass:
        @variantmethod("a")
        def my_method(self, arg: int) -> str:
            return f"a: {arg}"

        @my_method.register("b")
        def my_method(self, arg: int) -> str:
            return f"b: {arg}"

        @my_method.register("c")
        def my_method(self, arg: int) -> str:
    ```
    Switch between variants by set(), or select a key temporarily through
    __getitem__:
    ```
    my_obj = MyClass()
    my_obj.my_method.set("b")
    my_obj.my_method(42)
    my_obj.my_method["c"](42)
    ```
    """
    virtual_table: dict[KT, Callable[Concatenate[T, P], R]]

    @overload
    def __new__(cls, key: KT, func: Callable[Concatenate[T, P], R], /) -> "variantmethod[KT, T, P, R]": ...
    @overload
    def __new__(cls, key: KT, /) -> Callable[[Callable[Concatenate[T, P], R]], "variantmethod[KT, T, P, R]"]: ...
    def __new__(cls, arg1, arg2=None, /):
        if arg2 is None:
            return lambda func: cls(arg1, func)
        else:
            return super().__new__(cls)

    def __init__(self, key: KT, func: Callable[Concatenate[T, P], R], /):
        super().__init__(lambda obj: _Variant(key, obj, self.virtual_table))
        self.virtual_table = {key: func}
        self.__doc__ = func.__doc__

    def __set__(self, instance: T, value):
        raise TypeError("can not assign to variant methods")

    def register(self, key: KT, /):
        def decorator(func: Callable) -> variantmethod[KT, T, P, R]:
            self.virtual_table[key] = func
            return self
        return decorator


# ------------------------------
# Signal
# ------------------------------

class _Emitter[VT]:
    def __init__(self, obj, cb_m: list, cb_f: list):
        self.obj = obj
        self._cb_list = [func.__get__(self.obj, self.obj.__class__) for func in cb_m]
        self._cb_list.extend(cb_f)

    @overload
    def emit(self) -> None: ...
    @overload
    def emit(self, value: VT, /) -> None: ...
    def emit(self, *args) -> None:
        import inspect

        if len(args) > 1:
            raise TypeError("too many arguments for emit")

        for func in self._cb_list:
            try:
                params = inspect.signature(func).parameters
            except TypeError:
                continue

            if params:
                value = args[:1] # 0 or 1 arg
            else:
                value = ()

            func(*value)

    def connect[R](self, target: Callable[..., R], /):
        self._cb_list.append(target)
        return target

    def disconnect[R](self, target: Callable[..., R], /):
        try:
            self._cb_list.remove(target)
        except ValueError:
            pass
        return target


class Signal[T, VT](immutable_property[T, _Emitter[VT]]):
    def __init__(self, dtype: type[VT] | None = None, /):
        super().__init__(lambda obj: _Emitter(obj, self._cb_m, self._cb_f))
        self._cb_m = []
        self._cb_f = []
        self.dtype = dtype

    def __set__(self, instance: T, value):
        raise TypeError("can not assign to signals")

    def bindm[V](self, func: V, /) -> V:
        """Binds a descriptor to the signal. The descriptor supports
        `__get__` returning a callable."""
        if not hasattr(func, "__get__"):
            raise TypeError(f"{func!r} is not a descriptor")
        self._cb_m.append(func)
        return func

    def unbindm[V](self, func: V, /) -> V:
        self._cb_m.remove(func)
        return func

    def bindf[R](self, func: Callable[[VT], R], /):
        """A decorator that binds a callable to the signal."""
        if not callable(func):
            raise TypeError(f"{func!r} is not callable")
        self._cb_f.append(func)
        return func

    def unbindf[R](self, func: Callable[[VT], R], /):
        self._cb_f.remove(func)
        return func


# Here we use Callable instead of SupportsGet for a better type deduction.
def signalmethod[T, V](func: Callable[[T, V], Any], /) -> Signal[T, V]:
    """Create a signal method from a function binded."""
    s = Signal()
    s.bindm(func) # This checks if func is a descriptor.
    return s


# ------------------------------
# External Methods
# ------------------------------

class declare[T, **P, R]:
    """Declare the signature of a method and subsequently provide
    its implementation."""
    __slots__ = ("__name__", "__stub__", "__func__")
    __name__: str | None

    def __init__(self, stub: Callable[Concatenate[T, P], R], /):
        self.__name__ = None
        self.__stub__ = stub
        self.__func__ = None

    def __set_name__(self, owner: type[T], name: str) -> None:
        if self.__name__ is None:
            self.__name__ = name
        elif name != self.__name__:
            raise TypeError(
                "Cannot assign the same declare to two different names "
                f"({self.__name__!r} and {name!r})."
            )

    def _get_name_of_stub(self) -> str:
        if hasattr(self.__stub__, "__name__"):
            return self.__stub__.__name__
        elif hasattr(self.__stub__, "__qualname__"):
            return self.__stub__.__qualname__
        else:
            stub_type = type(self.__stub__)
            return stub_type.__name__

    @overload
    def __get__(self, instance: T, owner: type[T]) -> Callable[P, R]: ...
    @overload
    def __get__[V](self, instance: None, owner: type[T]) -> Callable[[V], V]: ...
    def __get__(self, instance, owner):
        if instance is None: # if fetched by class
            return lambda f: self.impl(f, owner)

        if self.__func__ is None:
            raise NotImplementedError(
                "can not find the implementation of the method "
                f"{self.__name__!r} in {owner.__name__!r}."
            )

        if hasattr(self.__func__, "__get__"):
            return self.__func__.__get__(instance, owner)
        else:
            return self.__func__

    def __set__(self, instance: T, value):
        raise TypeError("Cannot assign to a method")

    def impl(self, func, owner: type[T] | None = None):
        if not callable(func) and not hasattr(func, "__get__"):
            raise TypeError("expected a callable or a descriptor for "
                            f"implementation, but got {type(func)!r}")

        if (owner is not None) and (self.__name__ not in owner.__dict__):
            if self.__name__ is None:
                raise TypeError("only declarations inside a class can be "
                                "implemented with an owner (subclass)")
            if self.__name__ in owner.__dict__:
                raise TypeError(f"class {owner!r} already has an attribute "
                                f"named {self.__name__!r} in its __dict__")
            # if implement for subclasses: copy is needed for override
            new_ext = declare(self.__stub__)
            new_ext.__name__ = self.__name__
            new_ext.__func__ = func
            setattr(owner, self.__name__, new_ext)
            return func

        if self.__func__ is None:
            self.__func__ = func
            return func

        # if already implemented
        raise TypeError(
            f"function {self._get_name_of_stub()!r} "
            "has already been implemented"
            if owner is None else
            f"method {self.__name__!r} of class {owner.__name__!r} "
            "has already been implemented"
        )
