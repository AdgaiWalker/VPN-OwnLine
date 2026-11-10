import argparse
import getpass
import json
import os
import secrets
from pathlib import Path

from werkzeug.security import generate_password_hash

from .service import Config, Worker, create_app

parser = argparse.ArgumentParser(description="长青受控首次安装入口（独立最小闭环）")
parser.add_argument("command", choices=["init", "api", "worker"])
parser.add_argument("--config", required=True)
parser.add_argument("--origin", default="https://setup.example.com")
parser.add_argument("--port", type=int, default=4180)
parser.add_argument("--development", action="store_true")
args = parser.parse_args()
if args.command == "init":
    path = Path(args.config).resolve()
    if path.exists():
        raise SystemExit("配置已存在，不覆盖。")
    password = getpass.getpass("安装入口管理员密码：")
    if len(password) < 12:
        raise SystemExit("请使用至少 12 个字符。")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = {
        "origin": args.origin,
        "auth_user": "admin",
        "auth_hash": generate_password_hash(password),
        "csrf_key": secrets.token_hex(32),
        "data_dir": str(path.parent / "data"),
        "source_dir": str(Path(__file__).resolve().parents[2]),
        "development": args.development,
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(config, f, indent=2)
    print("入口配置已创建，管理员密码未写入配置。")
elif args.command == "worker":
    Worker(Config(args.config)).run()
else:
    from waitress import serve

    serve(create_app(Config(args.config)), host="127.0.0.1", port=args.port, threads=4)
