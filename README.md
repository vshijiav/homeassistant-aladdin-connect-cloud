# Aladdin Connect Cloud for Home Assistant

[English](README.md) | [简体中文](README.zh-CN.md)

A Home Assistant custom integration for Genie Aladdin Connect garage doors, ported from [homebridge-plugins/homebridge-aladdin-connect](https://github.com/homebridge-plugins/homebridge-aladdin-connect).

**Cloud control with direct Aladdin Connect account sign-in. No Home Assistant Cloud / Nabu Casa subscription is required by this integration.** An internet connection and access to the Genie cloud service are required; this integration does not implement local/LAN or offline control.

**Status: testing preview.** The repository is temporarily public so it can be installed through HACS. Authentication and commands have not yet been verified with a real Genie account and garage door. There is no automatic visibility change or release workflow.

## Features

- Configure your account through the Home Assistant UI, with English and Simplified Chinese translations.
- Open and close garage doors using standard Home Assistant cover actions.
- Report open, closed, opening, closing, unknown, and unavailable states.
- Expose door fault, battery level, and low-battery entities where supported.
- Configure polling, shared-door visibility, ignored doors, and the battery threshold.
- Add newly discovered doors and battery entities without restarting Home Assistant.
- Support password updates, reauthentication, and recovery after temporary connection failures.

The integration domain is `aladdin_connect_cloud`, and its UI name is **Aladdin Connect Cloud**. It uses a separate domain from Home Assistant's built-in `aladdin_connect` integration. Configure one integration to control each physical door to avoid duplicate commands.

## Installation

Home Assistant **2026.9.4 or later** is required by the HACS manifest. CI checks Core **2026.9.4** and **2026.10.1**. No additional Python libraries need to be installed inside Home Assistant.

### HACS custom repository

With HACS already configured in Home Assistant:

1. Open **HACS** in the sidebar, select the top-right **⋮** menu, then **Custom repositories**.
2. Enter `https://github.com/vshijiav/homeassistant-aladdin-connect-cloud`.
3. Select **Integration** as the repository type, then choose **Add**.
4. Open **Aladdin Connect Cloud** in HACS and select **Download**. Use the default branch, `main`, while no release has been published.
5. Restart Home Assistant completely.
6. Open **Settings → Devices & services → Add integration**, search for **Aladdin Connect Cloud**, and enter your Genie app account email and password.

This is a HACS custom integration repository, not a Supervisor app/add-on repository. Adding its URL under **Settings → Apps → Repositories** will not install it. It is not included in HACS's default catalog, so the custom-repository step is required. See [HACS custom-repository instructions](https://www.hacs.xyz/docs/faq/custom_repositories/).

### Manual installation

1. Download the repository ZIP from **Code → Download ZIP**, or clone the repository.
2. Copy the entire `custom_components/aladdin_connect_cloud` folder into the `custom_components` folder in your Home Assistant configuration directory.
3. Restart Home Assistant.
4. Open **Settings → Devices & services → Add integration**, then search for **Aladdin Connect Cloud**.
5. Enter the email address and password used in the Genie Aladdin Connect app. The integration validates account sign-in and the device list before creating the entry.

On Home Assistant OS, the expected layout is:

```text
/config/
├── configuration.yaml
└── custom_components/
    └── aladdin_connect_cloud/
        ├── __init__.py
        ├── api.py
        ├── config_flow.py
        ├── manifest.json
        └── ...
```

For other installation methods, use the directory containing your actual `configuration.yaml`. Do not add an extra repository-name folder between `custom_components` and `aladdin_connect_cloud`.

No YAML integration configuration or Homebridge installation is needed. Both HACS custom-repository installation and manual installation are supported.

## Entities

Each logical door is represented as a Home Assistant device. The stable identity is the cloud controller's `deviceId:doorIndex`; a controller with several doors creates a separate device for each door.

| Entity | Purpose |
| --- | --- |
| Garage `cover` | Open and close a door; report its current state |
| Door fault `binary_sensor` | Report the cloud API's fault flag or an opening/closing timeout |
| Battery `sensor` | Report battery percentage when the model provides a usable reading |
| Low battery `binary_sensor` | Compare the battery reading with the configured threshold |

Only open and close commands are available. Stop and percentage/position control are not supported by the upstream API implementation.

Unknown, unconfigured, and timed-out door states are reported as `unknown`, rather than being guessed as closed. The fault entity describes a cloud-reported fault or timeout; it is not an independent physical obstruction sensor.

Battery behavior follows the upstream implementation: a non-zero `battery_level` creates battery entities, and the reading is usable only when `link_status == 3`. The API uses zero for models without batteries, so zero cannot reliably be distinguished from a depleted battery. Existing battery entities report `unknown` when the reading becomes zero or the battery sensor disconnects. Battery entities are added later if a usable reading first appears after setup.

Home Assistant generates entity IDs from device names, for example `cover.main_garage`. Check the device page for your actual entity IDs.

## Options and updates

Open the integration's configuration options. Saving options reloads the entry automatically.

| Option | Default | Behavior |
| --- | --- | --- |
| Polling interval | 15 seconds | Adjustable from 5 to 60 seconds; all doors share one device-list query |
| Show shared doors | Off | Include doors shared with the account; Genie determines control permissions |
| Ignore doors | None | Select doors or enter cloud `door.id` values such as `F0AD4E1BC74D_1` |
| Low-battery threshold | 15% | Adjustable from 0 to 100%; readings at or below the threshold trigger low battery |

After a successful command, the integration requests an immediate refresh and polls every 5 seconds while awaiting the target state, for up to 90 seconds. It also uses a 5-second interval while the cloud reports a door moving. Once the door settles, normal polling resumes. An accepted HTTP command does not by itself change the reported door position.

New doors are added during subsequent polls. Entities become `unavailable` if their door disappears from the account, is disabled, or the cloud cannot be queried. They recover after a successful query. There are no push updates; reported states depend on Genie cloud latency and the polling interval.

## Actions

Use standard Home Assistant cover actions, replacing the example entity ID:

```yaml
action: cover.open_cover
target:
  entity_id: cover.main_garage
```

```yaml
action: cover.close_cover
target:
  entity_id: cover.main_garage
```

You can expose these covers to Apple Home through Home Assistant's HomeKit Bridge integration. Device control still uses the Genie cloud.

## Authentication and errors

The client signs in directly to AWS Cognito using `USER_PASSWORD_AUTH`, then calls `api.smartgarage.systems`. Access tokens stay in memory, expire 30 seconds before their reported lifetime, and are obtained again using the account password when needed. This follows the Homebridge implementation's authentication path.

- A read-only device query rejected with HTTP 401 gets a new token and retries once. Persistent rejection starts Home Assistant reauthentication.
- Door command POST requests are sent once. Timeouts, connection failures, HTTP 5xx, HTTP 401, and permission failures do not automatically replay a physical command. A timeout can mean the command arrived but its response was lost; check the door before trying again.
- Temporary startup failures use Home Assistant's setup retry mechanism. Failed queries during operation mark entities unavailable.
- Use **Reconfigure** to update the password for the existing account. Add a separate integration entry to use a different account.
- Cognito MFA, password-change requirements, and other extra authentication challenges are not completed automatically. Complete applicable steps in the official app; accounts that continuously require an MFA challenge are not supported.
- Home Assistant stores the username and password in its config entry. Protect the configuration directory and backups as you would other credentials. The integration does not log passwords, tokens, or full API responses.

## Relationship to the official integration

Home Assistant's [built-in Aladdin Connect integration](https://www.home-assistant.io/integrations/aladdin_connect/) uses the manufacturer's partner SDK and OAuth authentication path. This project ports the Homebridge app API path instead and has no Nabu Casa dependency. It is an independent custom integration, not an official Genie or Home Assistant product.

App API behavior and embedded Cognito client parameters may change with manufacturer updates. Automated tests do not establish that every account can still authenticate to the live service.

Protocol behavior is derived from upstream package **4.3.4**, commit [`2fe528a525ffacf5d435569d50a7cf2e4daa87f8`](https://github.com/homebridge-plugins/homebridge-aladdin-connect/tree/2fe528a525ffacf5d435569d50a7cf2e4daa87f8). See [NOTICE](NOTICE) for attribution and changes. Report issues with this port in [this repository](https://github.com/vshijiav/homeassistant-aladdin-connect-cloud/issues), rather than to the upstream Homebridge maintainers.

## Development and testing

Use Linux with Python **3.14.2 or later** for the pinned Home Assistant test environment:

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m pytest --cov --cov-report=term-missing
```

The test suite uses real Home Assistant Core and its custom-integration test framework. All Genie HTTP requests are mocked, and external network sockets are disabled. The previously recorded Core 2026.10.1 result is **65 passing tests and 98% statement coverage**. To reproduce the Core 2026.9.4 environment, use `requirements-dev-ha2026.9.txt` instead. See [VALIDATION.md](VALIDATION.md) and [GitHub Actions](https://github.com/vshijiav/homeassistant-aladdin-connect-cloud/actions) for validation results.

GitHub Actions runs HACS validation, lint, format checks, and the same automated suite on Core 2026.9.4 and 2026.10.1. CI does not access a Genie account, operate a garage door, change repository visibility, or publish releases.

Before treating the testing preview as a verified device integration, check it in a real Home Assistant installation:

- [ ] Account sign-in and device discovery.
- [ ] Open/close commands and the full moving-to-settled state sequence.
- [ ] Connection failure and recovery.
- [ ] Password update and reauthentication.
- [ ] Battery readings, if the installed model reports them.
- [ ] Shared-door permissions, if shared doors are used.

Record results without passwords, tokens, account email addresses, or raw account/device responses. Real-device testing remains pending.

## License

[Apache License 2.0](LICENSE), with the upstream license and attribution retained.
