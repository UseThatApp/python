# Changelog

All notable changes to this project are documented in this file. This project adheres to
[Semantic Versioning](https://semver.org/) and follows a clear, machine- and human-readable
format inspired by "Keep a Changelog".

## [0.3.0] - 2026-04-10

### Changed

- Breaking change: `get_version` now accepts a full `requestAccessLevel()` envelope instead of
  a flat message dict. The first parameter has been renamed from `message` to `envelope` and
  must contain a `type` field (`"level"`) and a nested `message` dict with `contents` and
  `signature`.
- Error envelopes (`type == "error"`) are now detected and raise a `ValueError` with the
  server's error description.
- Envelope `type` is validated; unexpected types raise a `ValueError`.

### Migration notes

The input structure has changed. Update your code as follows:

Before (0.2.0):

```python
from usethatapp.webapps import get_version

msg = {"signature": "0x...", "contents": "0x..."}
result = get_version(msg, public_key_path, private_key_path)
```

After (0.3.0):

```python
from usethatapp.webapps import get_version

envelope = {
    "type": "level",
    "responseTo": "<request-id>",
    "message": {
        "contents": "0x...",
        "signature": "0x..."
    }
}
result = get_version(envelope, public_key_path, private_key_path)
```

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
