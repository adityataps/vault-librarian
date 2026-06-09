from __future__ import annotations


class LibrarianInbox:
    def __init__(self, cfg, tools) -> None:
        self.cfg = cfg
        self.tools = tools

    def propose(self, action: str) -> None:
        pass

    def execute_checked(self) -> list[str]:
        return []
