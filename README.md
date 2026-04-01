
usethatapp
============

A small utility library for UseThatApp web applications providing
helpers to verify signatures and decrypt RSA/OAEP-encrypted messages.

Features
--------
- Verify PSS/SHA256 signatures
- Decrypt OAEP/SHA256 encrypted messages
- Helpers to load RSA keys from files or PEM strings

Install
-------

From PyPI:

```bash
pip install usethatapp
```

Requirements
------------
- Python >= 3.8
- cryptography>=46.0.5,<47

Quick usage
-----------

The package exposes a simple API in `usethatapp.webapps` and helpers in
`usethatapp.encryption`.

Example: verify signature and decrypt message from a JSON payload

```python
from usethatapp.webapps import get_version

message_json = '{"signature": "0xdeadbeef...", "contents": "0x..."}'
public_key_path = "./keys/public.pem"
private_key_path = "./keys/private.pem"

version = get_version(message_json, public_key_path, private_key_path)
if version.lower() == 'pro':
    # expose pro features
    print('Pro version detected!')
else:
    # hide pro features
    print('Free version detected.')
```

Loading keys directly
---------------------

You can also use the `Keys` helper from `usethatapp.encryption` to load
keys from PEM strings or files:

```python
from usethatapp.encryption import Keys

pub = Keys.read_public_key_from_file('keys/public.pem')
priv = Keys.read_private_key_from_file('keys/private.pem')
```

API reference
-------------

- usethatapp.webapps.get_version(message, public_key_path, private_key_path, encoding='utf-8')
  - message: dict or JSON string containing 'signature' and 'contents' (hex strings, optionally prefixed with 0x)
  - public_key_path / private_key_path: paths to PEM key files
  - encoding: attempt to decode decrypted bytes (defaults to 'utf-8')
  - returns: decoded string or raw bytes

- usethatapp.encryption.decrypt_message(private_key, encrypted_message) -> bytes
- usethatapp.encryption.verify_signature(public_key, signature, message) -> bool
- usethatapp.encryption.Keys: convenience class with these methods:
  - read_public_key_from_string(pem_str)
  - read_public_key_from_file(file_path)
  - read_private_key_from_string(pem_str)
  - read_private_key_from_file(file_path)

License
-------

This project is licensed under the MIT License. 
details.

Links
-----
- Homepage: https://github.com/UseThatApp/python
- Documentation: https://docs.usethatapp.com
- Changelog: https://github.com/UseThatApp/python/blob/main/CHANGELOG.md

Contact
-------
For support: support@usethatapp.com

