# Validation

Recorded on 2026-10-12.

| Check | Result |
| --- | --- |
| Home Assistant Core | 2026.10.1; real Core modules and custom integration loader |
| Python / platform | 3.14.4 / Linux, WSL Ubuntu 24.04 |
| Test framework | pytest-homeassistant-custom-component 0.13.372 |
| Integration version | 1.0.1 |
| Home Assistant automated tests | **95 passed** |
| Standalone diagnostic tests | **7 passed**; Python 3.12.10 / Windows, standard library only |
| Integration statement coverage | **99%**; 505 statements, 7 not covered |
| Ruff lint / format checks | Passed |
| Python syntax parsing | Passed |
| Translation keys, installation layout, ZIP integrity | Checked by the local packaging script |

The suite checks Cognito requests and HMAC parameters, concurrent token caching,
token expiry and HTTP 401 recovery, door commands without automatic replay,
configuration and duplicate-account detection, password changes and reauthentication,
shared and ignored doors, actual HA cover service calls, all door status mappings,
fault and battery entities, dynamic discovery, connection recovery, and unloading.
Additional checks cover string controller IDs, authentication/device failure stages,
DNS/TLS/timeout classification, config-flow diagnostic placeholders, and safe logging.
The standalone script tests check login and read-only query requests, response-shape
diagnostics, credential/value omission, transport failures, and redirect rejection.

**All Genie API responses are mocked. External network sockets are disabled during
tests. No real Genie account was used, and no physical door was operated.** These
results establish integration behavior and Home Assistant framework compatibility;
live authentication and physical-device testing remain pending.

The repository is temporarily public for HACS installation during device testing.
GitHub Actions checks HACS compatibility and runs the suite on Core 2026.9.4 and
2026.10.1 without account credentials. It does not publish releases or change visibility.

The first live setup attempt reported a generic connection/response error while the
official app worked. Its cause has not yet been confirmed. Version 1.0.1 corrects a
string-ID parsing incompatibility and supplies safe setup and standalone diagnostics.

中文：HA 自动化测试 95 项通过，另有独立调试脚本测试 7 项通过，集成覆盖率 99%。
所有云端响应均为模拟数据。首次实机添加失败原因仍待诊断，实机门控尚未验证；
仓库临时公开以便通过 HACS 安装。
