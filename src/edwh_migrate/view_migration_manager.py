import abc
import os
import types
import typing as t
import warnings

from .constants import CURRENT_MIGRATION
from .helpers import classproperty

E = t.TypeVar("E", bound=Exception)

if t.TYPE_CHECKING:
    from pydal import DAL as pyDAL
    from typedal import TypeDAL

    DAL: t.TypeAlias = pyDAL | TypeDAL
else:
    from pydal import DAL


class ViewMigrationManager(abc.ABC):
    """
    A base class for managing the lifecycle of view migrations in a database using context management.

    This class provides an abstract framework for creating, managing, and reversing database views,
    ensuring that migrations are properly handled with dependencies between different migrations.

    Attributes:
        uses (list[typing.Type["ViewMigrationManager"]]): A list of other ViewMigrationManager classes
            that the current class depends on.
        replaces: The previous manager for this view. Once this manager is active, the previous
            manager is no longer rebuilt, including during the activation migration.

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
    def uses(cls) -> t.Iterable[t.Type["ViewMigrationManager"]]:
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
    _used_by: list[t.Type["ViewMigrationManager"]]
    _replaced_by: list[t.Type["ViewMigrationManager"]]
    replaces: t.Optional[t.Type["ViewMigrationManager"]] = None

    may_go_up = False

    def __init__(self, db: DAL, cache: t.Optional[dict] = None):
        """
        Initialize the ViewMigrationManager with a database connection.

        Args:
            db (DAL): The database connection object.
        """
        if cache is None:
            cache = {}

        self.db = db
        self._scheduled = False
        self._skip_down = False
        self._ordered_instances: t.Optional[list["ViewMigrationManager"]] = None
        cache[self.__class__] = self

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
        related = list(self._replaced_by)
        if self.replaces is not None:
            related.append(self.replaces)
        self.replacement_instances = []
        for cls in related:
            if cls not in cache:
                cache[cls] = cls(db, cache)
            self.replacement_instances.append(cache[cls])

    def __init_subclass__(cls) -> None:
        cls._replaced_by = []
        if not hasattr(cls, "_used_by"):
            # note: this has to be created here,
            # otherwise 'used_by' is a shared reference between all subclasses!!!
            cls._used_by = []

        # pycharm doesn't really understand abstract class properties so cast the type here:
        dependencies = t.cast(t.Iterable[t.Type["ViewMigrationManager"]], cls.uses)

        for dependency_cls in dependencies:
            dependency_cls._used_by.append(cls)
        if cls.replaces is not None:
            cls.replaces._replaced_by.append(cls)

    def should_run(self) -> bool:
        """
        Perform checks to know whether this dependency is active.
        """
        return self.check_since() and self.check_until() and not self._has_active_replacement()

    def _has_active_replacement(self) -> bool:
        return self._active_manager() is not self

    def _active_manager(self) -> "ViewMigrationManager":
        for item in self.replacement_instances:
            if item.__class__ in self._replaced_by:
                selected = item._active_manager()
                if selected.check_since() and selected.check_until():
                    return selected
        return self

    def _uses_replacements(self) -> bool:
        visited = set()

        def check(item):
            if item in visited:
                return False
            visited.add(item)
            return bool(item.replacement_instances) or any(check(dependent) for dependent in item.instances)

        return check(self)

    def _migration_order(self) -> list["ViewMigrationManager"]:
        """Collect affected managers once and order dependencies before their dependents."""
        affected = {}
        visited = {}

        def collect(item):
            if item.__class__ in visited:
                return
            visited[item.__class__] = item
            active = item.check_since() and item.check_until()
            retiring = any(
                replacement.since == os.environ.get(CURRENT_MIGRATION)
                and replacement.check_since()
                and replacement.check_until()
                for replacement in item.replacement_instances
                if replacement.__class__ in item._replaced_by
            )
            if active and (item.should_run() or retiring):
                affected[item.__class__] = item
            if active or item._has_active_replacement():
                for dependent in item.instances:
                    collect(dependent)
            for related in item.replacement_instances:
                collect(related)

        collect(self)
        ordered = []
        pending = set()
        completed = set()

        def order(item):
            if item in completed:
                return
            if item in pending:
                raise ValueError("Circular view migration dependencies")
            pending.add(item)
            for dependency in item.uses:
                if dependency in affected:
                    order(affected[dependency])
                if dependency in visited:
                    selected = visited[dependency]._active_manager()
                    if selected.__class__ in affected:
                        order(selected)
            pending.remove(item)
            completed.add(item)
            ordered.append(item)

        for item in affected.values():
            order(item)
        return ordered

    def _run_ordered_hook(self, item, method, *args):
        item._scheduled = True
        try:
            if item is self:
                # The root's override already called into this base method.
                getattr(ViewMigrationManager, method)(item, *args)
            else:
                getattr(item, method)(*args)
        finally:
            item._scheduled = False

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
        if self._scheduled:
            if not self._skip_down:
                self.down()
            self.may_go_up = True
            return

        if not self._uses_replacements():
            if not self.should_run():
                return
            for item in reversed(self.instances):
                item.__enter__()
            self.down()
            self.may_go_up = True
            return

        self._ordered_instances = self._migration_order()
        retiring = {item.__class__ for item in self._ordered_instances if not item.should_run()}
        for item in reversed(self._ordered_instances):
            # The installed predecessor owns the drop at handover. Both versions may
            # target the same relation, so do not execute the replacement's drop too.
            item._skip_down = item.replaces in retiring
            self._run_ordered_hook(item, "__enter__")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        tb: types.TracebackType | None,
    ) -> None:
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

        if self._scheduled:
            if self.may_go_up and self.should_run():
                self.up()
            self.may_go_up = False
            return

        if self._ordered_instances is None:
            if not self.should_run() or not self.may_go_up:
                return
            self.up()
            self.may_go_up = False
            for item in self.instances:
                item.__exit__(exc_type, exc_value, tb)
            return

        for item in self._ordered_instances:
            self._run_ordered_hook(item, "__exit__", exc_type, exc_value, tb)
