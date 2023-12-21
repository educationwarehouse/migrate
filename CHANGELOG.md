# Changelog

<!--next-version-placeholder-->

## v0.7.1 (2023-12-21)
### Fix
* If the ewh_implemented_features .table file already existed, setup_db could crash ([`04d2149`](https://github.com/educationwarehouse/migrate/commit/04d214917fe41bfc3637075a18394b7e7561064f))

## v0.7.0 (2023-12-15)


## v0.7.0-beta.1 (2023-12-15)
### Feature
* Support typedal via USE_TYPEDAL=1 or toml ([`744430d`](https://github.com/educationwarehouse/migrate/commit/744430d4f9b829115a12d90e290ef731c449bdff))

## v0.6.3 (2023-11-22)
### Fix
* Remove lock file on base exception since keyboardinterrupt also means the migration failed! ([`9fb8c3e`](https://github.com/educationwarehouse/migrate/commit/9fb8c3ec27812611913bd50c3558f4f08133616b))

## v0.6.2 (2023-11-21)
### Fix
* Expose console_hook for external library usage ([`56ae0b6`](https://github.com/educationwarehouse/migrate/commit/56ae0b69f407847fa21e4754e2770d7c0ad3ca88))
* Every function can now be passed an existing config. ([`efc4c41`](https://github.com/educationwarehouse/migrate/commit/efc4c41ed985fbea6722b6dea4b0ace776e20939))
* You can now choose a migrations file in the config (toml or env) ([`2341fab`](https://github.com/educationwarehouse/migrate/commit/2341faba01cd5c8e77461e5c53e3df6ed59176a6))

## v0.6.1 (2023-11-20)
### Fix
* Still load .env if pyproject.toml exists, so we can combine those configs ([`69c8e73`](https://github.com/educationwarehouse/migrate/commit/69c8e73a0fbcce01a14ba3f32c041c8c0db78270))

## v0.6.0 (2023-11-14)
### Feature
* Improved config via configuraptor; allow chaging MIGRATE_TABLE from ewh_implemented_features ([`caadaed`](https://github.com/educationwarehouse/migrate/commit/caadaedaec90838255727d76cbbb8b3e1e91710c))
* Optional `db_folder` from config and `db_uri` as alias for `migrate_uri` ([`3530cfc`](https://github.com/educationwarehouse/migrate/commit/3530cfcf1a08e155ff01a8869abda650bede3712))
* Config: Better error handling by replacing `suppress` with normal try-catch (-> more informative tracebacks) ([`1dc044f`](https://github.com/educationwarehouse/migrate/commit/1dc044fd8c66389bb96a0ade69e62ea3fb924997))
* `config` can now be imported from the package directly ([`c06ab11`](https://github.com/educationwarehouse/migrate/commit/c06ab11a179919d4ac12dd03ceb91ec428033595))
* **schema:** Choose schema from config (name or False) ([`c877f36`](https://github.com/educationwarehouse/migrate/commit/c877f360bbf34ba5105b6834c80f54579c35cfce))
* Custom flag directory + refactor console hooks to use list of args (after 0) ([`132de79`](https://github.com/educationwarehouse/migrate/commit/132de79caa79fc9f2ea276abf22e24083d65b6c4))
* **mypy:** Improved type hints for @migration decorator ([`afa987a`](https://github.com/educationwarehouse/migrate/commit/afa987af1ca8cc9e7a4d65d047b0882f40999cec))

### Fix
* More pytests + coverage ([`b2eefd2`](https://github.com/educationwarehouse/migrate/commit/b2eefd22771e5569432652e5925a8ab312544e69))
* **tests:** More test coverage and minor fix in backup restore function ([`41eb4bd`](https://github.com/educationwarehouse/migrate/commit/41eb4bd0117ecf1e3c26f49e6d5bb546372adc2d))
* Tests should import from src so you don't have to keep installing the module to test it ([`8d5c886`](https://github.com/educationwarehouse/migrate/commit/8d5c886dae902fe2a9e7710631595243f4ec673e))

### Documentation
* Show example with pydal2sql to create CREATE TABLE for ewh_implemented_features ([`ac04306`](https://github.com/educationwarehouse/migrate/commit/ac0430604b6302f099ec541b2a7d5b7bb5b8ee1c))
* Added example via docker-compose ([`9a8de23`](https://github.com/educationwarehouse/migrate/commit/9a8de23c0675beb09c4599104efa7f95552b586d))
* Added new config keys and included usage example ([`13fdd6c`](https://github.com/educationwarehouse/migrate/commit/13fdd6c1aa12f3142d328424791d63dc9fc2590d))

## v0.5.2 (2023-11-08)
### Fix
* **pgbouncer:** Set search path (schema) to public after restoring db ([`c70ccb0`](https://github.com/educationwarehouse/migrate/commit/c70ccb0de377b35037de79d32a3d6ccadbf870f2))

## v0.5.1 (2023-08-02)
### Fix
* Solves the wrong object being sent as a set of arguments. psql should work ([`9743b3f`](https://github.com/educationwarehouse/migrate/commit/9743b3f4423b729a1bf739be0d2dc2052973bb1c))

## v0.5.0 (2023-08-02)
### Feature
* Supports passwords in database uri's using uri scheme instead of -U -p arguments etc. psql is compatible with the `postgres://` uri scheme, so why bother? ([`80f09ce`](https://github.com/educationwarehouse/migrate/commit/80f09ce15369ee6756afedc2a4d44e176a1c95fb))

## v0.4.4 (2023-08-02)
### Fix
* Fixing an issue with long_running, and rollback the transaction after an error on a non-existing table. ([`accfbe4`](https://github.com/educationwarehouse/migrate/commit/accfbe4fd3ee0c9ea6b9933025a33166a16d9105))

## v0.4.3 (2023-05-15)
### Fix
* BaseExceptionGroup does not exist in 3.10 yet ([`3433a4f`](https://github.com/educationwarehouse/migrate/commit/3433a4fda0d6ebfb2a551d9f5c3feb4f51e6afc0))

## v0.4.2 (2023-05-04)
### Documentation
* **migrate:** Changed package name from '-' to edwh-migrate and added extra's dev dependencies ([`ae3eef6`](https://github.com/educationwarehouse/migrate/commit/ae3eef6a1e2db47d03fcd60a57d768d79b7f4a32))

## v0.4.1 (2023-05-04)
### Fix
* Better troubleshooting support for the sys.argv[1] argument ([`8a21505`](https://github.com/educationwarehouse/migrate/commit/8a21505307618a45d993b772f1ea40e0c4b3343f))

## v0.4.0 (2023-05-04)
### Feature
* Support for argv[1] as a path to a python file, or to the folder where `migrations.py` is stored. ([`7d0aba6`](https://github.com/educationwarehouse/migrate/commit/7d0aba641907ca4100a10a3fba67e3286ab8f5c6))

## v0.3.0 (2023-05-04)
### Feature
* Failed tests will sometimes be written to db; better support for sqlite; better unpacker code, better docs, more translation into english ([`7701670`](https://github.com/educationwarehouse/migrate/commit/7701670b8e4adc234a2ae8abeac8780adda65330))

### Documentation
* **env:** Environment variables documented ([`71950c2`](https://github.com/educationwarehouse/migrate/commit/71950c20d6dbed59892192b7344dafd109131e9f))

## v0.2.0 (2023-04-22)
### Feature
* Sqlite3 is now a possible alternative; the schema lockfile mechanism is now optional. ([`8e1baa8`](https://github.com/educationwarehouse/migrate/commit/8e1baa8afe640234b36587fff2d2d6a0774fde63))

## v0.1.0 (2023-04-22)
### Feature
* Initial release ([`29c4b05`](https://github.com/educationwarehouse/migrate/commit/29c4b0526dacf428d4665e357a0081c00f7372e8))
