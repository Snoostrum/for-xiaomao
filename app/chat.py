from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from app import __version__
from app.config import Config, load_config
from app.llm.provider import LLMError, chat_completion

log = logging.getLogger(__name__)

# 只带最近这些条上下文去问:够聊,又不至于越聊越贵
MAX_HISTORY_MESSAGES = 20

EXIT_WORDS = {"退出", "exit", "quit"}


def trim_history(history: list[dict], limit: int = MAX_HISTORY_MESSAGES) -> None:
    """掐头:只留最近 limit 条;开头若是一条 assistant 的回应,一并丢掉(没头没尾的回应会带坏模型)。"""
    if len(history) > limit:
        del history[: len(history) - limit]
    while history and history[0]["role"] != "user":
        del history[0]


def chat_turn(cfg: Config, history: list[dict], user_text: str) -> str:
    """一问一答。成功:这一问一答都记进 history(下轮带上下文);失败:返回人话,这一问不记(重问一次即可)。"""
    messages = [*history, {"role": "user", "content": user_text}]
    try:
        answer = chat_completion(cfg, messages)
    except LLMError as e:
        log.warning("终端聊天失败:%s | %s", e.human, e.detail)
        return e.human
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": answer})
    trim_history(history)
    return answer


def _config_problem(cfg: Config) -> str:
    """缺什么就返回一句"去哪补"的人话;都齐了返回空字符串。"""
    if not cfg.api_key:
        return "还没填 API Key——在浏览器打开的「设置」页里填好、保存,回来直接打字就行。"
    if not cfg.base_url:
        return "还没填「接口地址」——在浏览器打开的「设置」页里填好、保存。"
    if not cfg.model:
        return "还没填「模型名」——在浏览器打开的「设置」页里填好、保存。"
    return ""


def _banner(url: str) -> str:
    return (
        f"小灶 v{__version__} 开好了,网页版在:{url}\n"
        "这个窗口可以聊天:直接打字,回车发出去;输入「退出」结束。"
    )


def chat_loop(
    data_dir: Path,
    url: str,
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> None:
    """终端聊天循环。每轮都重读配置——网页里刚填好的 Key,下一句就生效。"""
    print_fn(_banner(url))
    problem = _config_problem(load_config(data_dir))
    if problem:
        print_fn(f"小灶> {problem}")

    history: list[dict] = []
    while True:
        try:
            text = input_fn("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print_fn("")
            break
        if not text:
            continue
        if text.lower() in EXIT_WORDS:
            break
        cfg = load_config(data_dir)
        problem = _config_problem(cfg)
        if problem:
            print_fn(f"小灶> {problem}")
            continue
        try:
            answer = chat_turn(cfg, history, text)
        except KeyboardInterrupt:
            print_fn("")
            break
        print_fn(f"小灶> {answer}")
    print_fn("再见——这个窗口可以关了。")
