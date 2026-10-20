import unittest
import studio


class RealismControls(unittest.TestCase):
    def test_strength_is_independent_of_prompt(self):
        base = dict(prompt="自然光下的人物轻轻抬眼", realism=True)
        a, _ = studio.build_h3_creator_data(dict(base, realism_strength=0), "a")
        b, _ = studio.build_h3_creator_data(dict(base, realism_strength=0.2), "b")
        self.assertEqual(a["segments"][0]["prompt"], b["segments"][0]["prompt"])
        self.assertEqual(a["loras"], [])
        self.assertEqual(b["loras"][0]["strength"], 0.2)
        self.assertFalse(a["face"]["on"])

    def test_disabled_and_invalid(self):
        a, _ = studio.build_h3_creator_data(dict(prompt="测试", realism=False, realism_strength=0.2), "a")
        self.assertEqual(a["loras"], [])
        for value in (-1, 0.7, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                studio.build_h3_creator_data(dict(prompt="测试", realism_strength=value), "a")


if __name__ == "__main__":
    unittest.main()
