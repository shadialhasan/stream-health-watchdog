# -*- coding: utf-8 -*-
"""
Automated Tests for Live Stream Health Watchdog
Author: Eng. MHD. Shadi AL-Hasan <mhd.shadi.alhasan@gmail.com>
"""

import json
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile

from watchdog import (
    StreamWatchdog,
    filter_stream_info,
    filter_streams_catalog,
    render_critical_alert_template,
    render_recovery_template,
    render_digest_template,
    send_telegram_alert,
    load_env_file
)

class TestStreamWatchdog(unittest.TestCase):
    def setUp(self):
        self.stream_url = "https://live.example.com/hls/channel1.m3u8"
        self.watchdog = StreamWatchdog(
            stream_url=self.stream_url,
            check_interval=10,
            failure_threshold=3,
            telegram_bot_token="test_token",
            telegram_chat_id="12345678"
        )

    @patch("subprocess.run")
    def test_watchdog_probe_success(self, mock_run):
        """Test probing returns true when valid video stream is present."""
        probe_output = {
            "streams": [
                {
                    "index": 0,
                    "codec_name": "h264",
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1"
                },
                {
                    "index": 1,
                    "codec_name": "aac",
                    "codec_type": "audio",
                    "channels": 2
                }
            ],
            "format": {
                "format_name": "hls",
                "bit_rate": "4500000"
            }
        }
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(probe_output).encode("utf-8"),
            stderr=b""
        )

        is_healthy = self.watchdog.check_health()
        self.assertTrue(is_healthy)
        self.assertEqual(len(self.watchdog.last_probe_data.get("streams", [])), 2)

    @patch("subprocess.run")
    def test_watchdog_probe_missing_video(self, mock_run):
        """Test probing returns false when only audio streams exist."""
        probe_output = {
            "streams": [
                {
                    "index": 0,
                    "codec_name": "aac",
                    "codec_type": "audio"
                }
            ]
        }
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(probe_output).encode("utf-8"),
            stderr=b""
        )

        is_healthy = self.watchdog.check_health()
        self.assertFalse(is_healthy)

    @patch("subprocess.run")
    def test_watchdog_probe_process_failure_or_timeout(self, mock_run):
        """Test probing returns false when ffprobe exits with non-zero code or times out."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=b"",
            stderr=b"Connection refused"
        )
        self.assertFalse(self.watchdog.check_health())

        mock_run.side_effect = Exception("Subprocess timed out")
        self.assertFalse(self.watchdog.check_health())

    @patch.object(StreamWatchdog, "notify")
    @patch.object(StreamWatchdog, "probe_stream")
    def test_consecutive_failures_and_alert_trigger(self, mock_probe, mock_notify):
        """Test that consecutive failures increment and trigger alert at threshold."""
        mock_probe.return_value = (False, {})

        # Tick 1: Failure 1
        res1 = self.watchdog.tick()
        self.assertEqual(res1["consecutive_failures"], 1)
        self.assertFalse(res1["alert_sent"])
        mock_notify.assert_not_called()

        # Tick 2: Failure 2
        res2 = self.watchdog.tick()
        self.assertEqual(res2["consecutive_failures"], 2)
        self.assertFalse(res2["alert_sent"])
        mock_notify.assert_not_called()

        # Tick 3: Failure 3 (Threshold met)
        res3 = self.watchdog.tick()
        self.assertEqual(res3["consecutive_failures"], 3)
        self.assertTrue(res3["alert_sent"])
        self.assertTrue(self.watchdog.is_failing_state)
        mock_notify.assert_called_once()

    @patch.object(StreamWatchdog, "notify")
    @patch.object(StreamWatchdog, "probe_stream")
    def test_stream_recovery(self, mock_probe, mock_notify):
        """Test that recovery notification is triggered when stream recovers from down state."""
        self.watchdog.is_failing_state = True
        self.watchdog.consecutive_failures = 4

        mock_probe.return_value = (True, {"streams": [{"codec_type": "video"}]})
        res = self.watchdog.tick()

        self.assertTrue(res["is_alive"])
        self.assertTrue(res["recovered"])
        self.assertEqual(self.watchdog.consecutive_failures, 0)
        self.assertFalse(self.watchdog.is_failing_state)
        mock_notify.assert_called_once()


class TestTemplatesAndFiltering(unittest.TestCase):
    def test_telegram_alert_template_rendering(self):
        """Verify content of critical alert template."""
        rendered = render_critical_alert_template(
            stream_url="https://live.test/ch1.m3u8",
            failure_count=3,
            threshold=3,
            timestamp="2026-10-01 12:00:00 UTC",
            error_detail="Connection timeout"
        )
        self.assertIn("CRITICAL STREAM ALERT", rendered)
        self.assertIn("https://live.test/ch1.m3u8", rendered)
        self.assertIn("Threshold: 3", rendered)
        self.assertIn("Connection timeout", rendered)

    def test_telegram_recovery_template_rendering(self):
        """Verify content of recovery template."""
        rendered = render_recovery_template(
            stream_url="https://live.test/ch1.m3u8",
            failed_checks=5,
            timestamp="2026-10-01 12:05:00 UTC"
        )
        self.assertIn("STREAM RECOVERED", rendered)
        self.assertIn("5", rendered)

    def test_telegram_digest_template_rendering(self):
        """Verify content of stream health digest template."""
        streams = [
            {"name": "Channel 1 HD", "healthy": True},
            {"name": "Channel 2 4K", "healthy": False}
        ]
        digest = render_digest_template(streams, "2026-10-01 12:00:00 UTC")
        self.assertIn("STREAM HEALTH DIGEST", digest)
        self.assertIn("Channel 1 HD", digest)
        self.assertIn("ONLINE", digest)
        self.assertIn("Channel 2 4K", digest)
        self.assertIn("FAILING", digest)

    def test_json_filtering_stream_info(self):
        """Verify JSON filtering by codec_type, resolution, and codec_name."""
        probe_data = {
            "streams": [
                {"codec_name": "h264", "codec_type": "video", "width": 1920, "height": 1080},
                {"codec_name": "hevc", "codec_type": "video", "width": 3840, "height": 2160},
                {"codec_name": "aac", "codec_type": "audio", "channels": 2}
            ]
        }
        # Filter video
        videos = filter_stream_info(probe_data, codec_type="video")
        self.assertEqual(len(videos), 2)

        # Filter min resolution 4k
        ultra_hd = filter_stream_info(probe_data, codec_type="video", min_width=3840)
        self.assertEqual(len(ultra_hd), 1)
        self.assertEqual(ultra_hd[0]["codec_name"], "hevc")

        # Filter audio
        audio = filter_stream_info(probe_data, codec_type="audio")
        self.assertEqual(len(audio), 1)

    def test_json_filtering_catalog(self):
        """Verify filtering multi-stream channel catalog."""
        catalog = [
            {"name": "News Live", "url": "rtmp://live.test/news", "healthy": True},
            {"name": "Sports 1", "url": "https://ott.test/sports.m3u8", "healthy": False},
            {"name": "Sports 2", "url": "rtsp://edge.test/sports2", "healthy": True}
        ]
        rtmp_streams = filter_streams_catalog(catalog, protocol="rtmp://")
        self.assertEqual(len(rtmp_streams), 1)
        self.assertEqual(rtmp_streams[0]["name"], "News Live")

        healthy_streams = filter_streams_catalog(catalog, healthy_only=True)
        self.assertEqual(len(healthy_streams), 2)

        sports_streams = filter_streams_catalog(catalog, keyword="sports")
        self.assertEqual(len(sports_streams), 2)

    def test_load_env_file(self):
        """Verify loading environment file without external libraries."""
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
            f.write("# Sample comment\n")
            f.write("STREAM_URL=https://sample.stream/test.m3u8\n")
            f.write("CHECK_INTERVAL=15\n")
            temp_path = Path(f.name)

        try:
            vars_loaded = load_env_file(temp_path)
            self.assertEqual(vars_loaded.get("STREAM_URL"), "https://sample.stream/test.m3u8")
            self.assertEqual(vars_loaded.get("CHECK_INTERVAL"), "15")
        finally:
            temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
