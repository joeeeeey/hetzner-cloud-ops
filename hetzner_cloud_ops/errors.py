from __future__ import annotations


class HetznerSkillError(RuntimeError):
    pass


class ConfigError(HetznerSkillError):
    pass


class BackendError(HetznerSkillError):
    def __init__(self, message: str, *, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


class SyncError(HetznerSkillError):
    def __init__(self, message: str, *, hint: str | None = None):
        super().__init__(message)
        self.hint = hint

