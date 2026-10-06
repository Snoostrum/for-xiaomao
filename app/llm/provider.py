from __future__ import annotations

import logging

import requests

from app.config import Config

log = logging.getLogger(__name__)


class LLMError(Exception):
    def __init__(self, human: str, detail: str = ""):
        super().__init__(human)
        self.human = human
        self.detail = detail


def _chat_url(cfg: Config) -> str:
    return cfg.base_url.rstrip("/") + "/chat/completions"


def _post_chat(cfg: Config, payload: dict, timeout: float) -> dict:
    url = _chat_url(cfg)
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.exceptions.Timeout:
        raise LLMError("等太久了没收到回应——网络慢或对方服务在忙,过会儿再试。", f"timeout {url}")
    except requests.exceptions.SSLError as e:
        raise LLMError("安全连接没建起来(SSL 错误)——检查『接口地址』填对了没有。", f"{e} | {url}")
    except requests.exceptions.ConnectionError as e:
        raise LLMError(f"连不上 {url} ——检查网络,或确认『接口地址』填对了。", f"{e} | {url}")
    except requests.exceptions.RequestException as e:
        raise LLMError(f"连不上 {url} ——检查网络;或确认『接口地址』填对了(要以 http:// 或 https:// 开头)。", f"{e} | {url}")

    if resp.status_code == 401:
        raise LLMError("Key 不对或已过期——去平台重新复制一个,粘贴到上面。", resp.text[:300])
    if resp.status_code == 402:
        raise LLMError("账户余额不足——去平台充值,或者先用免费模型。", resp.text[:300])
    if resp.status_code == 403:
        raise LLMError("平台拒绝了这个请求(403)——可能是地区限制或权限问题。", resp.text[:300])
    if resp.status_code == 404:
        raise LLMError("接口地址或模型名不对(404)——检查『接口地址』和『模型名』。", resp.text[:300])
    if resp.status_code == 429:
        raise LLMError("请求太频繁被限速了——等一分钟再试。", resp.text[:300])
    if resp.status_code >= 500:
        raise LLMError("对方服务器出错——不是你的问题,过会儿再试。", resp.text[:300])
    if resp.status_code != 200:
        raise LLMError(f"遇到没见过的错误(HTTP {resp.status_code})——细节在日志里。", resp.text[:300])

    try:
        return resp.json()
    except ValueError:
        raise LLMError("对方的回应看不懂(不是 JSON)——可能接口地址不对。", resp.text[:300])


def chat_completion(cfg: Config, messages: list[dict], max_tokens: int = 1024, timeout: float = 60.0) -> str:
    payload = {"model": cfg.model, "messages": messages, "max_tokens": max_tokens}
    data = _post_chat(cfg, payload, timeout)
    try:
        # content 偶尔是 null(只有推理没有正文),别把 None 当回复带出去
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise LLMError("回应里没有文本内容——可能模型名不对。", str(data)[:300])


def test_connection(cfg: Config) -> tuple[bool, str]:
    if not cfg.api_key:
        return False, "还没填 Key。"
    if not cfg.base_url:
        return False, "还没填接口地址。"
    if not cfg.model:
        return False, "还没填模型名。"
    try:
        chat_completion(cfg, [{"role": "user", "content": "你好"}], max_tokens=4, timeout=15.0)
    except LLMError as e:
        log.warning("测试连接失败:%s | %s", e.human, e.detail)
        return False, e.human
    return True, "连接成功,模型有回应 ✔"
