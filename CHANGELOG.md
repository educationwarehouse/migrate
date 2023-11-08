# Changelog

<!--next-version-placeholder-->

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
