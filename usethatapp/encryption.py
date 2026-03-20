from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def decrypt_message(private_key: rsa.RSAPrivateKey, encrypted_message: bytes) -> bytes:
    """Decrypts a message

    Note: Uses SHA256 encryption

    Args:
        private_key: the private key used for decryption
        encrypted_message: the message to be decrypted

    Returns:
        The decrypted message
    """
    decrypted_message = private_key.decrypt(
        encrypted_message,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    return decrypted_message


def verify_signature(public_key: rsa.RSAPublicKey, signature: bytes, message: bytes) -> bool:
    """Verifies a signature on an encrypted message

    Note: Uses SHA256 encryption

    Args:
        public_key: the public key used for signature verification
        signature: the signature to be verified
        message: the message signed by the signature

    Returns:
        True if verification passes, False otherwise
    """
    try:
        public_key.verify(
            signature,
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
    except InvalidSignature:
        return False
    return True


class Keys:

    @classmethod
    def read_public_key_from_string(cls, pem_str: str) -> rsa.RSAPublicKey:
        pem_public_key = pem_str.encode().decode('unicode-escape').encode()
        return serialization.load_pem_public_key(pem_public_key)

    @classmethod
    def read_public_key_from_file(cls, file_path: str) -> rsa.RSAPublicKey:
        with open(file_path, 'rb') as key_file:
            return serialization.load_pem_public_key(key_file.read())

    @classmethod
    def read_private_key_from_string(cls, pem_str: str) -> rsa.RSAPrivateKey:
        pem_private_key = pem_str.encode().decode('unicode-escape').encode()
        return serialization.load_pem_private_key(pem_private_key, password=None)

    @classmethod
    def read_private_key_from_file(cls, file_path: str) -> rsa.RSAPrivateKey:
        with open(file_path, 'rb') as key_file:
            return serialization.load_pem_private_key(key_file.read(), password=None)


