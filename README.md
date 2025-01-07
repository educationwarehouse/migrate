# Educationwarehouse's Migrate

[![PyPI - Version](https://img.shields.io/pypi/v/edwh-migrate.svg)](https://pypi.org/project/edwh-migrate)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/edwh-migrate.svg)](https://pypi.org/project/edwh-migrate)

-----

**Table of Contents**

- [Installation](#installation)
- [Documentation](#documentation)
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

* `MIGRATE_URI` (required): regular `postgres://user:password@host:port/database` or `sqlite:///path/to/database` URI
* `DATABASE_TO_RESTORE`: path to a (compressed) SQL file to restore. `.xz`,`.gz` and `.sql` are supported.
* `MIGRATE_CAT_COMMAND`: for unsupported compression formats, this command decompresses the file and produces sql on the
  stdout.
* `SCHEMA_VERSION`: Used in case of schema versioning. Set by another process.
* `REDIS_HOST`: If set, all keys of the redis database 0 will be removed.
* `MIGRATE_TABLE`: name of the table where installed migrations are stored. Defaults to `ewh_implemented_features`. 
* `FLAG_LOCATION`: when using schema versioned lock files, this directory is used to store the flags. Defaults to `/flags`.
* `CREATE_FLAG_LOCATION` (bool): should the directory above be created if it does not exist yet? Defaults to 0 (false). 
* `SCHEMA`: (for postgres) set the default namespace (`search_path`). Defaults to `public`.
* `USE_TYPEDAL`: pass a TypeDAL instance to migrations instead of a regular pyDAL.

### Config: pyproject.toml

You can also set your config variables via the `[tool.migrate]` key in `pyproject.toml`.
First, these variables are loaded and then updated with variables from the environment.
This way, you can set static variables (the ones you want in git, e.g. the `migrate_table` name or path to the backup to
restore) in the toml, and keep private/dynamic vars in the environment (e.g. the database uri or schema version).

Example:

```toml
[tool.migrate]
migrate_uri = "" # filled in by .env
database-to-restore = "migrate/data/db_backup.sql"
# ...
```

### Creating a `migrations.py`

```python
from edwh_migrate import migration

@migration
def feature_1(db):
    print("feature_1")
    return True


@migration(requires=[feature_1]) # optional `requires` ensures previous migration(s) are installed
def functionalname_date_sequencenr(db: pydal.DAL):
    db.executesql("""
        CREATE TABLE ...
    """)
    db.commit()
    return True

```

### Usage

When your configuration is set up properly and you have a file containing your migrations, you can simply run:

```bash
migrate
# or, to use a different name than migrations.py:
migrate path/to/my/migrate_file.py
```

## Advanced Topics

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
                '''
                CREATE MATERIALIZED VIEW my_example_view AS
                SELECT id, name FROM my_table;
                '''
            )

        def down(self):
            # Logic to reverse the migration
            self.db.executesql(
                '''
                DROP MATERIALIZED VIEW IF EXISTS my_example_view;
                '''
            )

    class AnotherExampleView(ViewMigrationManager):
        # This class depends on MyExampleView_V1
        uses = (MyExampleView_V1,)

        def up(self):
            # Logic to apply the migration
            self.db.executesql(
                '''
                CREATE MATERIALIZED VIEW another_example_view AS
                SELECT id, name FROM my_example_view;
                '''
            )

        def down(self):
            # Logic to reverse the migration
            self.db.executesql(
                '''
                DROP MATERIALIZED VIEW IF EXISTS another_example_view;
                '''
            )
    ```

2. **Define the `previous_migration`**: Create a migration function that serves as the prerequisite for `MyExampleView_V1`.

    ```python
    from edwh_migrate import migration

    @migration
    def previous_migration(db):
        db.executesql('''
        CREATE TABLE my_table (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255)
        );
        ''')
        db.commit()
        return True
    ```

3. **Use the Subclass in a Migration Function**: Utilize the subclass in a migration function to manage the view migration context.

    ```python
    from edwh_migrate import migration

    @migration
    def upgrade_some_source_table_that_my_example_view_depends_on(db):
        with MyExampleView_V1(db):
            db.executesql('''
            ALTER TABLE my_table
            ADD COLUMN new_column VARCHAR(255);
            ''')
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

## License

`edwh-migrate` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
