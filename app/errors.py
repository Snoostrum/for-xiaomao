from __future__ import annotations


class HumanError(Exception):
    """带人话的异常:界面上展示 human,细节留给日志/排查。"""

    def __init__(self, human: str, detail: str = ""):
        super().__init__(human)
        self.human = human
        self.detail = detail
