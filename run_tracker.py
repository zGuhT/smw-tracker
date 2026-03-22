"""
Entry point for the hardware tracker.

Modes:
  (default)   Direct DB access, local only
  --http      HTTP API client (for split deployments)
  --cloud     Direct DB + cloud sync (pushes state to smwtracker.com)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="SMW Tracker - Hardware Poller")
    parser.add_argument("--http", action="store_true", help="Use HTTP API client")
    parser.add_argument("--cloud", action="store_true", help="Enable cloud sync (local + push to cloud)")
    parser.add_argument("--cloud-url", default="https://smwtracker.com", help="Cloud server URL")
    parser.add_argument("--api-key", default=None, help="API key for cloud (or set SMW_API_KEY env)")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="API base URL (--http mode)")
    parser.add_argument("--qusb-url", default="ws://127.0.0.1:23074", help="QUsb2Snes WebSocket URL")
    parser.add_argument("--poll", type=float, default=0.25, help="Poll interval in seconds")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    from hardware.qusb_client import QUsb2SnesClient
    from hardware.smw_tracker import SMWTracker

    # Choose client
    if args.cloud:
        from core.db import init_db
        from hardware.cloud_client import CloudSyncClient
        init_db()
        api_key = args.api_key or os.environ.get("SMW_API_KEY", "")
        client = CloudSyncClient(cloud_url=args.cloud_url, api_key=api_key)
        logging.info("Using cloud sync client → %s", args.cloud_url)
    elif args.http:
        from hardware.tracker_client import HttpApiClient
        client = HttpApiClient(base_url=args.api_url)
        logging.info("Using HTTP API client → %s", args.api_url)
    else:
        from core.db import init_db
        from hardware.tracker_client import DirectServiceClient
        init_db()
        client = DirectServiceClient()
        logging.info("Using direct service client (no HTTP overhead)")

    qusb = QUsb2SnesClient(url=args.qusb_url, app_name="SMW Tracker")
    qusb.connect()
    device = qusb.auto_attach_first_device(wait=True)
    logging.info("Attached to device: %s", device)

    tracker = SMWTracker(qusb=qusb, client=client)
    tracker.run_forever(poll_seconds=args.poll)


if __name__ == "__main__":
    main()
