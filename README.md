# astrbot_plugin_zhouli

让 AstrBot 支持合乎周礼的问礼、释礼和会话回复模式。

## 功能

- `/zhouli on`：开启当前会话的周礼模式。
- `/zhouli off`：关闭当前会话的周礼模式。
- `/zhouli status`：查看当前会话状态。
- `/zhouli ask <文本>` 或 `/问礼 <文本>`：把现代中文改写成周礼体。
- `/zhouli plain <文本>` 或 `/释礼 <文本>`：把周礼体翻回直接的人话。
- 自然触发词：如“进入周礼模式”“问礼：文本”“退朝”，可在 WebUI 配置里修改。
- 问礼会优先保持原意、立场、否定/肯定关系和疑问/陈述等句式，同时补关系、释名分、作白话类比，让周礼体带一点论证感。
- 释礼会把周礼体翻回人话，保持原文对象、立场和句式，不继续整活。

## 配置

插件提供 `_conf_schema.json`，可在 AstrBot WebUI 的插件配置页修改：

- 是否默认开启周礼模式。
- 群聊自然触发是否需要 @ 机器人。
- 问礼/释礼/开启/关闭触发词。
- 自动选择辞气、默认篇幅、最大输入字数；默认篇幅会影响论证展开程度。
- 可选指定 LLM provider ID。

## 数据

会话模式状态会保存到 AstrBot 的插件数据目录 `data/plugin_data/astrbot_plugin_zhouli/zhouli_state.json`。卸载插件时，AstrBot 的插件管理逻辑可以正常识别并清理插件本体；状态数据按 AstrBot 的插件数据目录规则独立保存。

## 示例

用户：

```text
/问礼 疯狂星期四，谁请我吃饭才合乎周礼
```

机器人会调用当前 AstrBot LLM provider 返回周礼体改写结果。

## 致谢

周礼体规则参考 `Aspirin0000/zhouli-translator` 的 `speak-zhouli` 思路，并针对 AstrBot 插件运行做了轻量化 prompt。
