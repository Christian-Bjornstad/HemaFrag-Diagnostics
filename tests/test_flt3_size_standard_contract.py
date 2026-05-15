import os
import unittest

from core.analyses.flt3.pipeline import flt3_size_standard_mode
from scripts.run_flt3_liz500_qc_all_injections import _size_standard_channel_for_path


class Flt3SizeStandardContractTests(unittest.TestCase):
    def setUp(self):
        self._old_ladder = os.environ.get("HEMAFRAG_FLT3_LADDER")
        self._old_size_standard = os.environ.get("HEMAFRAG_FLT3_SIZE_STANDARD")

    def tearDown(self):
        if self._old_ladder is None:
            os.environ.pop("HEMAFRAG_FLT3_LADDER", None)
        else:
            os.environ["HEMAFRAG_FLT3_LADDER"] = self._old_ladder
        if self._old_size_standard is None:
            os.environ.pop("HEMAFRAG_FLT3_SIZE_STANDARD", None)
        else:
            os.environ["HEMAFRAG_FLT3_SIZE_STANDARD"] = self._old_size_standard

    def test_default_rox500_mode_uses_data4_channel(self):
        os.environ.pop("HEMAFRAG_FLT3_LADDER", None)
        os.environ.pop("HEMAFRAG_FLT3_SIZE_STANDARD", None)

        mode = flt3_size_standard_mode()

        self.assertEqual(mode["size_standard"], "ROX500")
        self.assertEqual(mode["internal_ladder"], "GS500ROX")
        self.assertEqual(mode["size_standard_channel"], "DATA4")
        self.assertFalse(mode["uses_liz_sizes"])

    def test_liz500_override_uses_data105_channel(self):
        os.environ["HEMAFRAG_FLT3_LADDER"] = "LIZ500"

        mode = flt3_size_standard_mode()

        self.assertEqual(mode["size_standard"], "LIZ500_250")
        self.assertEqual(mode["internal_ladder"], "LIZ500_250")
        self.assertEqual(mode["size_standard_channel"], "DATA105")
        self.assertTrue(mode["uses_liz_sizes"])

    def test_channel_detection_preserves_requested_fallback_on_parse_failure(self):
        os.environ.pop("HEMAFRAG_FLT3_LADDER", None)
        os.environ.pop("HEMAFRAG_FLT3_SIZE_STANDARD", None)

        channel = _size_standard_channel_for_path(
            __file__,
            fallback=str(flt3_size_standard_mode()["size_standard_channel"]),
        )

        self.assertEqual(channel, "DATA4")


if __name__ == "__main__":
    unittest.main()
