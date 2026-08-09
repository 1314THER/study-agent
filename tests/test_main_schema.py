"""FastAPI 请求模型与后端主模块冒烟测试。"""

import unittest


class AgentActRequestTest(unittest.TestCase):
    def test_request_accepts_history(self):
        from backend.main import AgentActRequest

        req = AgentActRequest(
            message="你好",
            history=[{"role": "user", "content": "上一条"}, {"role": "assistant", "content": "好的"}],
        )
        self.assertEqual(req.message, "你好")
        self.assertEqual(len(req.history), 2)
        self.assertEqual(req.history[0]["content"], "上一条")

    def test_main_module_imports(self):
        import backend.main  # noqa: F401


if __name__ == "__main__":
    unittest.main()
