"""In-memory lifecycle for a single local first-installation session."""

import threading

from .installations import CheckedTargets, InstallError


class LocalSetupSession:
    def __init__(self, checker, installer):
        self._checker = checker
        self._installer = installer
        self._targets = CheckedTargets()
        self._lock = threading.Lock()
        self._state = {"state": "idle"}

    def check(self, login):
        with self._lock:
            if self._state["state"] == "running":
                raise InstallError("安装正在进行，请等待原任务结束")
        result = self._checker(login)
        if not result.get("ready_for_install"):
            return {"result": result}
        token = self._targets.remember(login, result)
        return {"result": result, "check_token": token}

    def start(self, token):
        with self._lock:
            if self._state["state"] != "idle":
                raise InstallError("已有安装任务，请查看原任务状态")
            checked = self._targets.take(token)
            self._state = {"state": "running"}
        thread = threading.Thread(target=self._run, args=(checked,), daemon=True)
        try:
            thread.start()
        except RuntimeError:
            checked["login"].clear()
            with self._lock:
                self._state = {"state": "attention", "message": "无法启动安装任务，请重新检查。"}
            raise InstallError("无法启动安装任务，请重新检查") from None

    def _run(self, checked):
        try:
            def checker(login):
                return {"ok": True, "result": self._checker(login)}

            CheckedTargets.recheck(checked, checker)
            result = self._installer(checked)
            if not isinstance(result, dict) or result.get("verified") is not True:
                raise InstallError("安装结果尚未通过完整验收")
            with self._lock:
                self._state = {"state": "done", "delivery": result["delivery"]}
        except Exception:
            # Never expose external exception text: it may contain credentials.
            with self._lock:
                self._state = {"state": "attention", "message": "安装或验收未完成，请检查原任务；不要重复安装。"}
        finally:
            checked["login"].clear()

    def status(self):
        with self._lock:
            return dict(self._state)
