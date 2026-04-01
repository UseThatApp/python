# Changelog

All notable changes to this project are documented in this file. This project adheres to
[Semantic Versioning](https://semver.org/) and follows a clear, machine- and human-readable
format inspired by "Keep a Changelog".

## [0.2.0] - 2026-03-29

### Changed

- Breaking change: renamed `get_product` -> `get_version` to better reflect the function's
  purpose and improve clarity of the public API.

### Migration notes

If you previously imported or called `get_product`, update your code as follows:

Before:

```python
from usethatapp.webapps import get_product

result = get_product(message, public_key_path, private_key_path)
```

After:

```python
from usethatapp.webapps import get_version

result = get_version(message, public_key_path, private_key_path)
```

The function signature and behavior remain the same aside from the name change.

## [0.1.0] - 2026-03-19

### Added

- Initial release: introduced `get_product` (now renamed to `get_version`) to retrieve
  licensing or version information from signed/encrypted messages.

---

For more details, including commit-level history, see the project's Git repository.
