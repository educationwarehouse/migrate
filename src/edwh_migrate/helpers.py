import abc
import typing

T = typing.TypeVar("T")

class classproperty:
    def __init__(self, fget: typing.Callable[[typing.Type[T]], typing.Any]) -> None:
        """
        Initialize the classproperty.

        Args:
            fget: A function that takes the class as an argument and returns a value.
        """
        self.fget = fget

    def __get__(self, obj: typing.Any, owner: typing.Type[T]) -> typing.Any:
        """
        Retrieve the property value.

        Args:
            obj: The instance of the class (unused).
            owner: The class that owns the property.

        Returns:
            The value returned by the function.
        """
        return self.fget(owner)


def abstractclassproperty(method: typing.Callable[[typing.Type[T]], typing.Any]) -> classproperty:
    """
    Create an abstract class property.

    Args:
        method: A function that takes the class as an argument and returns a value.

    Returns:
        A classproperty that is also marked as an abstract method.
    """
    return classproperty(abc.abstractmethod(method))
