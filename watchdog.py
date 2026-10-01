# -*- coding: utf-8 -*-
"""
Live Stream Health Watchdog (HLS / RTMP / RTSP)
Author: Eng. MHD. Shadi AL-Hasan <mhd.shadi.alhasan@gmail.com>
Phone: +963934005922
Copyright (c) 2026 MHD. Shadi AL-Hasan
"""

import time
import subprocess
import json
import argparse
from pathlib import Path

class StreamWatchdog:
    def __init__(self, stream_url: str, check_interval: int = 10, telegram_webhook: str = None):
        self.stream_url = stream_url
        self.check_interval = check_interval
        self.telegram_webhook = telegram_webhook
        self.consecutive_failures = 0

    def check_health(self) -> bool:
        """Probes stream for 5 seconds using ffprobe."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-show_format",
            "-analyzeduration", "5000000",
            "-probesize", "5000000",
            self.stream_url
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8)
            if res.returncode == 0:
                data = json.loads(res.stdout.decode('utf-8'))
                streams = data.get("streams", [])
                has_video = any(s.get("codec_type") == "video" for s in streams)
                return has_video
        except Exception:
            return False
        return False

    def notify(self, message: str):
        print(f"[ALERT] {message}")
        # Webhook hook logic here

    def monitor(self):
        print(f"[*] Starting Stream Watchdog for: {self.stream_url}")
        print(f"[*] Check Interval: {self.check_interval}s")
        
        while True:
            is_alive = self.check_health()
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            if is_alive:
                print(f"[{timestamp}] [OK] Stream is active and flowing.")
                self.consecutive_failures = 0
            else:
                self.consecutive_failures += 1
                print(f"[{timestamp}] [FAIL] Stream stalled/unresponsive! (Failures: {self.consecutive_failures})")
                if self.consecutive_failures >= 3:
                    self.notify(f"Critical stream drop detected on {self.stream_url}!")
            time.sleep(self.check_interval)

def main():
    parser = argparse.ArgumentParser(description="Monitor live stream status (HLS/RTMP/RTSP).")
    parser.add_argument("--url", "-u", required=True, help="Live stream URL to probe")
    parser.add_argument("--interval", "-i", type=int, default=10, help="Check interval in seconds")
    args = parser.parse_args()

    watchdog = StreamWatchdog(args.url, args.interval)
    try:
        watchdog.monitor()
    except KeyboardInterrupt:
        print("\nWatchdog stopped.")

if __name__ == "__main__":
    main()
