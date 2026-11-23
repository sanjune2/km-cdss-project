import os
import smtplib
import unittest
from unittest.mock import patch

from invitation_email import invitation_link, send_staff_invitation


class StaffInvitationEmailTests(unittest.TestCase):
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
        with patch.dict(os.environ, settings, clear=True), patch("invitation_email.smtplib.SMTP") as smtp:
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
