
__all__ = ['attribute', 'descriptor', 'variantmethod', 'Signal']

import types
from typing import TypeVar, Generic, ParamSpec, overload, Concatenate, Any
from collections.abc import Callable

_T = TypeVar('_T')
_KT = TypeVar('_KT')
_VT = TypeVar('_VT')
_P = ParamSpec('_P')
_R_co = TypeVar('_R_co', covariant=True)


### Attribute

class attribute(Generic[_T, _VT]):
    __slots__ = ('__name__', '_default', '_default_factory')

    def __init__(
        self,
        fnew: Callable[[_T], _VT] | None = None,
        default: _VT | None = None,
    ) -> None:
        self.__name__ = None
        self._default = default
        self._default_factory = fnew

    def __set_name__(self, owner: type[_T], name: str):
        self.__name__ = name

    def __get__(self, obj: _T, objtype: type[_T]) -> _VT:
        assert self.__name__ is not None
        self._check_dict(obj)

        if obj is None:
            return self._make_default(obj, objtype)

        # Look for the attribute in the instance first.
        if self.__name__ in obj.__dict__:
            return obj.__dict__[self.__name__]
        else:
            value = self._make_default(obj, objtype)
            obj.__dict__[self.__name__] = value
            return value

    def __set__(self, obj: _T, value: _VT, /) -> None:
        assert self.__name__ is not None
        self._check_dict(obj)

        obj.__dict__[self.__name__] = value

    def __delete__(self, obj: _T) -> None:
        self._check_dict(obj)

        if self.__name__ in obj.__dict__:
            del self.__dict__[self.__name__]

    def _check_dict(self, obj: _T):
        try:
            obj.__dict__
        except AttributeError:
            raise TypeError("must have __dict__ attribute")

    def _make_default(self, obj: _T, objtype: type[_T]) -> _VT:
        if self._default_factory is not None:
            return self._default_factory.__get__(obj, objtype)()
        else:
            return self._default


def descriptor(factory: Callable[_P, _VT], /) -> Callable[_P, attribute[_T, _VT]]:
    def wrapper(*args, **kwargs):
        return attribute(lambda _: factory(*args, **kwargs))
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


class variantmethod(attribute[_T, _Variant[_KT, _T, _P, _R_co]], Generic[_KT, _T, _P, _R_co]):
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
        self.__func__ = func
        self.virtual_table = {key: func}
        super().__init__(lambda obj: _Variant(key, obj, self.virtual_table))

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


class Signal(attribute[_T, _Emitter[_VT]]):
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
