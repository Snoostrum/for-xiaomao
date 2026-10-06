from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    base_url: str
    default_model: str


# 模型名与接口地址都会随平台调整;设置页允许手改,不做硬校验。
# 「需核实」= 动手当天打开对应平台文档确认一次(规格 §6-4)。
PRESETS: dict[str, Preset] = {
    "openrouter": Preset(
        key="openrouter",
        name="OpenRouter(免费起步)",
        base_url="https://openrouter.ai/api/v1",
        default_model="google/gemma-4-31b-it:free",  # 需核实
    ),
    "kimi": Preset(
        key="kimi",
        name="Kimi 国际版",
        base_url="https://api.moonshot.ai/v1",  # 需核实(platform.kimi.ai 文档)
        default_model="kimi-k3",  # 需核实
    ),
    "bailian_intl": Preset(
        key="bailian_intl",
        name="阿里百炼国际版",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",  # 需核实
        default_model="qwen3.8-flash",  # 需核实
    ),
    "deepseek": Preset(
        key="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-flash",  # deepseek-chat 仍是别名;以平台当天文档为准
    ),
    "custom": Preset(key="custom", name="自定义", base_url="", default_model=""),
}
