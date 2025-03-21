import abc
import os
import types
import typing
import warnings

from pydal import DAL

from .constants import CURRENT_MIGRATION
from .helpers import classproperty

E = typing.TypeVar("E", bound=Exception)


class ViewMigrationManager(abc.ABC):
    """
    A base class for managing the lifecycle of view migrations in a database using context management.

    This class provides an abstract framework for creating, managing, and reversing database views,
    ensuring that migrations are properly handled with dependencies between different migrations.

    Attributes:
        uses (list[typing.Type["ViewMigrationManager"]]): A list of other ViewMigrationManager classes
            that the current class depends on.

    Example:
        1. Define a subclass that implements specific migration logic:

        ```python
        class MyExampleView_V2(ViewMigrationManager):
            def up(self):
                self.db.executesql(
                    '''
                    CREATE MATERIALIZED VIEW my_example_view AS
                    SELECT id, name FROM my_table;
                    '''
                )

            def down(self):
                self.db.executesql(
                    '''
                    DROP MATERIALIZED VIEW IF EXISTS my_example_view;
                    '''
                )
        ```

        2. Use the subclass in a migration function:

        ```python
        @migration
        def upgrade_some_source_table_that_my_example_view_depends_on(db):
            with MyExampleView_V2(db):
                db.executesql('''
                -- Perform operations that might affect `my_example_view`
                ''')
            db.commit()
            return True
        ```

        In this example:
        - The `down` method will drop the `my_example_view` before the block of code is executed.
        - The SQL operations inside the block will run.
        - The `up` method will recreate the `my_example_view` after the block completes.

    Methods:
        __init__(db: DAL):
            Initializes the manager with the provided database connection.

        __init_subclass__():
            Handles subclass initialization, ensuring proper tracking of dependencies
            using the `uses` and `used_by` attributes.

        up():
            Abstract method to define the migration logic. Subclasses must implement this to
            define how the view should be created or modified.

        down():
            Abstract method to define the rollback logic. Subclasses must implement this to
            define how the view should be dropped or reverted.

        __enter__():
            Context management for reversing the migration before executing a block of code.

        __exit__(exc_type, exc_value, traceback):
            Context management for applying the migration after a block of code has executed,
            regardless of whether an exception was raised.
    """

    @abc.abstractmethod
    @classproperty
    def uses(cls) -> typing.Iterable[typing.Type["ViewMigrationManager"]]:
        """
        List/tuple of view migration classes that this one depends on.
        """
        warnings.warn(f"Class {cls} has default 'uses'? This may indicate missing dependencies!")
        return ()

    @classproperty
    def since(cls) -> str:
        """
        Migration that must have run before this migration becomes relevant.

        Otherwise, old migrations may break due to new dependencies and we definitely don't want that!
        """
        return ""

    @classproperty
    def until(cls) -> str:
        """
        Migration after which this class should no longer be used.

        This attribute specifies the migration after which this view migration manager
        should not be utilized. It ensures that new migrations do not use views or logic
        from this class beyond the specified migration.
        """
        return ""

    # note: manually setting `used_by` is deprecated!
    _used_by: list[typing.Type["ViewMigrationManager"]]

    may_go_up = False

    def __init__(self, db: DAL, cache: typing.Optional[dict] = None):
        """
        Initialize the ViewMigrationManager with a database connection.

        Args:
            db (DAL): The database connection object.
        """
        if cache is None:
            cache = {}

        self.db = db

        used_by = getattr(self, "_used_by", [])

        assert self.__class__ not in used_by, "Recursion prevented..."

        # self.instances = tuple(_(db, cache) for _ in used_by)

        instances = []
        for dep in used_by:
            if dep in cache:
                # re-used classes should use the same instance (but configuraptor.Singleton doesn't work here):
                i = cache[dep]
            else:
                i = dep(db, cache)
                cache[dep] = i
            instances.append(i)

        self.instances = instances

    def __init_subclass__(cls) -> None:
        if not hasattr(cls, "_used_by"):
            # note: this has to be created here,
            # otherwise 'used_by' is a shared reference between all subclasses!!!
            cls._used_by = []

        # pycharm doesn't really understand abstract class properties so cast the type here:
        dependencies = typing.cast(typing.Iterable[typing.Type["ViewMigrationManager"]], cls.uses)

        for dependency_cls in dependencies:
            dependency_cls._used_by.append(cls)

    def should_run(self) -> bool:
        """
        Perform checks to know whether this dependency is active.
        """
        return self.check_since() and self.check_until()

    def check_since(self) -> bool:
        """
        If a 'since' is specified, that migration should have run already at this point.
        """
        db = self.db

        if not (since := self.since):
            return True

        if os.environ[CURRENT_MIGRATION] == since:
            return True

        query = db.ewh_implemented_features.name == since
        query &= db.ewh_implemented_features.installed == True

        return db(query).count() > 0

    def check_until(self) -> bool:
        """
        If an 'until' is specified, that migration should not have run yet at this point.
        """
        db = self.db

        if not (until := self.until):
            return True

        query = db.ewh_implemented_features.name == until
        query &= db.ewh_implemented_features.installed == True

        return db(query).count() == 0

    @abc.abstractmethod
    def up(self) -> None:
        """
        Defines the logic to apply the migration, such as creating or modifying views.
        This method should be implemented in subclasses for the specific migration task.
        """

    @abc.abstractmethod
    def down(self) -> None:
        """
        Defines the logic to reverse the migration, such as dropping or reverting views.
        This method should be implemented in subclasses for the specific migration task.
        """

    def __enter__(self) -> None:
        """
        Context management method for entering the runtime context related to the migration.
        By default, this calls the `down` method to reverse or remove the migration before executing
        the block of code.

        Returns:
            ViewMigrationManager: The current instance of the migration manager.
        """
        if not self.should_run():
            return

        for item in reversed(self.instances):
            item.__enter__()

        self.down()
        self.may_go_up = True

    def __exit__(self, exc_type: typing.Type[E], exc_value: E, tb: types.TracebackType) -> None:
        """
        Context management method for exiting the runtime context related to the migration.
        This method calls the `up` method to apply the migration after the block of code finishes,
        regardless of whether an exception was raised.

        Args:
            exc_type (type): The exception type raised during execution (if any).
            exc_value (Exception): The exception instance raised during execution (if any).
            tb (traceback): The traceback object related to the exception (if any).
        """
        if exc_type:
            # block failed, don't try to go up!
            return

        if not self.should_run():
            return

        if not self.may_go_up:
            # didn't go down properly or already executed!
            return

        self.up()
        self.may_go_up = False

        for item in self.instances:
            item.__exit__(exc_type, exc_value, tb)
