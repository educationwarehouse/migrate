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

## License

`edwh-migrate` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
