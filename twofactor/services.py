import secrets

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import BackupCode, TwoFactor
from .totp import match, new_secret

BACKUP_CODE_COUNT = 10
BACKUP_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0, 1, i, l or o


def normalise_backup(text):
    text = str(text or "")
    if not text.isascii():
        return ""  # lookalike characters can never match
    return "".join(ch for ch in text if ch.isalnum()).lower()


def _hash(code):
    return salted_hmac(
        "spled.twofactor.backup", normalise_backup(code), algorithm="sha256"
    ).hexdigest()


def new_backup_code():
    raw = "".join(secrets.choice(BACKUP_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def looks_like_a_code(text):
    """True if the input could be an authenticator code or a backup code.
    Input that could never succeed is not counted as a guess."""
    plain = "".join(str(text or "").split()).replace("-", "")
    if len(plain) == 6 and plain.isascii() and plain.isdigit():
        return True
    return len(normalise_backup(text)) == 10


def has_two_factor(user):
    return bool(
        user.is_authenticated
        and TwoFactor.objects.filter(user=user, confirmed_at__isnull=False).exists()
    )


def begin_setup(user):
    tf, _ = TwoFactor.objects.get_or_create(user=user, defaults={"secret": new_secret()})
    return tf


def generate_backup_codes(user):
    codes = set()
    while len(codes) < BACKUP_CODE_COUNT:
        codes.add(new_backup_code())
    codes = sorted(codes)
    with transaction.atomic():
        BackupCode.objects.filter(user=user).delete()
        BackupCode.objects.bulk_create(
            [BackupCode(user=user, code_hash=_hash(c)) for c in codes]
        )
    return codes


def confirm_setup(user, code):
    """Turn two-step verification on if the code is right. Returns the backup
    codes (shown once), or None."""
    with transaction.atomic():
        tf = (
            TwoFactor.objects.select_for_update()
            .filter(user=user, confirmed_at__isnull=True)
            .first()
        )
        if tf is None:
            return None
        step = match(tf.secret, code)
        if step is None:
            return None
        tf.confirmed_at = timezone.now()
        tf.last_used_step = step
        tf.save(update_fields=["confirmed_at", "last_used_step"])
        return generate_backup_codes(user)


def verify_code(user, code):
    """Check an authenticator code or a backup code. Returns "totp", "backup" or None."""
    with transaction.atomic():
        tf = (
            TwoFactor.objects.select_for_update()
            .filter(user=user, confirmed_at__isnull=False)
            .first()
        )
        if tf is None:
            return None
        step = match(tf.secret, code, after_step=tf.last_used_step)
        if step is not None:
            tf.last_used_step = step
            tf.save(update_fields=["last_used_step"])
            return "totp"
        if len(normalise_backup(code)) == 10:
            backup = (
                BackupCode.objects.select_for_update()
                .filter(user=user, code_hash=_hash(code), used_at__isnull=True)
                .first()
            )
            if backup is not None:
                backup.used_at = timezone.now()
                backup.save(update_fields=["used_at"])
                return "backup"
    return None


def remaining_backup_codes(user):
    return BackupCode.objects.filter(user=user, used_at__isnull=True).count()


def disable(user):
    with transaction.atomic():
        BackupCode.objects.filter(user=user).delete()
        TwoFactor.objects.filter(user=user).delete()


def format_secret(secret):
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))


def qr_data_uri(text):
    """A QR code as an image address, or None if the optional package is missing."""
    try:
        import segno

        return segno.make(text).svg_data_uri(scale=5, border=2, dark="#0e2a24")
    except Exception:
        return None