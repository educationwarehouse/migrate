# coding=utf-8
# SPDX-FileCopyrightText: 2023-present Remco <remco@educationwarehouse.nl>
#
# SPDX-License-Identifier: MIT
"""
When writing new tasks, make sure:
 * /!\ executesql() returns tuples, explicitly use as_dict or as_ordered_dict to have easy acces for results
 * /!\ arguments and placeholders use the `where gid = %(gid)s` syntax, where gid should be a key in the `placeholders`
   argument given to executesql
 * /!\ make sure to use schema reference:
   - public."user"
   - public.item
   forget and fail...

"""
from .migrate import registered_functions, migration, setup_db, UnknownConfigException, recover_database_from_backup, \
    InvalidConfigException, activate_migrations

__all__ = [
    registered_functions,
    migration,
    activate_migrations,
    setup_db,
    recover_database_from_backup,
    InvalidConfigException,
    UnknownConfigException,
]
