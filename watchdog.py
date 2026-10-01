# -*- coding: utf-8 -*-
"""
Live Stream Health Watchdog (HLS / RTMP / RTSP)
Author: Eng. MHD. Shadi AL-Hasan <mhd.shadi.alhasan@gmail.com>
Phone: +963934005922
Copyright (c) 2026 MHD. Shadi AL-Hasan
"""

import os
import sys
import time
import json
import argparse
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

# Load .env file if available (standard library only)
def load_env_file(filepath: Optional[Path] = None) -> Dict[str, str]:
    """Loads environment key-values from a .env file without external dependencies."""
    env_vars: Dict[str, str] = {}
    if filepath is None:
        filepath = Path(".env")
    if not filepath.exists():
        return env_vars
    
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            env_vars[key] = val
            if key not in os.environ:
                os.environ[key] = val
    return env_vars


# --- Telegram Notification Templates ---

def render_critical_alert_template(
    stream_url: str,
    failure_count: int,
    threshold: int,
    timestamp: Optional[str] = None,
    error_detail: Optional[str] = None
) -> str:
    """Renders formatted Telegram Markdown alert for critical stream down event."""
    ts = timestamp or time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    detail = error_detail or "No active video stream detected via ffprobe probe."
    return (
        "🚨 *CRITICAL STREAM ALERT*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔴 *Status:* Stream Down / Stalled\n"
        f"📺 *Stream URL:* `{stream_url}`\n"
        f"⚠️ *Consecutive Failures:* {failure_count} (Threshold: {threshold})\n"
        f"⏱ *Timestamp:* `{ts}`\n"
        f"🛠 *Diagnostics:* {detail}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📡 _Broadcast Stream Health Watchdog_"
    )

def render_recovery_template(
    stream_url: str,
    failed_checks: int,
    timestamp: Optional[str] = None
) -> str:
    """Renders formatted Telegram Markdown notification when stream recovers."""
    ts = timestamp or time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    return (
        "✅ *STREAM RECOVERED & HEALTHY*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 *Status:* Video Stream Restored & Flowing\n"
        f"📺 *Stream URL:* `{stream_url}`\n"
        f"🔄 *Failed Checks Before Recovery:* {failed_checks}\n"
        f"⏱ *Timestamp:* `{ts}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📡 _Broadcast Stream Health Watchdog_"
    )

def render_digest_template(
    streams_summary: List[Dict[str, Any]],
    timestamp: Optional[str] = None
) -> str:
    """Renders periodic health summary digest for all monitored channels."""
    ts = timestamp or time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    lines = [
        "📊 *STREAM HEALTH DIGEST*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"⏱ *Generated:* `{ts}`",
        f"🔢 *Total Channels:* {len(streams_summary)}",
        ""
    ]
    for s in streams_summary:
        icon = "🟢" if s.get("healthy") else "🔴"
        name = s.get("name", s.get("url", "Unknown"))
        lines.append(f"{icon} *{name}*: {'ONLINE' if s.get('healthy') else 'FAILING'}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📡 _Broadcast Stream Health Watchdog_")
    return "\n".join(lines)


# --- JSON Filtering Engine ---

def filter_stream_info(
    probe_data: Dict[str, Any],
    codec_type: str = "video",
    min_width: Optional[int] = None,
    min_height: Optional[int] = None,
    codec_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Filters ffprobe JSON streams based on codec type, resolution, and codec name.
    """
    if not isinstance(probe_data, dict):
        return []
    streams = probe_data.get("streams", [])
    filtered: List[Dict[str, Any]] = []

    for s in streams:
        if codec_type and s.get("codec_type") != codec_type:
            continue
        if codec_name and s.get("codec_name", "").lower() != codec_name.lower():
            continue
        if min_width is not None and s.get("width", 0) < min_width:
            continue
        if min_height is not None and s.get("height", 0) < min_height:
            continue
        filtered.append(s)

    return filtered

def filter_streams_catalog(
    streams: List[Dict[str, Any]],
    protocol: Optional[str] = None,
    healthy_only: Optional[bool] = None,
    keyword: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Filters a JSON catalog of streaming channels by protocol, health, or keyword.
    """
    results: List[Dict[str, Any]] = []
    for s in streams:
        url = s.get("url", "").lower()
        name = s.get("name", "").lower()
        if protocol and not url.startswith(protocol.lower()):
            continue
        if healthy_only is not None and s.get("healthy") != healthy_only:
            continue
        if keyword:
            kw = keyword.lower()
            if kw not in url and kw not in name:
                continue
        results.append(s)
    return results


# --- Dispatcher ---

def send_telegram_alert(
    message: str,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    webhook_url: Optional[str] = None,
    parse_mode: str = "Markdown",
    timeout: int = 5
) -> bool:
    """
    Sends message to Telegram via Bot API or webhook URL.
    Returns True if sent successfully, False otherwise.
    """
    if bot_token and chat_id:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = json.dumps({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": parse_mode
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status == 200
        except Exception as e:
            print(f"[ERROR] Failed to send Telegram notification: {e}")
            return False

    elif webhook_url:
        payload = json.dumps({"text": message}).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status == 200
        except Exception as e:
            print(f"[ERROR] Failed to trigger alert webhook: {e}")
            return False

    return False


# --- Core Watchdog ---

class StreamWatchdog:
    def __init__(
        self,
        stream_url: str,
        check_interval: int = 10,
        failure_threshold: int = 3,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        telegram_webhook: Optional[str] = None
    ):
        self.stream_url = stream_url
        self.check_interval = check_interval
        self.failure_threshold = failure_threshold
        self.telegram_bot_token = telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.telegram_webhook = telegram_webhook or os.getenv("TELEGRAM_WEBHOOK")
        
        self.consecutive_failures = 0
        self.is_failing_state = False
        self.last_probe_data: Dict[str, Any] = {}

    def probe_stream(self, timeout: int = 8) -> Tuple[bool, Dict[str, Any]]:
        """Probes stream for 5 seconds using ffprobe and extracts JSON streams."""
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
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
            if res.returncode == 0:
                data = json.loads(res.stdout.decode('utf-8'))
                self.last_probe_data = data
                video_streams = filter_stream_info(data, codec_type="video")
                return (len(video_streams) > 0, data)
        except Exception as e:
            self.last_probe_data = {"error": str(e)}
            return (False, self.last_probe_data)
        return (False, {})

    def check_health(self) -> bool:
        """Convenience method returning boolean stream status."""
        is_healthy, _ = self.probe_stream()
        return is_healthy

    def notify(self, message: str, alert_type: str = "critical") -> bool:
        """Dispatches alert through print logging and configured Telegram/Webhook."""
        print(f"[{alert_type.upper()}] {message}")
        return send_telegram_alert(
            message=message,
            bot_token=self.telegram_bot_token,
            chat_id=self.telegram_chat_id,
            webhook_url=self.telegram_webhook
        )

    def tick(self) -> Dict[str, Any]:
        """
        Executes a single monitoring cycle.
        Returns status dictionary containing health, failures, and alert status.
        """
        is_alive, probe_data = self.probe_stream()
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        result: Dict[str, Any] = {
            "timestamp": timestamp,
            "stream_url": self.stream_url,
            "is_alive": is_alive,
            "consecutive_failures": self.consecutive_failures,
            "alert_sent": False,
            "recovered": False
        }

        if is_alive:
            if self.is_failing_state:
                # Stream recovered!
                recovery_msg = render_recovery_template(
                    stream_url=self.stream_url,
                    failed_checks=self.consecutive_failures,
                    timestamp=timestamp
                )
                self.notify(recovery_msg, alert_type="recovery")
                result["recovered"] = True
                self.is_failing_state = False

            print(f"[{timestamp}] [OK] Stream is active and flowing.")
            self.consecutive_failures = 0
            result["consecutive_failures"] = 0
        else:
            self.consecutive_failures += 1
            result["consecutive_failures"] = self.consecutive_failures
            print(f"[{timestamp}] [FAIL] Stream stalled/unresponsive! (Failures: {self.consecutive_failures})")
            
            if self.consecutive_failures >= self.failure_threshold and not self.is_failing_state:
                self.is_failing_state = True
                alert_msg = render_critical_alert_template(
                    stream_url=self.stream_url,
                    failure_count=self.consecutive_failures,
                    threshold=self.failure_threshold,
                    timestamp=timestamp
                )
                self.notify(alert_msg, alert_type="alert")
                result["alert_sent"] = True

        return result

    def monitor(self):
        """Runs the continuous monitoring loop."""
        print(f"[*] Starting Stream Watchdog for: {self.stream_url}")
        print(f"[*] Check Interval: {self.check_interval}s | Threshold: {self.failure_threshold}")
        
        while True:
            self.tick()
            time.sleep(self.check_interval)

def main():
    load_env_file()
    parser = argparse.ArgumentParser(description="Monitor live stream status (HLS/RTMP/RTSP).")
    parser.add_argument(
        "--url", "-u",
        default=os.getenv("STREAM_URL"),
        help="Live stream URL to probe (defaults to STREAM_URL from .env)"
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=int(os.getenv("CHECK_INTERVAL", "10")),
        help="Check interval in seconds"
    )
    parser.add_argument(
        "--threshold", "-t",
        type=int,
        default=int(os.getenv("FAILURE_THRESHOLD", "3")),
        help="Consecutive failure threshold before alert"
    )
    parser.add_argument(
        "--filter-json",
        action="store_true",
        help="Run probe once and output filtered JSON streams analysis"
    )
    args = parser.parse_args()

    if not args.url:
        parser.error("Stream URL is required. Provide via --url or STREAM_URL in .env")

    watchdog = StreamWatchdog(
        stream_url=args.url,
        check_interval=args.interval,
        failure_threshold=args.threshold
    )

    if args.filter_json:
        is_alive, probe_data = watchdog.probe_stream()
        filtered = filter_stream_info(probe_data)
        print(json.dumps({
            "is_alive": is_alive,
            "video_streams": filtered,
            "stream_url": args.url
        }, indent=2))
        return

    try:
        watchdog.monitor()
    except KeyboardInterrupt:
        print("\nWatchdog stopped.")

if __name__ == "__main__":
    main()
