"""Check routing outcomes from real server and client configuration output."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from nodekit import templates, subscriptions


class AIDestinationRulesTests(unittest.TestCase):
    def test_ai_domains_and_subdomains_take_protected_server_and_client_routes(self):
        expected = (
            "chatgpt.com", "api.chatgpt.com", "openai.com", "api.openai.com",
            "anthropic.com", "api.anthropic.com", "claude.ai", "app.claude.ai",
            "oaistatic.com", "cdn.oaistatic.com", "oaiusercontent.com", "files.oaiusercontent.com",
            "ai.google.dev", "bard.google.com",
        )
        for warp in ({"type": "socks", "server_port": 40000}, {"private_key": "TEST"}):
            config = templates.exit_config(443, "id", "sni", "private", "1234", warp=warp)
            rules = config["route"]["rules"]
            self.assertIn({"action": "sniff"}, rules)
            for domain in expected + ("example.com", "notchatgpt.com"):
                with self.subTest(domain=domain, warp=warp):
                    selected = next(r["outbound"] for r in rules if "outbound" in r and (
                        not (r.get("domain_keyword") or r.get("domain_suffix"))
                        or any(keyword in domain for keyword in r.get("domain_keyword", []))
                        or any(domain == suffix or domain.endswith("." + suffix) for suffix in r.get("domain_suffix", []))
                    ))
                    self.assertEqual(selected, "warp-out" if domain in expected else "direct")
        node = {"name": "A", "host": "198.51.100.4", "port": 443, "uuid": "id"}
        for profile in ("all", "pro", "direct"):
            client = subscriptions.render_clash_yaml([node], profile=profile)
            rules = [line.strip()[2:].split(",") for line in client.split("rules:\n", 1)[1].splitlines() if line.strip().startswith("- ")]
            for domain in expected:
                selected = next(rule[-1] for rule in rules if (
                    rule[0] == "MATCH"
                    or rule[0] == "DOMAIN-KEYWORD" and rule[1] in domain
                    or rule[0] == "DOMAIN-SUFFIX" and (domain == rule[1] or domain.endswith("." + rule[1]))
                ))
                self.assertEqual(selected, "🤖 AI 业务", (domain, profile))


if __name__ == "__main__":
    unittest.main()
