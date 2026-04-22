import uuid

from django.conf import settings
from django.db import models


class IdentityKey(models.Model):
    """
    Stores the public components of a user's Olm identity keypair.
    Private keys never leave the client; this table is a public key store only.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pm_identity_key",
        db_column="user_id",
    )
    # Curve25519 identity key (base64url, 44 chars max but 64 is safe headroom)
    ik_pub_curve25519 = models.CharField(max_length=64)
    # Ed25519 identity key (base64url, 44 chars max but 64 is safe headroom)
    ik_pub_ed25519 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    rotated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "pm_identitykey"
        verbose_name = "Identity Key"
        verbose_name_plural = "Identity Keys"

    def __str__(self):
        return f"IdentityKey(user_id={self.user_id})"


class SignedPreKey(models.Model):
    """
    The signed prekey for X3DH. In Olm's model this IS the Curve25519 IK,
    signed by the Ed25519 IK. spk_id starts at 1 and increments only on
    emergency IK rotation. No independent rotation cycle.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pm_signed_prekeys",
        db_column="user_id",
    )
    spk_id = models.PositiveIntegerField()  # monotonic, starts at 1
    # Curve25519 IK pub (same as IdentityKey.ik_pub_curve25519 at registration)
    spk_pub = models.CharField(max_length=64)
    # Ed25519 signature over spk_pub (base64url, up to ~88 chars; 128 is safe)
    spk_sig = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "pm_signedprekey"
        verbose_name = "Signed PreKey"
        verbose_name_plural = "Signed PreKeys"

    def __str__(self):
        return f"SignedPreKey(user_id={self.user_id}, spk_id={self.spk_id})"


class OneTimePreKey(models.Model):
    """
    Olm one-time prekeys (OTPKs). Each row is consumed (deleted) atomically
    when a prekey bundle is fetched. Pool cap 150, replenish threshold 20.
    otpk_id is the Olm string key ID (base64url, not an integer).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pm_one_time_prekeys",
        db_column="user_id",
    )
    # Olm string key ID — base64url representation, not a sequential integer.
    otpk_id = models.CharField(max_length=64)
    # Curve25519 one-time prekey public component (base64url)
    otpk_pub = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pm_onetimeprekey"
        verbose_name = "One-Time PreKey"
        verbose_name_plural = "One-Time PreKeys"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "otpk_id"],
                name="pm_onetimeprekey_user_otpk_id_unique",
            )
        ]

    def __str__(self):
        return f"OneTimePreKey(user_id={self.user_id}, otpk_id={self.otpk_id!r})"


class EncryptedEnvelope(models.Model):
    """
    Offline store-and-forward buffer. Rows are deleted on ACK (delete-on-delivery).
    Ciphertext is opaque base64-encoded Olm ciphertext — server never decrypts it.
    expires_at is indexed for periodic cleanup of undelivered envelopes.

    IMPORTANT: Do NOT add fields named content, body, plaintext, or message.
    This model is a dumb pipe; all meaning lives inside ciphertext_b64.
    """

    # UUID PK so envelope IDs are not guessable / enumerable
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pm_sent_envelopes",
        db_column="sender_id",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pm_received_envelopes",
        db_column="recipient_id",
    )
    # Olm ciphertext, base64-encoded. Max 65536 chars per blueprint.
    ciphertext_b64 = models.TextField(
        max_length=65536,
        help_text="Olm ciphertext (base64). Server does not decrypt this field.",
    )
    # 0 = PreKey message (X3DH session setup), 1 = regular ratchet message
    MESSAGE_TYPE_PREKEY = 0
    MESSAGE_TYPE_REGULAR = 1
    MESSAGE_TYPE_CHOICES = [
        (MESSAGE_TYPE_PREKEY, "PreKey"),
        (MESSAGE_TYPE_REGULAR, "Regular"),
    ]
    message_type = models.SmallIntegerField(choices=MESSAGE_TYPE_CHOICES)
    # The OTPK consumed during X3DH (null for regular messages)
    otpk_id_used = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Envelopes expire after 7 days; indexed for efficient cleanup queries.
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "pm_encryptedenvelope"
        verbose_name = "Encrypted Envelope"
        verbose_name_plural = "Encrypted Envelopes"

    def __str__(self):
        return f"EncryptedEnvelope(id={self.pk}, sender_id={self.sender_id})"


class PrivateSession(models.Model):
    """
    Tracks that a private-messaging session exists between two users.
    user_a_id < user_b_id is enforced at the DB level via CheckConstraint
    so that there is always exactly one session row per pair regardless of
    which user initiated.

    NO key material is stored here.
    """

    user_a = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pm_sessions_as_a",
        db_column="user_a_id",
    )
    user_b = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pm_sessions_as_b",
        db_column="user_b_id",
    )
    initiated_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pm_privatesession"
        verbose_name = "Private Session"
        verbose_name_plural = "Private Sessions"
        constraints = [
            models.UniqueConstraint(
                fields=["user_a", "user_b"],
                name="pm_privatesession_user_pair_unique",
            ),
            # Enforce canonical ordering: always store min(uid) as user_a.
            models.CheckConstraint(
                check=models.Q(user_a_id__lt=models.F("user_b_id")),
                name="pm_privatesession_user_a_lt_user_b",
            ),
        ]

    def __str__(self):
        return f"PrivateSession(user_a_id={self.user_a_id}, user_b_id={self.user_b_id})"
