import type { PlatformId } from "../types/prototype.ts";

/**
 * 根据 User-Agent 和触控特征匹配平台类型。
 */
export function browserPlatform(
  userAgent: string = typeof navigator !== "undefined" ? navigator.userAgent : "",
  maxTouchPoints: number = typeof navigator !== "undefined" ? navigator.maxTouchPoints : 0
): PlatformId {
  if (
    /iPhone|iPad|iPod/.test(userAgent) ||
    (/Macintosh/.test(userAgent) && maxTouchPoints > 1)
  ) {
    return "ios";
  }
  if (/Android/.test(userAgent)) return "android";
  if (/Macintosh|Mac OS X/.test(userAgent)) return "mac";
  if (/Windows/.test(userAgent)) return "windows";
  return "linux";
}

/**
 * 校验 IPv4 地址或合法域名。
 */
export function validHost(value: string): boolean {
  if (!value) return false;
  if (/^\d+\.\d+\.\d+\.\d+$/.test(value)) {
    return value.split(".").every((x) => {
      const n = Number(x);
      return !Number.isNaN(n) && n >= 0 && n <= 255;
    });
  }
  return /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$/i.test(
    value
  );
}

/**
 * 生成演示用途的高熵随机口令。
 */
export function demoPassword(): string {
  if (typeof crypto !== "undefined" && crypto.getRandomValues) {
    const a = new Uint32Array(2);
    crypto.getRandomValues(a);
    return `demo-${a[0].toString(36)}-${a[1].toString(36)}`;
  }
  return `demo-${Math.random().toString(36).slice(2, 8)}-${Date.now().toString(36)}`;
}
