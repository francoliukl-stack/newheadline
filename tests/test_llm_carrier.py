import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.llm_carrier import (  # noqa: E402
    CarrierAttempt,
    CarrierUnavailable,
    ALL_CARRIERS,
    is_quota_exhausted,
    run_prompt,
)


def fake_runner(script):
    """Build a runner returning canned (returncode, stdout, stderr) per carrier."""
    calls = []

    def runner(carrier, prompt, timeout):
        calls.append(carrier)
        return script[carrier]

    runner.calls = calls
    return runner


class QuotaDetectionTests(unittest.TestCase):
    def test_recognises_the_real_codex_and_claude_limit_messages(self):
        self.assertTrue(is_quota_exhausted(
            "ERROR: You've hit your usage limit. Upgrade to Pro ... try again at Aug 9th, 2026 9:41 PM."
        ))
        self.assertTrue(is_quota_exhausted("Claude AI usage limit reached|1234567890"))
        self.assertTrue(is_quota_exhausted("429 Too Many Requests: rate limit exceeded"))
        self.assertTrue(is_quota_exhausted("Please run /login to authenticate"))

    def test_does_not_mistake_ordinary_model_output_for_a_quota_failure(self):
        self.assertFalse(is_quota_exhausted('{"verdict": "noise", "reason": "rate limit article"}'))
        self.assertFalse(is_quota_exhausted(""))


class CarrierFailoverTests(unittest.TestCase):
    def test_uses_the_primary_carrier_when_it_succeeds(self):
        runner = fake_runner({"codex": (0, '{"ok": true}', "")})
        result = run_prompt("p", carriers=("codex",), runner=runner)
        self.assertEqual(result.carrier, "codex")
        self.assertEqual(result.text, '{"ok": true}')
        self.assertEqual(runner.calls, ["codex"])

    def test_falls_back_to_the_next_carrier_when_the_first_is_out_of_quota(self):
        runner = fake_runner({
            "codex": (1, "", "ERROR: You've hit your usage limit. try again at Aug 9th"),
            "claude": (0, '{"ok": true}', ""),
        })
        result = run_prompt("p", carriers=("codex", "claude"), runner=runner)
        self.assertEqual(result.carrier, "claude")
        self.assertEqual(runner.calls, ["codex", "claude"])
        self.assertEqual(result.attempts[0].reason, "quota_exhausted")

    def test_reports_every_attempt_so_a_silent_downgrade_is_impossible(self):
        runner = fake_runner({
            "codex": (1, "", "usage limit"),
            "claude": (0, "text", ""),
        })
        result = run_prompt("p", carriers=("codex", "claude"), runner=runner)
        self.assertEqual([a.carrier for a in result.attempts], ["codex", "claude"])
        self.assertEqual(result.attempts[-1].status, "success")
        self.assertTrue(result.degraded)

    def test_a_non_quota_failure_still_tries_the_next_carrier_but_is_labelled_differently(self):
        runner = fake_runner({
            "codex": (1, "", "boom: unexpected crash"),
            "claude": (0, "text", ""),
        })
        result = run_prompt("p", carriers=("codex", "claude"), runner=runner)
        self.assertEqual(result.attempts[0].reason, "error")
        self.assertEqual(result.carrier, "claude")

    def test_raises_when_every_carrier_is_unavailable_rather_than_returning_empty(self):
        runner = fake_runner({
            "codex": (1, "", "usage limit"),
            "claude": (1, "", "usage limit reached"),
        })
        with self.assertRaises(CarrierUnavailable) as ctx:
            run_prompt("p", carriers=("codex", "claude"), runner=runner)
        self.assertIn("codex", str(ctx.exception))
        self.assertIn("claude", str(ctx.exception))

    def test_empty_output_counts_as_a_failure_not_a_valid_answer(self):
        runner = fake_runner({"codex": (0, "   ", ""), "claude": (0, "real", "")})
        result = run_prompt("p", carriers=("codex", "claude"), runner=runner)
        self.assertEqual(result.carrier, "claude")
        self.assertEqual(result.attempts[0].reason, "empty_output")

    def test_default_carrier_order_puts_codex_first(self):
        self.assertEqual(ALL_CARRIERS[0], "codex")
        self.assertIn("claude", ALL_CARRIERS)

    def test_attempt_records_are_serialisable_for_runlog_metadata(self):
        attempt = CarrierAttempt(carrier="codex", status="failed", reason="quota_exhausted", detail="usage limit")
        self.assertEqual(
            attempt.as_dict(),
            {"carrier": "codex", "status": "failed", "reason": "quota_exhausted", "detail": "usage limit"},
        )


if __name__ == "__main__":
    unittest.main()
