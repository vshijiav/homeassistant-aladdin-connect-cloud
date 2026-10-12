# Aladdin Connect Cloud — Home Assistant 自定义集成

[English](README.md) | [简体中文](README.zh-CN.md)

**当前阶段：测试预览。** 仓库临时公开，便于通过 HACS 自定义仓库安装。真实 Genie 账号登录和实机门控尚未验证，没有自动改变可见性或发布流程。英文 README 是主文档。

将 [homebridge-plugins/homebridge-aladdin-connect](https://github.com/homebridge-plugins/homebridge-aladdin-connect) 的云端协议改写为 Python / Home Assistant 集成。原始实现版本为 4.3.4，源码提交 `2fe528a525ffacf5d435569d50a7cf2e4daa87f8`。

**这是云端集成，需要互联网，不提供车库门局域网直连或离线控制。** 它直接使用 Genie App 的账号密码登录 AWS Cognito，然后调用 `api.smartgarage.systems`。本集成没有 Home Assistant Cloud / Nabu Casa 依赖。

它使用独立域名 `aladdin_connect_cloud`，界面名称为 **Aladdin Connect Cloud**，不会替换 Home Assistant 自带的 `aladdin_connect`。不要同时为同一扇门配置两个集成来发送重复操作。

## 安装

HACS 安装要求 Home Assistant **2026.9.4 或更新版本**。CI 检查 Core **2026.9.4** 和 **2026.10.1**，无需在 Home Assistant 中额外安装 Python 库。

### 通过 HACS 自定义仓库安装

在 HA 中已配置好 HACS 的情况下：

1. 打开侧栏 **HACS → 右上角 ⋮ → 自定义仓库（Custom repositories）**。
2. 输入地址：`https://github.com/vshijiav/homeassistant-aladdin-connect-cloud`。
3. 类型选择 **Integration / 集成**，点击 **Add / 添加**。
4. 在 HACS 中打开 **Aladdin Connect Cloud**，点击 **Download / 下载**；尚无发布版本时使用默认分支 `main`。
5. 完整重启 Home Assistant。
6. 前往 **设置 → 设备与服务 → 添加集成**，搜索 **Aladdin Connect Cloud**，填写 Genie App 的邮箱和密码。

地址应添加到 **HACS 的自定义仓库**，不是 **设置 → 应用/加载项 → 仓库**。项目尚未加入 HACS 默认目录，需要手动添加仓库地址。[HACS 官方说明](https://www.hacs.xyz/docs/faq/custom_repositories/)

### 手动安装

1. 在仓库页面使用 **Code → Download ZIP** 下载并解压，或克隆仓库。
2. 将包中的 `custom_components/aladdin_connect_cloud` 整个文件夹复制到 Home Assistant 配置目录的 `custom_components` 下。HA OS 的配置目录通常为 `/config`；其他安装方式以实际 `configuration.yaml` 所在目录为准。
3. 重启 Home Assistant。
4. 打开 **设置 → 设备与服务 → 添加集成**，搜索 **Aladdin Connect Cloud**。
5. 输入 Aladdin Connect App 的邮箱和密码。集成会先验证登录和设备查询，成功后创建实体。

最终目录结构必须为：

```text
/config/
├── configuration.yaml
└── custom_components/
    └── aladdin_connect_cloud/
        ├── __init__.py
        ├── api.py
        ├── binary_sensor.py
        ├── config_flow.py
        ├── const.py
        ├── coordinator.py
        ├── cover.py
        ├── entity.py
        ├── manifest.json
        ├── sensor.py
        ├── strings.json
        └── translations/
            ├── en.json
            └── zh-Hans.json
```

请勿多套一层仓库名称目录。无需配置 YAML，也无需安装 Homebridge。本项目支持 HACS 自定义仓库和手动安装。

## 提供的实体

每扇门作为一个 Home Assistant 设备，使用 `deviceId:doorIndex` 保持稳定身份。一个控制器上的多扇门分别建模。

| 实体 | 功能 |
| --- | --- |
| `cover`，设备类型 `garage` | 开门、关门；显示打开、关闭、正在打开、正在关闭 |
| 故障 `binary_sensor` | API 的 `fault` 标志，或开门/关门超时 |
| 电池 `sensor` | 支持电池的型号提供电量百分比 |
| 低电量 `binary_sensor` | 支持电池的型号按设定阈值报告低电量 |

只有开、关功能，没有停止、开到某个百分比或位置控制。未配置、未知状态和动作超时的门显示 `unknown`，不会猜测为关闭。故障实体代表云端报告的故障或动作超时，并非独立的物理障碍物传感器。

电池逻辑沿用原仓库：`battery_level > 0` 时才建立电池实体，且 `link_status == 3` 才认为电量有效。原 API 用 `0` 同时表示无电池型号，因此无法可靠区分“无电池”和“电量耗尽”。已建立的电池实体遇到 `0` 或失联时显示 `unknown`。后来首次出现有效电量的门会自动补充电池实体。

实体 ID 由 Home Assistant 根据设备名称生成，例如 `cover.main_garage`。实际 ID 请在设备页面确认。

## 选项

在集成卡片上打开配置选项；保存后自动重新加载。

| 选项 | 默认值 | 说明 |
| --- | --- | --- |
| 轮询间隔 | 15 秒 | 可设置 5–60 秒，所有门共享一次设备列表查询 |
| 显示共享门 | 关闭 | 是否显示分享给当前账号的门；控制权限由 Genie 云端决定 |
| 忽略的门 | 空 | 从列表选择，或输入云端 `door.id`，例如 `F0AD4E1BC74D_1` |
| 低电量阈值 | 15% | 可设置 0–100%；小于或等于阈值时报告低电量 |

发送成功指令后立即请求刷新，随后最多每 5 秒查询一次，直到云端报告目标状态或指令等待超过 90 秒。云端仍报告门正在运动时继续每 5 秒查询。门稳定后恢复常规间隔。不会仅凭 HTTP 成功就把实体改成打开或关闭。

新增的门会在后续轮询中自动添加；门从账号消失、被禁用，或云端查询失败时，对应实体标为 `unavailable`。恢复正常查询后自动恢复。此实现没有推送通知，状态更新受 Genie 云端延迟影响。

## 在自动化中使用

使用 Home Assistant 标准动作，替换示例中的实体 ID：

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

可通过标准 HomeKit Bridge 集成将这些 `cover` 实体再暴露给 Apple 家庭 App；设备侧仍通过 Genie 云端控制。

## 认证和异常处理

- `AccessToken` 只保存在内存，按秒计算有效期，并提前 30 秒失效；需要时用账号密码重新登录，行为与原项目一致。
- 只读设备查询遇到 HTTP 401，会获取新令牌并重试一次；再次被拒绝时触发 Home Assistant 重新认证。
- 开关门 POST 请求只发送一次。超时、网络中断、5xx、401 或权限错误不会自动重发物理操作。超时可能意味着云端已收到指令但响应丢失，请先确认门的状态。
- 临时网络故障会由 Home Assistant 的集成启动重试机制处理；运行期间查询失败则显示实体不可用。
- 密码变化后可使用集成菜单中的“重新配置”更新同一账号的密码；认证失效也会出现重新认证提示。切换账号时添加另一条集成配置。
- Cognito MFA、改密码等额外登录挑战没有自动处理；界面会提示在官方 App 完成相关步骤。持续要求验证码的账号不受支持。
- 账号密码由 Home Assistant 的配置条目保存；请按普通 HA 凭据保护配置目录和备份。代码不记录密码、令牌或完整 API 响应。

## 与官方集成的关系

Home Assistant 自带的 [Aladdin Connect 集成](https://www.home-assistant.io/integrations/aladdin_connect/) 使用厂商合作 SDK / OAuth 路径。本包按用户要求移植 Homebridge 的 App API 路径，并非替换官方集成或宣称获得厂商支持。App API 和内置客户端参数可能随厂商更新而改变。

本移植版的问题请提交到[本仓库](https://github.com/vshijiav/homeassistant-aladdin-connect-cloud/issues)，不要提交给原仓库维护者。

## 开发与测试

交付包包含测试源码。测试使用实际 Home Assistant Core 和其测试框架，但所有 Genie HTTP 请求均模拟，禁止外网 socket。没有使用真实账号，也没有操作真实车库门。

在 Linux 环境运行：

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m pytest --cov --cov-report=term-missing
```

默认开发环境固定为 Home Assistant 2026.10.1 / Python >= 3.14.2；验证 Core 2026.9.4 时使用 `requirements-dev-ha2026.9.txt`。测试覆盖登录与令牌缓存、令牌过期和 401 恢复、开关门 URL / 请求体、失败命令不重发、配置与重新认证、实际 HA 实体状态、故障/电池状态、共享门和忽略选项、后续设备发现、断网恢复以及卸载。

仍需在实际 Home Assistant 和 Genie 账号上验证账号登录、设备列表和门控行为。测试通过不等于厂商当前线上接口已实测。

GitHub Actions 会运行 HACS 验证、代码检查以及 Core 2026.9.4 / 2026.10.1 自动化测试，不访问真实 Genie 账号，不操作车库门，也不会改变仓库可见性或自动发布。

在将测试预览视为实机已验证版本前，需要检查账号登录与设备发现、开关门及动作状态、断网恢复、更新密码与重新认证，以及适用型号的电池数据和共享门权限。记录测试结果时不要包含密码、令牌、邮箱或原始账号/设备响应。

## 授权

Apache License 2.0。保留原项目许可证，来源与改写范围见 `NOTICE`。
