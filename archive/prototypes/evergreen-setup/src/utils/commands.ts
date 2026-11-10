import { BOOTSTRAP_COMMAND } from "../constants/providers.ts";

/**
 * 生成安全的远程 SSH 连接命令字符串。
 */
export function formatSshCommand(user: string, host: string, port: string): string {
  const p = (port || "22").trim();
  const u = (user || "root").trim();
  const h = (host || "").trim();
  if (!h) return "";
  if (p === "22") {
    return `ssh ${u}@${h}`;
  }
  return `ssh -p ${p} ${u}@${h}`;
}

/**
 * 获取主控一键自举命令。
 */
export function getBootstrapCommand(): string {
  return BOOTSTRAP_COMMAND;
}
