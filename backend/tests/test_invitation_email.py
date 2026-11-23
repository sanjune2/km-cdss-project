import os
import smtplib
import ssl
import unittest
from unittest.mock import patch

from invitation_email import invitation_link, send_staff_invitation


class StaffInvitationEmailTests(unittest.TestCase):
    def setUp(self):
        # Load the OS certificate store before tests clear the process environment.
        self.tls = ssl.create_default_context()

    def test_ssl_uses_verified_tls_and_reports_recipient_refusal(self):
        settings = {
            "HANUI_PUBLIC_URL": "http://localhost:5173/",
            "HANUI_SMTP_HOST": "smtp.example.test",
            "HANUI_SMTP_SECURITY": "ssl",
            "HANUI_SMTP_FROM": "invite@example.test",
            "HANUI_SMTP_USER": "invite@example.test",
            "HANUI_SMTP_PASSWORD": "test-only",
        }
        with patch.dict(os.environ, settings, clear=True), patch("invitation_email.ssl.create_default_context", return_value=self.tls), patch("invitation_email.smtplib.SMTP_SSL") as smtp:
            smtp.return_value.send_message.return_value = {}
            link = invitation_link("test-token")
            self.assertEqual(send_staff_invitation("staff@example.test", link), "sent")
            self.assertEqual(smtp.call_args.args, ("smtp.example.test", 465))
            self.assertTrue(smtp.call_args.kwargs["context"].check_hostname)
            smtp.return_value.starttls.assert_not_called()
            smtp.return_value.send_message.return_value = {"staff@example.test": (550, b"rejected")}
            self.assertEqual(send_staff_invitation("staff@example.test", link), "failed")

    def test_invalid_public_url_never_connects_to_smtp(self):
        for value in ("", "javascript:alert(1)", "https://user:pass@example.test", "https://example.test/path"):
            with self.subTest(value=value), patch.dict(os.environ, {
                "HANUI_PUBLIC_URL": value, "HANUI_SMTP_HOST": "smtp.example.test",
                "HANUI_SMTP_FROM": "invite@example.test",
            }, clear=True), patch("invitation_email.smtplib.SMTP") as smtp:
                self.assertIsNone(invitation_link("test-token"))
                self.assertEqual(send_staff_invitation("staff@example.test", None), "failed")
                smtp.assert_not_called()

    def test_disabled_and_incomplete_settings(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(invitation_link("token"))
            self.assertEqual(send_staff_invitation("staff@example.test", None), "not_configured")
        with patch.dict(os.environ, {"HANUI_SMTP_HOST": "smtp.example.test"}, clear=True):
            self.assertEqual(send_staff_invitation("staff@example.test", None), "failed")

    def test_sends_public_link_and_preserves_fallback_on_refusal(self):
        settings = {
            "HANUI_PUBLIC_URL": "https://hanui.example.test/",
            "HANUI_SMTP_HOST": "smtp.example.test",
            "HANUI_SMTP_FROM": "invite@example.test",
            "HANUI_SMTP_USER": "invite@example.test",
            "HANUI_SMTP_PASSWORD": "test-only",
        }
        recipient = "staff@example.test"
        with patch.dict(os.environ, settings, clear=True), patch("invitation_email.ssl.create_default_context", return_value=self.tls), patch("invitation_email.smtplib.SMTP") as smtp:
            link = invitation_link("token+test")
            self.assertEqual(link, "https://hanui.example.test/staff/register?token=token%2Btest")
            client = smtp.return_value
            client.send_message.return_value = {}
            self.assertEqual(send_staff_invitation(recipient, link), "sent")
            client.starttls.assert_called_once()
            client.login.assert_called_once_with(settings["HANUI_SMTP_USER"], settings["HANUI_SMTP_PASSWORD"])
            message = client.send_message.call_args.args[0]
            self.assertEqual(str(message["To"]), recipient)
            self.assertIn(link, message.get_content())
            client.send_message.side_effect = smtplib.SMTPException
            self.assertEqual(send_staff_invitation(recipient, link), "failed")
