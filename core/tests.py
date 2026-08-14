from django.test import TestCase

# Create your tests here.
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Participant

User = get_user_model()


class CustomUserManagerTests(TestCase):
    """Sanity checks for the email-based custom user manager."""

    def test_create_user_requires_email(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email=None, password="a-strong-password-0")

    def test_create_user_normalizes_email_and_sets_password(self):
        user = User.objects.create_user(email="Test@Example.com", password="a-strong-password-1")
        self.assertEqual(user.email, "Test@example.com")  # domain is lowercased
        self.assertTrue(user.check_password("a-strong-password-1"))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_superuser_sets_staff_and_superuser_flags(self):
        admin = User.objects.create_superuser(email="admin@example.com", password="a-strong-password-2")
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_create_superuser_rejects_is_staff_false(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser(
                email="bad-admin@example.com", password="a-strong-password-3", is_staff=False
            )


class EncryptedFieldRoundTripTests(TestCase):
    """The test that matters most: if FIELD_ENCRYPTION_KEYS or the
    encrypt/decrypt path ever breaks, this fails loudly here instead of
    silently corrupting participant data in production.
    """

    def test_backup_email_round_trips_through_the_database(self):
        user = User.objects.create_user(
            email="participant@example.com",
            password="a-strong-password-4",
            backup_email="secondary@example.com",
        )
        reloaded = User.objects.get(pk=user.pk)  # fresh fetch forces decryption
        self.assertEqual(reloaded.backup_email, "secondary@example.com")

    def test_participant_google_tokens_round_trip_through_the_database(self):
        user = User.objects.create_user(email="p2@example.com", password="a-strong-password-5")
        participant = Participant.objects.create(
            user=user,
            start_date=date(2026, 1, 1),
            treatment_arm=0,
            google_access_token="fake-access-token-value",
            google_refresh_token="fake-refresh-token-value",
        )
        reloaded = Participant.objects.get(pk=participant.pk)
        self.assertEqual(reloaded.google_access_token, "fake-access-token-value")
        self.assertEqual(reloaded.google_refresh_token, "fake-refresh-token-value")


class AdminAccessControlTests(TestCase):
    """Confirms staff-only views actually turn away anonymous visitors,
    and that logged-in staff can load them without error."""

    def setUp(self):
        self.staff_user = User.objects.create_user(
            email="staff@example.com", password="a-strong-password-6", is_staff=True
        )
        participant_user = User.objects.create_user(
            email="participant-x@example.com", password="a-strong-password-7"
        )
        self.participant = Participant.objects.create(
            user=participant_user, start_date=date(2026, 1, 1), treatment_arm=0
        )

    def test_anonymous_user_is_redirected_not_let_in(self):
        for url in [
            reverse("admin-dashboard"),
            reverse("participant_detail", args=[self.participant.pk]),
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/admin/login/", response.url)

    def test_staff_user_can_load_dashboard(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("admin-dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_staff_user_can_load_participant_detail(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("participant_detail", args=[self.participant.pk]))
        self.assertEqual(response.status_code, 200)


class SecurityHeadersTests(TestCase):
    """Confirms core.middleware.SecurityHeadersMiddleware is still wired up."""

    def test_response_carries_hardening_headers(self):
        response = self.client.get(reverse("admin:login"))
        self.assertEqual(response.get("Cross-Origin-Resource-Policy"), "same-origin")
        self.assertEqual(response.get("Cross-Origin-Embedder-Policy"), "require-corp")
        self.assertIn("geolocation=()", response.get("Permissions-Policy", ""))