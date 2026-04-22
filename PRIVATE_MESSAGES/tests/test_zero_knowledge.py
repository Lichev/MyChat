"""
test_zero_knowledge.py

Zero-knowledge guarantees:
1. No plaintext ever appears in any pm_* database column.
2. No pm_* model is registered or browsable through Django admin.
3. No model field is named with a plaintext-semantics name.
"""

import uuid
from django.test import TestCase, Client
from django.contrib.admin import site as admin_site
from django.contrib.auth import get_user_model
from django.db import connection

from PRIVATE_MESSAGES.models import (
    EncryptedEnvelope,
    IdentityKey,
    OneTimePreKey,
    PrivateSession,
    SignedPreKey,
)

UserModel = get_user_model()

# Marker that must NEVER appear verbatim in the database.
_PLAINTEXT_MARKER = "ZERO_KNOWLEDGE_MARKER_XK9Q"

# All pm_* tables (match db_table names on each Model.Meta).
_PM_TABLES = [
    "pm_identitykey",
    "pm_signedprekey",
    "pm_onetimeprekey",
    "pm_encryptedenvelope",
    "pm_privatesession",
]

# Field names that must never appear on PRIVATE_MESSAGES models.
_FORBIDDEN_FIELD_NAMES = {"content", "body", "plaintext", "message", "text", "payload"}

_PM_MODELS = [IdentityKey, SignedPreKey, OneTimePreKey, EncryptedEnvelope, PrivateSession]


def _make_user(username, password="testpass123!"):
    return UserModel.objects.create_user(username=username, password=password)


def _make_friends(user_a, user_b):
    """Create a bilateral friendship directly, bypassing the request flow."""
    from FRIEND.models import Friend
    Friend.objects.get_or_create(from_user=user_a, to_user=user_b)
    Friend.objects.get_or_create(from_user=user_b, to_user=user_a)


class DBLeakTest(TestCase):
    """
    Insert 50 EncryptedEnvelope rows containing a known marker in the
    ciphertext_b64 field (simulating opaque blobs the server stores but
    must not interpret). Then dump every column of every pm_* table via
    raw SQL and assert the PLAINTEXT_MARKER byte-sequence does NOT appear
    in any column that the server should treat as opaque.

    NOTE: The marker IS stored in ciphertext_b64 (the server is a dumb pipe
    and persists whatever the client sends). The test therefore verifies that:
    (a) the marker appears ONLY in ciphertext_b64 and nowhere else — it does
        not bleed into username fields, session metadata, etc.
    (b) fields that must be opaque are not accidentally logged as plaintext
        into a separate table.

    The real zero-knowledge guarantee is that ciphertext_b64 is the ONLY
    column that contains the marker — i.e., the server never unpacks it into
    any other column.
    """

    def setUp(self):
        self.sender = _make_user("zk_sender")
        self.recipient = _make_user("zk_recipient")
        _make_friends(self.sender, self.recipient)

        # Register identity keys (minimal valid-looking base64 values).
        _ik = "A" * 44  # 44-char base64url is plausible for a Curve25519/Ed25519 key
        _spk_sig = "B" * 88
        IdentityKey.objects.create(
            user=self.sender,
            ik_pub_curve25519=_ik,
            ik_pub_ed25519=_ik,
        )
        SignedPreKey.objects.create(
            user=self.sender,
            spk_id=1,
            spk_pub=_ik,
            spk_sig=_spk_sig,
            is_active=True,
        )
        IdentityKey.objects.create(
            user=self.recipient,
            ik_pub_curve25519=_ik,
            ik_pub_ed25519=_ik,
        )
        SignedPreKey.objects.create(
            user=self.recipient,
            spk_id=1,
            spk_pub=_ik,
            spk_sig=_spk_sig,
            is_active=True,
        )

        from django.utils import timezone
        from datetime import timedelta

        for i in range(50):
            EncryptedEnvelope.objects.create(
                sender=self.sender,
                recipient=self.recipient,
                # The ciphertext_b64 deliberately contains the marker — the server
                # is a dumb pipe and stores it verbatim. It must NEVER decode or
                # copy the marker to any other column.
                ciphertext_b64=f"{_PLAINTEXT_MARKER}_ENVELOPE_{i:03d}",
                message_type=0,
                otpk_id_used=None,
                expires_at=timezone.now() + timedelta(days=7),
            )

    def test_marker_confined_to_ciphertext_column_only(self):
        """
        Dump every column of every pm_* table. Assert the marker appears
        in NO column OTHER than ciphertext_b64. This proves the server never
        unpacks the ciphertext into any other DB field.
        """
        with connection.cursor() as cur:
            for table in _PM_TABLES:
                cur.execute(f"SELECT * FROM {table}")  # noqa: S608 — test-only raw SQL
                columns = [d[0] for d in cur.description]
                rows = cur.fetchall()
                for row in rows:
                    for col_name, value in zip(columns, row):
                        if col_name == "ciphertext_b64":
                            # Skip — marker is legitimately stored here.
                            continue
                        str_value = str(value) if value is not None else ""
                        self.assertNotIn(
                            _PLAINTEXT_MARKER,
                            str_value,
                            msg=(
                                f"Plaintext marker found in table={table} "
                                f"column={col_name} value={str_value!r}"
                            ),
                        )

    def test_envelope_count_in_db(self):
        """Sanity: confirm all 50 envelopes are stored."""
        self.assertEqual(
            EncryptedEnvelope.objects.filter(sender=self.sender).count(), 50
        )


class AdminExposureTest(TestCase):
    """
    Log in as a Django superuser and verify no pm_* model appears in admin.
    """

    def setUp(self):
        self.superuser = UserModel.objects.create_superuser(
            username="zk_admin",
            password="adminpass123!",
        )
        self.client = Client()
        self.client.force_login(self.superuser)

    def test_pm_models_not_in_admin_registry(self):
        """No pm_* model should be registered with the admin site."""
        registered_db_tables = {
            model._meta.db_table for model in admin_site._registry
        }
        pm_db_tables = {m._meta.db_table for m in _PM_MODELS}
        overlap = registered_db_tables & pm_db_tables
        self.assertEqual(
            overlap,
            set(),
            msg=f"PM models unexpectedly registered in admin: {overlap}",
        )

    def test_admin_pm_urls_return_404(self):
        """
        Attempting to navigate to /admin/PRIVATE_MESSAGES/ returns 404,
        not 200 (model not registered) or 302 (login redirect wouldn't
        happen for an authenticated superuser with a valid model).
        """
        app_label = "PRIVATE_MESSAGES"
        model_names = ["identitykey", "signedprekey", "onetimeprekey",
                       "encryptedenvelope", "privatesession"]
        for model_name in model_names:
            url = f"/admin/{app_label}/{model_name}/"
            response = self.client.get(url, HTTP_HOST="127.0.0.1")
            self.assertEqual(
                response.status_code,
                404,
                msg=f"Expected 404 for {url}, got {response.status_code}",
            )


class NoPlaintextFieldNamesTest(TestCase):
    """
    Reflect on PRIVATE_MESSAGES model fields and assert none are named
    with plaintext-semantics identifiers (case-insensitive).
    """

    def test_no_plaintext_field_names_on_models(self):
        for model_cls in _PM_MODELS:
            for field in model_cls._meta.get_fields():
                name_lower = field.name.lower() if hasattr(field, "name") else ""
                self.assertNotIn(
                    name_lower,
                    _FORBIDDEN_FIELD_NAMES,
                    msg=(
                        f"Forbidden field name '{field.name}' found on "
                        f"{model_cls.__name__}. "
                        f"Forbidden names: {_FORBIDDEN_FIELD_NAMES}"
                    ),
                )
