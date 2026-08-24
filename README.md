# Educationwarehouse's Migrate

[![PyPI - Version](https://img.shields.io/pypi/v/edwh-migrate.svg)](https://pypi.org/project/edwh-migrate)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/edwh-migrate.svg)](https://pypi.org/project/edwh-migrate)

-----

**Table of Contents**

- [Installation](#installation)
- [Documentation](#documentation)
  - [Config: Environment variables](#config-environment-variables)
  - [Config: pyproject.toml](#config-pyprojecttoml)
  - [Creating a `migrations.py`](#creating-a-migrationspy)
  - [Usage](#usage)
- [Advanced Topics](#advanced-topics)
- [Library usage](#library-usage)
- [License](#license)

## Installation

```console
pip install edwh-migrate
# or to include extra dependencies (psycopg2, redis):
pip install edwh-migrate[full]
```

## Documentation

### Config: Environment variables

These variables can be set in the current environment or via `.env`:

* `MIGRATE_URI` (required): regular `postgres://user:password@host:port/database` or `sqlite:///path/to/database` URI.
  `DB_URI` can be used as an alias.
* `MIGRATIONS_FILE` (optional): path to a file containing migrations. By default, a file called `migrations.py` in the
  working directory is used.
* `DATABASE_TO_RESTORE`: path to a (compressed) SQL file to restore when the migrations table is missing. `.xz`,`.gz`
  and `.sql` are supported, for both postgres (via `psql`) and sqlite (via `sqlite3`).
  Defaults to `/data/database_to_restore.sql`.
* `MIGRATE_CAT_COMMAND`: for unsupported compression formats, this command decompresses the file and produces sql on the
  stdout.
* `SCHEMA_VERSION`: Used in case of schema versioning. Set by another process.
  See [Usage](#usage) for the lock file mechanics.
* `REDIS_HOST`: If set, all keys of the redis database 0 will be removed after a successful run.
  A full `redis://host:port` URL is also accepted.
* `MIGRATE_TABLE`: name of the table where installed migrations are stored. Defaults to `ewh_implemented_features`.
* `FLAG_LOCATION`: when using schema versioned lock files, this directory is used to store the flags. Defaults to `/flags`.
* `CREATE_FLAG_LOCATION` (bool): should the directory above be created if it does not exist yet? Defaults to 0 (false).
* `SCHEMA`: (for postgres) set the default namespace (`search_path`). Defaults to `public`.
  Set to `false` to leave the search path untouched.
* `USE_TYPEDAL`: pass a TypeDAL instance to migrations instead of a regular pyDAL.
* `DB_FOLDER`: directory where pyDAL stores its `.table` files and sql logs. Uses the pyDAL default when unset.
* `MIGRATION_ORDERING_MODE`: ordering strategy for migrations. `legacy` (default) keeps definition/import order;
  `intertwined` interleaves migrations from multiple files by trailing numeric suffix (e.g. `..._20260330_001`).
  See [Intertwined ordering](#intertwined-ordering-across-multiple-files).

### Config: pyproject.toml

You can also set your config variables via the `[tool.migrate]` key in `pyproject.toml`.
First, these variables are loaded and then updated with variables from the environment.
This way, you can set static variables (the ones you want in git, e.g. the `migrate_table` name or path to the backup to
restore) in the toml, and keep private/dynamic vars in the environment (e.g. the database uri or schema version).

Keys are case-insensitive and `-` and `_` are interchangeable (`migrate-uri` = `migrate_uri` = `MIGRATE_URI`).

Example:

```toml
[tool.migrate]
migrate_uri = "" # filled in by .env
database-to-restore = "migrate/data/db_backup.sql"
# ...
```

### Creating a `migrations.py`

```python
from pydal import DAL

from edwh_migrate import migration


@migration
def feature_1(db):
    print("feature_1")
    return True


@migration(requires=[feature_1])  # optional `requires` ensures previous migration(s) are installed
def functionalname_date_sequencenr(db: DAL):
    db.executesql("""
        CREATE TABLE ...
    """)
    db.commit()
    return True
```

#### Dependencies: `requires`

`requires` accepts a single function, a single migration name, or a (mixed) list of both:

```python
@migration(requires=feature_1)            # a single function
@migration(requires="feature_1")          # a single migration name
@migration(requires=[feature_1, "other"]) # or a (mixed) list
```

#### Return values

A migration function must return a boolean:

* `True`: the migration is committed and marked as installed.
* `False`: the migration is rolled back and marked as failed. It will be retried on the next run.
* If an exception is raised, the whole run aborts with exit code 1 (and the lock file, when used, is removed so the run
  can be retried).

#### Splitting migrations across multiple files

Larger projects can split migrations over multiple files. Import the other files from your main migrations file;
importing a file registers its migrations:

```python
# migrations.py
import users_migrations  # noqa: F401 -- importing registers the migrations
import billing_migrations  # noqa: F401
```

The final run order is resolved topologically across all imported files:

* migrations with `requires` run as soon as all their requirements have run;
* independent migrations keep their definition/import order (`legacy`) or interleave by date suffix (`intertwined`);
* requiring an unknown migration raises `ValueError: ... depends on ... which is unknown`;
* circular dependencies raise `ValueError: circular dependency detected among migrations: ...`.

### Usage

When your configuration is set up properly and you have a file containing your migrations, you can simply run:

```bash
migrate                            # run ./migrations.py (or MIGRATIONS_FILE)
migrate path/to/my_migrations.py   # use a different file
migrate path/to/folder             # use path/to/folder/migrations.py
migrate --list                     # or -l: show a status table (succeeded / failed / missing)
migrate --help                     # or -h: show usage information
```

#### Lock files

When `SCHEMA_VERSION` is set, a lock file `migrate-{SCHEMA_VERSION}.complete` is created in `FLAG_LOCATION` after a
successful run:

* if the lock file already exists, nothing is run and migrate exits with code 0;
* on failure the lock file is removed, so the migration will be retried;
* failed migrations (installed = false) are also retried on the next run.

## Advanced Topics

### Intertwined ordering across multiple files

When migrations are split over multiple files (e.g. one per app or domain), `legacy` ordering runs them in import
order: everything from the first file, then everything from the second. With `MIGRATION_ORDERING_MODE=intertwined`,
independent migrations are interleaved by their trailing numeric suffix instead:

```python
# users_migrations.py
@migration
def users_create_table_20260330_001(db): ...


@migration
def users_add_email_20260402_001(db): ...


# billing_migrations.py
@migration
def billing_create_table_20260331_001(db): ...
```

Resulting run order with `intertwined`:

1. `users_create_table_20260330_001`
2. `billing_create_table_20260331_001`
3. `users_add_email_20260402_001`

With `legacy` the order would have been: both `users_*` migrations first, then `billing_create_table_20260331_001`.

Notes:

* the suffix convention is `_<date>_<sequence>` (e.g. `_20260330_001`), but any trailing `_number` or
  `_number_number` works;
* migrations without a numeric suffix are treated as suffix `0_0`, so they run first;
* migrations with `requires` always run as soon as their requirements are satisfied, regardless of suffix.

### Using `ViewMigrationManager` via Subclasses

`ViewMigrationManager` is designed to manage the lifecycle of view migrations in a database using context management. It ensures that migrations are properly handled with dependencies between different migrations.

#### Usage

1. **Define Subclasses**: Create subclasses of `ViewMigrationManager` and implement the required methods `up` and `down`.

    ```python
    from edwh_migrate import ViewMigrationManager


    class MyExampleView_V1(ViewMigrationManager):
        # Define dependencies (optional)
        uses = ()
        # Specify a migration that must have run before this class may be used
        since = "previous_migration"

        def up(self):
            # Logic to apply the migration
            self.db.executesql(
                """
                CREATE MATERIALIZED VIEW my_example_view AS
                SELECT id, name FROM my_table;
                """
            )

        def down(self):
            # Logic to reverse the migration
            self.db.executesql(
                """
                DROP MATERIALIZED VIEW IF EXISTS my_example_view;
                """
            )


    class AnotherExampleView(ViewMigrationManager):
        # This class depends on MyExampleView_V1
        uses = (MyExampleView_V1,)

        def up(self):
            # Logic to apply the migration
            self.db.executesql(
                """
                CREATE MATERIALIZED VIEW another_example_view AS
                SELECT id, name FROM my_example_view;
                """
            )

        def down(self):
            # Logic to reverse the migration
            self.db.executesql(
                """
                DROP MATERIALIZED VIEW IF EXISTS another_example_view;
                """
            )
    ```

2. **Define the `previous_migration`**: Create a migration function that serves as the prerequisite for `MyExampleView_V1`.

    ```python
    from edwh_migrate import migration


    @migration
    def previous_migration(db):
        db.executesql("""
        CREATE TABLE my_table (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255)
        );
        """)
        db.commit()
        return True
    ```

3. **Use the Subclass in a Migration Function**: Utilize the subclass in a migration function to manage the view migration context.

    ```python
    from edwh_migrate import migration


    @migration
    def upgrade_some_source_table_that_my_example_view_depends_on(db):
        with MyExampleView_V1(db):
            db.executesql("""
            ALTER TABLE my_table
            ADD COLUMN new_column VARCHAR(255);
            """)
        db.commit()
        return True
    ```

In the example above:
- `MyExampleView_V1` is a subclass of `ViewMigrationManager` that manages the lifecycle of a materialized view named `my_example_view`.
- `AnotherExampleView` is another subclass that depends on `MyExampleView_V1` and manages the lifecycle of another materialized view named `another_example_view`.
- The `up` method in `MyExampleView_V1` contains the logic to create the materialized view `my_example_view`.
- The `down` method in `MyExampleView_V1` contains the logic to drop the materialized view `my_example_view`.
- The `up` method in `AnotherExampleView` contains the logic to create the materialized view `another_example_view` that references `my_example_view`.
- The `down` method in `AnotherExampleView` contains the logic to drop the materialized view `another_example_view`.
- The `since` attribute specifies that a particular migration (`previous_migration`) must have run before `MyExampleView_V1` may be used.
- The `previous_migration` function creates the table `my_table` and serves as a prerequisite for `MyExampleView_V1`.
- The `migration` decorator is used to define a migration function (`upgrade_some_source_table_that_my_example_view_depends_on`) that executes within the context of `MyExampleView_V1`.
- The `with MyExampleView_V1(db)` block ensures that the `down` method is called before the block executes and the `up` method is called after the block completes.

In addition to 'since', the inverse 'until' can also be used.

## Library usage

Besides the CLI, `edwh_migrate` can be used as a library:

| Export | Description |
| --- | --- |
| `migration` | Decorator to register a migration function. |
| `migrations` | The `MigrationStore` singleton holding all registered migrations. |
| `setup_db()` | Connect to the configured database and return a (Type)DAL instance. |
| `activate_migrations()` | Run all pending migrations (without lock file handling). |
| `list_migrations(config, args=None)` | Import (if needed) and list all registered migrations. |
| `mark_migration(db, name, installed)` | Manually store a migration result in the features table. |
| `recover_database_from_backup()` | Restore `DATABASE_TO_RESTORE` into the configured database. |
| `get_config()` / `Config` | Access the resolved configuration. |
| `console_hook(args, config=None)` | The CLI entry point; takes a list of arguments and returns an exit code instead of exiting. |
| `ViewMigrationManager` | Base class for view migrations (see above). |
| `InvalidConfigException`, `UnknownConfigException` | Configuration error types. |

```python
from edwh_migrate import console_hook, get_config, list_migrations

config = get_config()
print(list_migrations(config))  # OrderedDict of registered migrations

exit_code = console_hook([], config)  # run the migrations, 0 on success
```

## License

`edwh-migrate` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
