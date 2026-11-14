import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

DIGITS = 6
PERIOD = 30
WINDOW = 1  # accept the previous, current and next 30-second step


def now():
    return time.time()


def new_secret():
    """160 random bits as 32 base32 characters."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def _key(secret):
    text = secret.replace(" ", "").upper()
    text += "=" * (-len(text) % 8)
    return base64.b32decode(text)


def hotp(secret, counter, digits=DIGITS):
    digest = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % (10 ** digits)).zfill(digits)


def step_at(moment=None):
    return int((now() if moment is None else moment) // PERIOD)


def totp(secret, moment=None, digits=DIGITS):
    return hotp(secret, step_at(moment), digits)


def match(secret, code, moment=None, after_step=-1):
    """Return the 30-second step this code belongs to, or None. Steps at or
    before after_step are refused, so a code can't be used twice."""
    text = "".join(str(code or "").split()).replace("-", "")
    if len(text) != DIGITS or not text.isascii() or not text.isdigit():
        return None
    current = step_at(moment)
    found = None
    for step in range(current - WINDOW, current + WINDOW + 1):
        equal = hmac.compare_digest(hotp(secret, step), text)
        if equal and step > after_step and found is None:
            found = step
    return found


def provisioning_uri(secret, account, issuer="Spled"):
    label = f"{quote(issuer, safe='')}:{quote(account, safe='@')}"
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer, safe='')}"
        f"&algorithm=SHA1&digits={DIGITS}&period={PERIOD}"
    )