"""In-memory lifecycle for a single local first-installation session."""

import threading
import time

from .installations import CheckedTargets, InstallError
from .local_setup_progress import STAGES
from .sshcheck.problem import Problem


class LocalSetupSession:
    def __init__(self, checker, installer, clock=time.monotonic):
        self._checker = checker
        self._installer = installer
        self._targets = CheckedTargets()
        self._lock = threading.Lock()
        self._state = {"state": "idle"}
        self._clock = clock
        self._history = []
        self._finished = None

    def report(self, stage):
        with self._lock:
            if self._state['state'] != 'running' or stage not in STAGES:
                return
            if self._history and tuple(STAGES).index(stage) <= tuple(STAGES).index(self._history[-1][0]):
                return
            self._history.append((stage, self._clock()))

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
            self._history = [('recheck', self._clock())]
        thread = threading.Thread(target=self._run, args=(checked,), daemon=True)
        try:
            thread.start()
        except RuntimeError:
            checked["login"].clear()
            with self._lock:
                self._state = {"state": "attention", 'error_code': 'INSTALL_FAILED', "message": "无法启动安装任务，请重新检查。"}
                self._finished = self._clock()
            raise InstallError("无法启动安装任务，请重新检查") from None

    def _run(self, checked):
        try:
            def checker(login):
                return {"ok": True, "result": self._checker(login)}

            CheckedTargets.recheck(checked, checker)
            result = self._installer(checked, self.report)
            if not isinstance(result, dict) or result.get("verified") is not True:
                raise InstallError("安装结果尚未通过完整验收")
            with self._lock:
                self._state = {"state": "done", "delivery": result["delivery"]}
                self._finished = self._clock()
        except Exception as exc:
            # Never expose external exception text: it may contain credentials.
            reasons = {'SSH_TIMEOUT': '服务器响应超时', 'SSH_UNAVAILABLE': 'SSH 连接不可用',
                       'SSH_AUTH_FAILED': 'SSH 认证失败', 'HOST_KEY_CHANGED': '服务器指纹发生变化'}
            code = exc.code if isinstance(exc, Problem) and exc.code in reasons else 'INSTALL_FAILED'
            with self._lock:
                label = STAGES[self._history[-1][0]]
                self._state = {"state": "attention", 'error_code': code,
                               "message": '在“' + label + '”阶段未完成：' + reasons.get(code, '执行或验收未通过') + '。请检查服务器原任务；不要重复安装。'}
                self._finished = self._clock()
        finally:
            checked["login"].clear()

    def status(self):
        with self._lock:
            result = dict(self._state)
            if self._history:
                now = self._finished if self._finished is not None else self._clock()
                stage, started = self._history[-1]
                result.update(stage=stage, stage_label=STAGES[stage],
                              elapsed_seconds=max(0, int(now - self._history[0][1])),
                              stage_elapsed_seconds=max(0, int(now - started)))
                result['stages'] = [
                    {'code': code, 'label': STAGES[code],
                     'elapsed_seconds': max(0, int((self._history[i + 1][1] if i + 1 < len(self._history) else now) - begin)),
                     'state': 'done' if i + 1 < len(self._history) or result['state'] == 'done' else result['state']}
                    for i, (code, begin) in enumerate(self._history)
                ]
            return result
