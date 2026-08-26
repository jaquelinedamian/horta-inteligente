"""Simulador sem dependências externas para o controlador ESP8266 do MVP."""
import argparse
import json
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from uuid import uuid4


def request(base_url, token, method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v1/device/{path}", data=data, method=method,
        headers={"Authorization": f"Device {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", required=True)
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        now = datetime.now(timezone.utc).isoformat()
        values = {"air-temperature": random.uniform(18, 30), "air-humidity": random.uniform(45, 85), "air-pressure": random.uniform(995, 1020), "water-level": random.uniform(20, 100)}
        readings = [{"channel": key, "value": round(value, 2), "recorded_at": now, "idempotency_key": str(uuid4())} for key, value in values.items()]
        try:
            print(request(args.url, args.token, "POST", "telemetry/", {"readings": readings}))
            print(request(args.url, args.token, "POST", "heartbeat/", {"recorded_at": now, "uptime_seconds": int(time.monotonic()), "signal_strength": -55, "free_heap_bytes": 42000, "firmware_version": "sim-1.0"}))
            commands = request(args.url, args.token, "GET", "commands/")
            for command in commands["commands"]:
                print("executando", command)
                print(request(args.url, args.token, "POST", f"commands/{command['id']}/ack/", {"status": "succeeded", "result": {"simulated": True}}))
        except urllib.error.URLError as exc:
            print("erro:", exc)
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
