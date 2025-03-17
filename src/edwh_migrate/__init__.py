# coding=utf-8
# SPDX-FileCopyrightText: 2023-present Remco <remco@educationwarehouse.nl>
#
# SPDX-License-Identifier: MIT
"""
This file exposes the most important functions and classes.

When writing new tasks, make sure:
 * ! executesql() returns tuples, explicitly use as_dict or as_ordered_dict to have easy acces for results
 * ! arguments and placeholders use the `where gid = %(gid)s` syntax, where gid should be a key in the `placeholders`
   argument given to executesql
 * ! make sure to use schema reference:
   - public."user"
   - public.item
   forget and fail...

"""

from .helpers import classproperty
from .migrate import (
    Config,
    InvalidConfigException,
    UnknownConfigException,
    activate_migrations,
    get_config,
    list_migrations,
    mark_migration,
    migration,
    # registered_functions is deprecated in favor of
    migrations,
    recover_database_from_backup,
    setup_db,
)
from .migrate import _console_hook as console_hook
from .view_migration_manager import ViewMigrationManager

__all__ = [
    "migration",
    # registered_functions is deprecated in favor of
    "migrations",
    "activate_migrations",
    "setup_db",
    "recover_database_from_backup",
    "InvalidConfigException",
    "UnknownConfigException",
    "Config",
    "get_config",
    "console_hook",
    "list_migrations",
    "mark_migration",
    "ViewMigrationManager",
    "classproperty",
]
