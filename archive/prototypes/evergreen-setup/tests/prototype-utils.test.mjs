import assert from "node:assert/strict";
import test from "node:test";
import { browserPlatform, validHost } from "../src/utils/platform.ts";
import { getClientApps } from "../src/utils/clientMatrix.ts";
import { formatSshCommand, getBootstrapCommand } from "../src/utils/commands.ts";

test("browserPlatform identifies iOS, Android, macOS, and Windows", () => {
  assert.equal(
    browserPlatform("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)", 5),
    "ios"
  );
  assert.equal(
    browserPlatform("Mozilla/5.0 (Linux; Android 13; Pixel 7)", 5),
    "android"
  );
  assert.equal(
    browserPlatform("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", 0),
    "mac"
  );
  assert.equal(
    browserPlatform("Mozilla/5.0 (Windows NT 10.0; Win64; x64)", 0),
    "windows"
  );
  assert.equal(
    browserPlatform("Mozilla/5.0 (X11; Linux x86_64)", 0),
    "linux"
  );
});

test("validHost accurately validates IPv4 and domain names", () => {
  assert.equal(validHost("127.0.0.1"), true);
  assert.equal(validHost("203.0.113.10"), true);
  assert.equal(validHost("256.0.0.1"), false);
  assert.equal(validHost("1.2.3"), false);
  assert.equal(validHost("server.example.com"), true);
  assert.equal(validHost("invalid_domain!"), false);
  assert.equal(validHost(""), false);
});

test("getClientApps matches PRD client matrix", () => {
  assert.deepEqual(getClientApps("ios"), ["Shadowrocket"]);
  assert.deepEqual(getClientApps("mac"), ["Shadowrocket", "Clash"]);
  assert.deepEqual(getClientApps("android"), ["FL Clash", "Clash"]);
  assert.deepEqual(getClientApps("windows"), ["Clash", "FL Clash"]);
});

test("formatSshCommand creates standard SSH strings", () => {
  assert.equal(formatSshCommand("root", "1.2.3.4", "22"), "ssh root@1.2.3.4");
  assert.equal(formatSshCommand("ubuntu", "1.2.3.4", "2222"), "ssh -p 2222 ubuntu@1.2.3.4");
  assert.equal(formatSshCommand("", "", "22"), "");
});

test("getBootstrapCommand returns non-empty shell pipe", () => {
  const cmd = getBootstrapCommand();
  assert.ok(cmd.includes("curl -fsSL"));
  assert.ok(cmd.includes("bootstrap.sh"));
});
