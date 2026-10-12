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
| GitHub Actions | Core 2026.9.4 and 2026.10.1 passed; HACS validation passed at commit `4208c1a` |
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

**All automated-test Genie API responses are mocked. External network sockets are
disabled during tests. No real Genie account was used by the automated suite, and
no physical door was operated.** These results establish integration behavior and
Home Assistant framework compatibility. The manual diagnostic below is separate.

The repository is temporarily public for HACS installation during device testing.
GitHub Actions checks HACS compatibility and runs the suite on Core 2026.9.4 and
2026.10.1 without account credentials. It does not publish releases or change visibility.

The first live setup attempt reported a generic connection/response error while the
official app worked. A subsequent user-run standalone diagnostic on Windows /
Python 3.12.10 returned HTTP 200 for Cognito authentication and GET /devices. It
discovered one controller with one door. Its controller ID was a string that could
not be converted to an integer by the version 1.0.0 parser. This reproduces the
parser rejection; the response shape passed the version 1.0.1 diagnostic checks.
No credentials, response values, or device identifiers were recorded here.
Home Assistant setup after updating and physical door commands remain unverified.

中文：HA 自动化测试 95 项通过，另有独立调试脚本测试 7 项通过，集成覆盖率 99%。
自动化测试的云端响应均为模拟数据。另一次用户在 Windows 上运行的真实账号诊断，
登录和设备查询均返回 HTTP 200；字符串设备 ID 触发了 1.0.0 的整数转换错误，
1.0.1 已修复。更新后 HA 内添加和实机门控尚待验证，仓库临时公开以便通过 HACS 安装。
