"""Linux SSH adapter: secrets stay in anonymous memory, outside argv and env."""
import json
import os
import subprocess
import sys


def run(job, arguments, runner=subprocess.call, memory_file=None):
    memory_file = memory_file or getattr(os, "memfd_create", None)
    if memory_file is None:
        raise RuntimeError("Linux anonymous memory files are required")
    descriptors = []

    def anonymous(name, value):
        fd = memory_file(name)
        descriptors.append(fd)
        os.fchmod(fd, 0o600)
        os.write(fd, value.encode())
        os.lseek(fd, 0, os.SEEK_SET)
        return fd

    try:
        host, user = job["ip"], job["user"]
        port = int(job.get("ssh_port") or 22)
        label = host if port == 22 else "[%s]:%s" % (host, port)
        known = anonymous("ownline-host", "%s %s %s\n" % (label, job["host_key_type"], job["host_key"]))
        path = lambda fd: "/proc/%s/fd/%s" % (os.getpid(), fd)
        command = ["ssh", "-p", str(port), "-o", "StrictHostKeyChecking=yes",
                   "-o", "GlobalKnownHostsFile=/dev/null", "-o", "UserKnownHostsFile=" + path(known),
                   "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=10",
                   "-o", "ServerAliveCountMax=3", "-o", "NumberOfPasswordPrompts=1"]
        phrase = ""
        if job.get("private_key"):
            key = anonymous("ownline-key", job["private_key"].rstrip("\n") + "\n")
            command += ["-i", path(key), "-o", "IdentitiesOnly=yes"]
            phrase = job.get("passphrase") or ""
            if not phrase:
                command += ["-o", "BatchMode=yes"]
        else:
            phrase = job.get("password") or ""
        inherited = []
        if phrase:
            password_fd = anonymous("ownline-auth", phrase + "\n")
            inherited.append(password_fd)
            prefix = ["sshpass", "-d", str(password_fd)]
            if job.get("private_key"):
                prefix += ["-P", "Enter passphrase"]
            command = prefix + command
        command += [user + "@" + host] + list(arguments)
        return runner(command, pass_fds=tuple(inherited))
    finally:
        for fd in descriptors:
            os.close(fd)


if __name__ == "__main__":
    try:
        with os.fdopen(int(sys.argv[1]), "r") as source:
            payload = source.read(150001)
        if len(payload.encode()) > 150000:
            raise ValueError("input too large")
        raise SystemExit(run(json.loads(payload), sys.argv[2:]))
    except (OSError, ValueError, KeyError, RuntimeError):
        print("安全 SSH 连接未完成", file=sys.stderr)
        raise SystemExit(2)
