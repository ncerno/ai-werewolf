"""配置加载器：从 YAML 文件和环境变量加载配置。"""
import os
import sys
import json
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# 项目根目录（src/utils/config.py → src/utils → src → 项目根）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default.yaml"
USER_CONFIG_PATH = PROJECT_ROOT / "data" / "user_config.json"


def _load_yaml(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        print(f"[FATAL] 配置文件不存在: {path}", file=sys.stderr)
        print("  请确保 config/default.yaml 存在。可从 config/default.yaml.example 复制。", file=sys.stderr)
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"[FATAL] 配置文件格式错误: {path}", file=sys.stderr)
        print(f"  {e}", file=sys.stderr)
        sys.exit(1)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f) or {}


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典，override 覆盖 base。"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict:
    """加载完整配置：default.yaml → user_config.json → 环境变量覆盖"""
    load_dotenv(PROJECT_ROOT / ".env")

    config = _load_yaml(DEFAULT_CONFIG_PATH)
    user_config = _load_json(USER_CONFIG_PATH)
    config = _deep_merge(config, user_config)

    # 环境变量覆盖 LLM API Key
    config = _apply_env_overrides(config)

    return config


def _apply_env_overrides(config: dict) -> dict:
    """用环境变量覆盖 LLM 配置中的敏感信息。"""
    env_map = {
        "LLM_DEFAULT_API_KEY": ("llm", "default", "api_key"),
        "LLM_DEFAULT_API_BASE": ("llm", "default", "api_base"),
        "LLM_DEFAULT_MODEL": ("llm", "default", "model"),
        "GOD_AGENT_API_KEY": ("llm", "god_agent", "api_key"),
    }

    for env_var, path in env_map.items():
        value = os.getenv(env_var)
        if value:
            section, sub, key = path
            if section in config and sub in config[section]:
                config[section][sub][key] = value

    return config


def save_user_config(config: dict) -> None:
    """保存用户配置到 JSON 文件。"""
    USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_llm_config_for_role(role: str, config: dict = None) -> dict:
    """获取指定角色的 LLM 配置，优先使用角色覆盖配置。"""
    if config is None:
        config = load_config()

    llm = config.get("llm", {})
    default = llm.get("default", {})
    overrides = llm.get("role_overrides", {})

    role_config = overrides.get(role, {})
    if role_config.get("enabled") and role_config.get("model"):
        result = default.copy()
        for key in ("model", "api_base", "api_key", "temperature", "max_tokens"):
            if role_config.get(key):
                result[key] = role_config[key]
        return result

    return default


def get_god_agent_config(config: dict = None) -> dict:
    """获取上帝 Agent 的 LLM 配置。"""
    if config is None:
        config = load_config()
    return config.get("llm", {}).get("god_agent", {})