
__all__ = ['immutable_property', 'descriptor', 'variantmethod', 'Signal']

import types
from typing import TypeVar, Generic, ParamSpec, overload, Concatenate, Any, Self
from collections.abc import Callable

_T = TypeVar('_T')
_KT = TypeVar('_KT')
_VT = TypeVar('_VT')
_P = ParamSpec('_P')
_R_co = TypeVar('_R_co', covariant=True)


### Attribute

class immutable_property(Generic[_T, _VT]): # Similar to the cached_property in functools.py
    """An immutable property reference.

    The __get__ method of this descriptor runs as a default factory at the first
    access to the attribute, and then stores the result in the instance, which
    is similar to the cached_property in functools.py.

    This type of property references cannot be changed after the first access,
    but can be deleted to reverted to the default value, and the referenced
    objects can still be mutable."""
    __slots__ = ('__name__', '_default', '_default_factory')

    def __init__(self, fnew: Callable[[_T], _VT] | None = None) -> None:
        self.__name__ = None
        self._default_factory = fnew

    def __set_name__(self, owner, name: str, /):
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
    def __get__(self, obj: _T, objtype: type[_T], /) -> _VT: ...
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

    def __set__(self, obj: _T, value: _VT, /) -> None:
        raise TypeError("can not assign to an immutable property")

    def __delete__(self, obj: _T, /) -> None:
        storage = self._get_storage(obj)

        if self.__name__ in storage:
            del storage[self.__name__]

    def _get_storage(self, obj: _T):
        try:
            return obj.__dict__
        except AttributeError as e:
            raise TypeError(
                f"No '__dict__' attribute on {type(obj).__name__!r} "
                f"instance to save {self.__name__!r} property."
            ) from e


def descriptor(factory: Callable[_P, _VT], /) -> Callable[_P, immutable_property[_T, _VT]]:
    def wrapper(*args, **kwargs):
        return immutable_property(lambda _: factory(*args, **kwargs))
    return wrapper


### VariantMethod

class _Variant(Generic[_KT, _T, _P, _R_co]):
    def __init__(
        self,
        curr_key: _KT,
        obj: _T,
        vt_ref: dict[_KT, Callable[Concatenate[_T, _P], _R_co]]
    ):
        self._vt_ref = vt_ref # read-only
        self.curr_key = curr_key
        self.instance = obj

    def __call__(self, *args: _P.args, **kwargs: _P.kwargs) -> _R_co:
        try:
            impl = self._vt_ref[self.curr_key]
        except KeyError:
            raise AttributeError(f"no variant was registered by {self.curr_key}")

        return impl.__get__(self.instance)(*args, **kwargs)

    def __len__(self) -> int:
        return len(self._vt_ref)

    def __getitem__(self, val: _KT) -> Callable[_P, _R_co]:
        func = self._vt_ref[val]
        return func.__get__(self.instance)

    def __contains__(self, item: _KT) -> bool:
        return item in self._vt_ref

    def set(self, val: _KT, /) -> None:
        self.curr_key = val

    def mapping(self):
        return types.MappingProxyType(self._vt_ref)


class variantmethod(immutable_property[_T, _Variant[_KT, _T, _P, _R_co]], Generic[_KT, _T, _P, _R_co]):
    """Variant method decorator class for implementing a key-based method
    dispatch mechanism.

    This class allows registering and calling different method implementations
    through different keys, forming a virtual method table.
    When accessing this property, it determines which specific implementation
    to call based on the object's state and the registered key.

    Generic parameters:
        _KT: The type of the key, used to distinguish different method variants
        _T: The type of the object that owns this property
        _P: The type of the method parameters
        _R_co: The return type of the method

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
    virtual_table: dict[_KT, Callable[Concatenate[_T, _P], _R_co]]

    @overload
    def __new__(cls, key: _KT, func: Callable[Concatenate[_T, _P], _R_co], /) -> "variantmethod[_KT, _T, _P, _R_co]": ...
    @overload
    def __new__(cls, key: _KT, /) -> Callable[[Callable[Concatenate[_T, _P], _R_co]], "variantmethod[_KT, _T, _P, _R_co]"]: ...
    def __new__(cls, arg1, arg2=None, /):
        if arg2 is None:
            return lambda func: cls(arg1, func)
        else:
            return super().__new__(cls)

    def __init__(self, key: _KT, func: Callable[Concatenate[_T, _P], _R_co], /):
        super().__init__(lambda obj: _Variant(key, obj, self.virtual_table))
        self.virtual_table = {key: func}
        self.__doc__ = func.__doc__

    def __set__(self, obj: _T, value: _VT):
        raise TypeError("can not assign to variant methods")

    def register(self, key: _KT, /):
        def decorator(func: Callable) -> variantmethod[_KT, _T, _P, _R_co]:
            self.virtual_table[key] = func
            return self
        return decorator


### Signal

class _Emitter(Generic[_VT]):
    def __init__(self, obj, cb_ref: list[Callable[[_VT], Any]]):
        self.obj = obj
        self._cb_ref = cb_ref # read-only
        self._cb_list = [func.__get__(self.obj, self.obj.__class__) for func in self._cb_ref]

    @overload
    def emit(self) -> None: ...
    @overload
    def emit(self, value: _VT, /) -> None: ...
    def emit(self, *args) -> None:
        import inspect

        if len(args) > 1:
            raise TypeError("too many arguments for emit")

        for func in self._cb_list:
            if inspect.signature(func).parameters:
                try:
                    value = (args[0],)
                except IndexError:
                    value = ()
            else:
                value = ()

            func(*value)

    def connect(self, target: Callable[[_VT], _R_co], /):
        self._cb_list.append(target)
        return target

    def disconnect(self, target: Callable[[_VT], _R_co], /):
        try:
            self._cb_list.remove(target)
        except ValueError:
            pass
        return target


class Signal(immutable_property[_T, _Emitter[_VT]]):
    callbacks: list[Callable[[_VT], Any]]

    def __init__(self, dtype: type[_VT], /):
        super().__init__(lambda obj: _Emitter(obj, self.callbacks))
        self.callbacks = []
        self.dtype = dtype

    def __set__(self, obj: _T, value: _VT):
        raise TypeError("can not assign to signals")

    def bind(self, func: Callable[[_VT], _R_co], /):
        if not callable(func) and not hasattr(func, "__get__"):
            raise TypeError(f"{func!r} is not callable or a descriptor")
        self.callbacks.append(func)
        return func

    def unbind(self, func: Callable[[_VT], _R_co], /):
        self.callbacks.remove(func)
        return func
