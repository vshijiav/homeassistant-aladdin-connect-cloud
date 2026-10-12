# Validation

Recorded on 2026-10-12.

| Check | Result |
| --- | --- |
| Home Assistant Core | 2026.10.1; real Core modules and custom integration loader |
| Python / platform | 3.14.4 / Linux, WSL Ubuntu 24.04 |
| Test framework | pytest-homeassistant-custom-component 0.13.372 |
| Automated tests | **65 passed** |
| Integration statement coverage | **98%**; 441 statements, 7 not covered |
| Ruff lint / format checks | Passed |
| Python syntax parsing | Passed |
| Translation keys, installation layout, ZIP integrity | Checked by the local packaging script |

The suite checks Cognito requests and HMAC parameters, concurrent token caching,
token expiry and HTTP 401 recovery, door commands without automatic replay,
configuration and duplicate-account detection, password changes and reauthentication,
shared and ignored doors, actual HA cover service calls, all door status mappings,
fault and battery entities, dynamic discovery, connection recovery, and unloading.

**All Genie API responses are mocked. External network sockets are disabled during
tests. No real Genie account was used, and no physical door was operated.** These
results establish integration behavior and Home Assistant framework compatibility;
live authentication and physical-device testing remain pending.

The repository is kept private during device testing. GitHub Actions runs checks
without account credentials and does not publish releases or change visibility.

中文：自动化测试 65 项通过，覆盖率 98%；所有云端响应均为模拟数据。
真实账号登录和实机门控仍待验证，实机测试期间仓库保持私有。
