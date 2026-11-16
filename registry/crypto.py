import base64
import binascii
import os

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Backups need the cryptography package. Run: pip install -r requirements-prod.txt"
    ) from exc

MAGIC = b"SPLEDENC1"
PREFIX_LEN = 8
TAG_LEN = 16
CHUNK = 1024 * 1024


class CryptoError(Exception):
    pass


def generate_key():
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def parse_key(value):
    text = str(value or "").strip()
    if not text:
        raise CryptoError("BACKUP_ENCRYPTION_KEY is not set. Make one with: python manage.py backup_key")
    try:
        key = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        raise CryptoError("BACKUP_ENCRYPTION_KEY is not valid. Make a new one with: python manage.py backup_key")
    if len(key) != 32:
        raise CryptoError("BACKUP_ENCRYPTION_KEY must decode to exactly 32 bytes. Make one with: python manage.py backup_key")
    return key


def _nonce(prefix, counter):
    return prefix + counter.to_bytes(4, "big")


def _aad(final):
    # Marking the last chunk means a file cut short at a chunk boundary is detected.
    return b"\x01" if final else b"\x00"


def encrypt_stream(src, dst, key):
    aes = AESGCM(key)
    prefix = os.urandom(PREFIX_LEN)
    dst.write(MAGIC + prefix)
    counter = 0
    current = src.read(CHUNK)
    while True:
        following = src.read(CHUNK)
        final = not following
        dst.write(aes.encrypt(_nonce(prefix, counter), current, _aad(final)))
        if final:
            return
        counter += 1
        current = following


def decrypt_stream(src, dst, key):
    aes = AESGCM(key)
    header = src.read(len(MAGIC) + PREFIX_LEN)
    if len(header) != len(MAGIC) + PREFIX_LEN or not header.startswith(MAGIC):
        raise CryptoError("This is not a Spled encrypted file.")
    prefix = header[len(MAGIC):]
    size = CHUNK + TAG_LEN
    current = src.read(size)
    if not current:
        raise CryptoError("The file ends right after its header: it is incomplete.")
    counter = 0
    while True:
        following = src.read(size)
        final = not following
        try:
            plain = aes.decrypt(_nonce(prefix, counter), current, _aad(final))
        except (InvalidTag, ValueError):
            raise CryptoError("Could not decrypt: wrong key, or the file is damaged or incomplete.")
        dst.write(plain)
        if final:
            return
        counter += 1
        current = following


def encrypt_file(src_path, dst_path, key):
    with open(src_path, "rb") as src, open(dst_path, "wb") as dst:
        encrypt_stream(src, dst, key)


def decrypt_file(src_path, dst_path, key):
    """Never leaves a partly decrypted file behind."""
    try:
        with open(src_path, "rb") as src, open(dst_path, "wb") as dst:
            decrypt_stream(src, dst, key)
    except BaseException:
        try:
            os.unlink(dst_path)
        except OSError:
            pass
        raise