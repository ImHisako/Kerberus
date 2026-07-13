import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from kerberus.network_insights import collect_i2p_peer_connections, lookup_ip_geolocation


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.payload


class NetworkInsightsTests(unittest.TestCase):
    def test_collects_only_public_established_i2p_router_peers(self):
        connections = [
            SimpleNamespace(status="ESTABLISHED", raddr=SimpleNamespace(ip="8.8.8.8", port=443)),
            SimpleNamespace(status="ESTABLISHED", raddr=SimpleNamespace(ip="127.0.0.1", port=7656)),
            SimpleNamespace(status="CLOSE_WAIT", raddr=SimpleNamespace(ip="1.1.1.1", port=80)),
        ]
        process = SimpleNamespace(
            info={"pid": 1, "name": "java", "cmdline": ["java", "-jar", "router.jar"]},
            net_connections=lambda kind: connections,
        )
        fake = SimpleNamespace(
            process_iter=lambda _attrs: [process],
            AccessDenied=RuntimeError,
            NoSuchProcess=RuntimeError,
            ZombieProcess=RuntimeError,
        )
        with patch.dict(sys.modules, {"psutil": fake}):
            peers = collect_i2p_peer_connections()
        self.assertEqual([(peer["ip"], peer["port"]) for peer in peers], [("8.8.8.8", 443)])

    def test_free_ip_lookup_needs_no_token_and_normalizes_connection_fields(self):
        payload = {
            "success": True, "ip": "8.8.8.8", "country": "United States", "country_code": "US",
            "connection": {"asn": 15169, "org": "Google LLC", "domain": "google.com"},
        }
        with patch("kerberus.network_insights.urlopen", return_value=_Response(payload)) as opened:
            result = lookup_ip_geolocation("8.8.8.8")
        request = opened.call_args.args[0]
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(request.full_url, "https://ipwho.is/8.8.8.8")
        self.assertEqual(result["country_code"], "US")
        self.assertEqual(result["as_name"], "Google LLC")

    def test_ipinfo_rejects_private_addresses_without_network_call(self):
        with patch("kerberus.network_insights.urlopen") as opened:
            with self.assertRaises(ValueError):
                lookup_ip_geolocation("127.0.0.1")
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
