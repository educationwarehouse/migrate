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

### Environment variables

* `MIGRATE_URI`: regular `postgres://user:password@host:port/database` or `sqlite:///path/to/database` URI
* `DATABASE_TO_RESTORE`: path to a (compressed) SQL file to restore. `.xz`,`.gz` and `.sql` are supported.  
* `MIGRATE_CAT_COMMAND`: for unsupported compression formats, this command decompresses the file and produces sql on the stdout. 
* `SCHEMA_VERSION`: Used in case of schema versioning. Set by another process.
* `REDIS_HOST`: If set, all keys of the redis database 0 will be removed. 


## License

`edwh-migrate` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
