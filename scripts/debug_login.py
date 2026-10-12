#!/usr/bin/env python3
"""Check Genie app login and device discovery with Python's standard library.

Run in a terminal with Python 3.12+. The password is entered without echo.
Only authentication and GET /devices are performed; no door commands are sent.
The report contains types and fixed diagnostic labels, never account/device values.
"""

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import platform
import re
import socket
import ssl
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

# Public app-client parameters from the Apache-2.0 Homebridge implementation.
# Keep these in sync with custom_components/aladdin_connect_cloud/const.py.
AUTH_URL = "https://cognito-idp.us-east-2.amazonaws.com"
API_BASE_URL = "https://api.smartgarage.systems"
AUTH_CLIENT_ID = "27iic8c3bvslqngl3hso83t74b"
AUTH_CLIENT_SECRET = "7bokto0ep96055k42fnrmuth84k7jdcjablestb7j53o8lp63v5"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
KNOWN_AUTH_ERRORS = {
    "NotAuthorizedException",
    "UserNotFoundException",
    "UserNotConfirmedException",
    "PasswordResetRequiredException",
    "TooManyRequestsException",
    "LimitExceededException",
    "InvalidParameterException",
    "UnexpectedLambdaException",
    "UserLambdaValidationException",
    "InvalidLambdaResponseException",
    "InternalErrorException",
}


class NoRedirect(HTTPRedirectHandler):
    """Do not forward an Authorization header or login payload to a redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def type_name(value: Any) -> str:
    """Return a fixed JSON type label without echoing a value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "other"


def field_types(value: dict, fields: tuple[str, ...]) -> dict[str, str]:
    """Report only code-owned field names and types, including missing fields."""
    return {field: type_name(value[field]) if field in value else "missing" for field in fields}


def valid_device_id(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 0
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]*", value) is not None


def summarize_devices(payload: Any) -> dict:
    """Summarize the response shape and fields used by the integration parser."""
    summary: dict = {"response_type": type_name(payload), "parser_problem_fields": []}
    problems: set[str] = set()
    if not isinstance(payload, dict) or not isinstance(payload.get("devices"), list):
        summary["parser_problem_fields"] = ["devices"]
        if isinstance(payload, dict):
            summary["top_level_fields"] = field_types(payload, ("devices", "data", "error"))
        return summary
    devices = payload["devices"]
    summary["device_count"] = len(devices)
    samples = []
    identities = set()
    for device in devices:
        item: dict = {"type": type_name(device)}
        if not isinstance(device, dict):
            problems.add("device")
        else:
            item["fields"] = field_types(device, ("id", "doors", "ownership", "is_enabled"))
            device_id = device.get("id")
            item["id_valid_in_1_0_1"] = valid_device_id(device_id)
            try:
                int(device_id)
                item["id_convertible_in_1_0_0"] = True
            except (TypeError, ValueError, OverflowError):
                item["id_convertible_in_1_0_0"] = False
            if not item["id_valid_in_1_0_1"]:
                problems.add("device.id")
            doors = device.get("doors")
            if not isinstance(doors, list):
                problems.add("device.doors")
            else:
                item["door_count"] = len(doors)
                door_samples = []
                for door in doors:
                    sample = {"type": type_name(door)}
                    if not isinstance(door, dict):
                        problems.add("door")
                    else:
                        sample["fields"] = field_types(
                            door, ("id", "door_index", "status", "battery_level", "link_status")
                        )
                        if "id" not in door or door["id"] is None or not str(door["id"]):
                            problems.add("door.id")
                        try:
                            index = int(door["door_index"])
                            if index < 0:
                                raise ValueError
                            if item["id_valid_in_1_0_1"]:
                                identity = f"{device_id}:{index}"
                                if identity in identities:
                                    problems.add("door.identity")
                                identities.add(identity)
                        except (KeyError, TypeError, ValueError, OverflowError):
                            problems.add("door.door_index")
                        try:
                            int(door.get("status") or 0)
                        except ValueError:
                            pass  # The integration maps unfamiliar status strings to UNKNOWN.
                        except (TypeError, OverflowError):
                            problems.add("door.status")
                        for field in ("battery_level", "link_status"):
                            try:
                                if door.get(field) is not None:
                                    int(door[field])
                            except (TypeError, ValueError, OverflowError):
                                problems.add(f"door.{field}")
                    if len(door_samples) < 3:
                        door_samples.append(sample)
                item["sample_doors"] = door_samples
        if len(samples) < 3:
            samples.append(item)
    summary["sample_devices"] = samples
    summary["parser_problem_fields"] = sorted(problems)
    return summary


def transport_reason(error: BaseException) -> str:
    """Never return the original exception text, URL, or response body."""
    if isinstance(error, ssl.SSLError):
        return "tls"
    if isinstance(error, socket.gaierror):
        return "dns"
    if isinstance(error, TimeoutError):
        return "timeout"
    return "connection"


def request_json(opener, method: str, url: str, stage: str, timeout: float, **kwargs) -> tuple:
    """Perform one bounded HTTPS request and return safe diagnostics separately."""
    started = time.monotonic()
    detail: dict = {"stage": stage}
    try:
        try:
            response = opener.open(Request(url, method=method, **kwargs), timeout=timeout)
        except HTTPError as error:
            response = error
        with response:
            detail["http_status"] = response.code
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        detail["elapsed_seconds"] = round(time.monotonic() - started, 2)
        if len(raw) > MAX_RESPONSE_BYTES:
            detail["reason"] = "response_too_large"
            return detail, None
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            detail["reason"] = "http" if response.code >= 300 else "invalid_json"
            return detail, None
        if not 200 <= response.code < 300:
            detail["reason"] = "http"
            if stage == "authentication" and isinstance(payload, dict):
                error_code = payload.get("__type")
                if isinstance(error_code, str):
                    # AWS may prefix a code with its fixed namespace.
                    error_code = error_code.rsplit("#", 1)[-1]
                    if error_code in KNOWN_AUTH_ERRORS:
                        detail["aws_error"] = error_code
            return detail, None
        detail["reason"] = "ok"
        return detail, payload
    except URLError as error:
        detail["reason"] = transport_reason(error.reason)
    except (OSError, TimeoutError) as error:
        detail["reason"] = transport_reason(error)
    detail["elapsed_seconds"] = round(time.monotonic() - started, 2)
    return detail, None


def diagnose(username: str, password: str, timeout: float = 10, *, opener=None) -> dict:
    """Return a shareable report; credentials and response values stay in memory."""
    if opener is None:
        opener = build_opener(NoRedirect())
    report: dict = {
        "report_version": 1,
        "python": platform.python_version(),
        "platform": platform.system(),
        "requests": [],
    }
    secret_hash = base64.b64encode(
        hmac.new(
            AUTH_CLIENT_SECRET.encode(),
            (username + AUTH_CLIENT_ID).encode(),
            hashlib.sha256,
        ).digest()
    ).decode()
    auth, payload = request_json(
        opener,
        "POST",
        AUTH_URL,
        "authentication",
        timeout,
        headers={
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
        },
        data=json.dumps(
            {
                "ClientId": AUTH_CLIENT_ID,
                "AuthFlow": "USER_PASSWORD_AUTH",
                "AuthParameters": {
                    "USERNAME": username,
                    "PASSWORD": password,
                    "SECRET_HASH": secret_hash,
                },
            }
        ).encode(),
    )
    report["requests"].append(auth)
    if auth["reason"] != "ok":
        report["result"] = "authentication_request_failed"
        return report
    if not isinstance(payload, dict):
        auth["reason"] = "invalid_response"
        auth["response_type"] = type_name(payload)
        report["result"] = "authentication_response_invalid"
        return report
    if payload.get("ChallengeName"):
        auth["reason"] = "challenge"
        report["result"] = "additional_sign_in_step_required"
        return report
    result = payload.get("AuthenticationResult")
    token = result.get("AccessToken") if isinstance(result, dict) else None
    auth["authentication_result_type"] = type_name(result)
    if isinstance(result, dict):
        auth["fields"] = field_types(result, ("AccessToken", "ExpiresIn"))
    try:
        lifetime = float(result["ExpiresIn"])
        lifetime_valid = 0 < lifetime < float("inf")
    except (KeyError, TypeError, ValueError, OverflowError):
        lifetime_valid = False
    if not isinstance(token, str) or not token or not lifetime_valid:
        auth["reason"] = "invalid_response"
        report["result"] = "authentication_response_invalid"
        return report
    devices, payload = request_json(
        opener,
        "GET",
        f"{API_BASE_URL}/devices",
        "devices",
        timeout,
        headers={"Authorization": f"Bearer {token}"},
    )
    report["requests"].append(devices)
    if devices["reason"] != "ok":
        report["result"] = "device_request_failed"
        return report
    devices["schema"] = summarize_devices(payload)
    if devices["schema"]["parser_problem_fields"]:
        devices["reason"] = "invalid_response"
        report["result"] = "device_response_invalid"
    elif not devices["schema"]["device_count"]:
        report["result"] = "no_devices"
    elif not any(isinstance(d, dict) and d.get("doors") for d in payload["devices"]):
        report["result"] = "no_doors"
    else:
        report["result"] = "login_and_device_query_succeeded"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=Path("aladdin-debug-report.json"))
    parser.add_argument(
        "--timeout", type=float, default=10, help="Request timeout in seconds (1-120)"
    )
    args = parser.parse_args()
    if not 1 <= args.timeout <= 120:
        parser.error("--timeout must be between 1 and 120 seconds")
    if not sys.stdin.isatty():
        print("Run this script in an interactive terminal. Credentials are not accepted by pipe.")
        return 2
    print("Genie login + device query only. No door commands. Password input is hidden.")
    print("Genie 登录和设备查询，不发送门控指令。密码输入不会显示。")
    try:
        username = input("Aladdin Connect email / 邮箱: ").strip()
        password = getpass.getpass("Password / 密码: ")
        if not username or not password:
            print("Email and password are required / 邮箱和密码不能为空。")
            return 2
        report = diagnose(username, password, args.timeout)
        text = json.dumps(report, indent=2, ensure_ascii=False)
        print(text)
        try:
            args.report.write_text(text + "\n", encoding="utf-8")
            print(f"Safe report saved / 脱敏报告已保存: {args.report.resolve()}")
        except OSError:
            print("Unable to write report; copy the JSON above / 报告保存失败，请复制上方 JSON。")
        print("Share the report, never your password or token / 可提供报告，不要提供密码或 token。")
        return 0 if report["result"] == "login_and_device_query_succeeded" else 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled / 已取消。")
        return 130


if __name__ == "__main__":
    sys.exit(main())
