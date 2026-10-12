"""Test the standalone diagnostic with no HA or third-party dependencies."""

import io
import json
import socket
import ssl
import unittest
from urllib.error import HTTPError, URLError

from scripts import debug_login as debug


class Response(io.BytesIO):
    """A urllib response containing only fake account data."""

    def __init__(self, data, code=200):
        super().__init__(json.dumps(data).encode())
        self.code = code


class Opener:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class DebugLoginTests(unittest.TestCase):
    def auth(self):
        return Response(
            {"AuthenticationResult": {"AccessToken": "private-token", "ExpiresIn": 3600}}
        )

    def test_success_uses_app_contract_and_only_reports_types(self):
        opener = Opener(
            self.auth(),
            Response(
                {
                    "devices": [
                        {
                            "id": "F0AD4E1BC74D",
                            "name": "private-name",
                            "doors": [{"id": "private-id", "door_index": 1, "status": 4}],
                        }
                    ]
                }
            ),
        )
        report = debug.diagnose("private@example.com", "private-password", opener=opener)
        self.assertEqual(report["result"], "login_and_device_query_succeeded")
        self.assertEqual(len(opener.calls), 2)
        auth = opener.calls[0][0]
        payload = json.loads(auth.data)
        self.assertEqual(auth.full_url, debug.AUTH_URL)
        self.assertEqual(payload["AuthFlow"], "USER_PASSWORD_AUTH")
        self.assertEqual(payload["AuthParameters"]["USERNAME"], "private@example.com")
        self.assertEqual(payload["AuthParameters"]["PASSWORD"], "private-password")
        self.assertTrue(payload["AuthParameters"]["SECRET_HASH"])
        read = opener.calls[1][0]
        self.assertEqual(read.method, "GET")
        self.assertEqual(read.full_url, f"{debug.API_BASE_URL}/devices")
        self.assertEqual(read.get_header("Authorization"), "Bearer private-token")
        self.assertNotIn("private", json.dumps(report))
        self.assertNotIn("F0AD4E1BC74D", json.dumps(report))
        item = report["requests"][1]["schema"]["sample_devices"][0]
        self.assertEqual(item["fields"]["id"], "string")
        self.assertTrue(item["id_valid_in_1_0_1"])
        self.assertFalse(item["id_convertible_in_1_0_0"])

    def test_auth_failure_records_aws_code_without_error_message(self):
        response = io.BytesIO(
            json.dumps({"__type": "NotAuthorizedException", "message": "private-password"}).encode()
        )
        opener = Opener(HTTPError(debug.AUTH_URL, 400, "private-text", {}, response))
        report = debug.diagnose("private@example.com", "private-password", opener=opener)
        self.assertEqual(report["result"], "authentication_request_failed")
        self.assertEqual(report["requests"][0]["aws_error"], "NotAuthorizedException")
        self.assertNotIn("private", json.dumps(report))
        self.assertEqual(len(opener.calls), 1)

    def test_malformed_device_fields_are_identified_without_values(self):
        cases = [
            ({"private-device": "private-password"}, ["devices"]),
            ({"devices": [{"id": "private@example.com", "doors": []}]}, ["device.id"]),
            (
                {"devices": [{"id": 1, "doors": [{"id": "private-id"}]}]},
                ["door.door_index"],
            ),
        ]
        for payload, fields in cases:
            with self.subTest(fields=fields):
                opener = Opener(self.auth(), Response(payload))
                report = debug.diagnose("owner", "password", opener=opener)
                self.assertEqual(report["result"], "device_response_invalid")
                self.assertEqual(report["requests"][1]["schema"]["parser_problem_fields"], fields)
                self.assertNotIn("private", json.dumps(report))

    def test_transport_errors_are_safe(self):
        for error, reason in (
            (socket.gaierror("private-host"), "dns"),
            (ssl.SSLError("private-host"), "tls"),
            (TimeoutError("private-password"), "timeout"),
            (OSError("private-url"), "connection"),
        ):
            with self.subTest(reason=reason):
                report = debug.diagnose("owner", "password", opener=Opener(URLError(error)))
                self.assertEqual(report["requests"][0]["reason"], reason)
                self.assertNotIn("private", json.dumps(report))

    def test_challenge_stops_before_device_query(self):
        opener = Opener(Response({"ChallengeName": "private-challenge"}))
        report = debug.diagnose("owner", "password", opener=opener)
        self.assertEqual(report["result"], "additional_sign_in_step_required")
        self.assertEqual(len(opener.calls), 1)
        self.assertNotIn("private", json.dumps(report))

    def test_redirect_is_never_followed(self):
        handler = debug.NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "", {}, "https://example.com"))

    def test_device_denial_stops_without_replaying_requests(self):
        opener = Opener(self.auth(), HTTPError(debug.API_BASE_URL, 401, "", {}, io.BytesIO(b"{}")))
        report = debug.diagnose("owner", "password", opener=opener)
        self.assertEqual(report["result"], "device_request_failed")
        self.assertEqual(report["requests"][1]["http_status"], 401)
        self.assertEqual(len(opener.calls), 2)


if __name__ == "__main__":
    unittest.main()
