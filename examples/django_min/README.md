# django_min — minimal UseThatApp Django example

Boots a single-view Django app that accepts a launch envelope at
`/uta/launch/` and calls `get_version()` for the resulting `user_key`.

## Run

```bash
pip install usethatapp django

# Generate a developer keypair (one-time):
python -c "
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
open('dev.pem','wb').write(k.private_bytes(serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
open('dev.pub','wb').write(k.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
"

export UTA_APP_ID=11111111-2222-3333-4444-555555555555
export UTA_PRIVATE_KEY="$(cat dev.pem)"
export UTA_MARKET_PUBLIC_KEY="$(cat market.pub)"

python app.py runserver 0.0.0.0:8000
```

