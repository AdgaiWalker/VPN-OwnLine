import type { PlatformId } from "../types/prototype.ts";

/**
 * 依据客户端支持矩阵获取当前系统对应的代理应用列表。
 * PRD 明确支持: Shadowrocket (iOS/Mac), Clash (Mac/Win/Android), FL Clash (Win/Android)。
 */
export function getClientApps(platform: PlatformId): string[] {
  switch (platform) {
    case "ios":
      return ["Shadowrocket"];
    case "mac":
      return ["Shadowrocket", "Clash"];
    case "android":
      return ["FL Clash", "Clash"];
    case "windows":
    case "linux":
    default:
      return ["Clash", "FL Clash"];
  }
}

/**
 * 获取客户端官方下载或接入指引信息。
 */
export function getClientAppInfo(appName: string): { label: string; guideUrl?: string } {
  switch (appName) {
    case "Shadowrocket":
      return { label: "Shadowrocket (小火箭)", guideUrl: "https://apps.apple.com/app/shadowrocket/id932747118" };
    case "FL Clash":
      return { label: "FL Clash (跨平台轻量)", guideUrl: "https://github.com/chen08209/FlClash" };
    case "Clash":
    default:
      return { label: "Clash", guideUrl: "https://github.com/Dreamacro/clash" };
  }
}
