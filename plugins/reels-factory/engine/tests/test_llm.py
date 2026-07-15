import pytest
from reels_factory.llm import FakeRunner, ClaudeCliRunner


def test_fake_runner_отдаёт_по_очереди_и_копит_промпты():
    r = FakeRunner(["a", "b"])
    assert r.run("p1") == "a"
    assert r.run("p2") == "b"
    assert r.prompts == ["p1", "p2"]


@pytest.mark.slow
def test_claude_cli_живой_вызов():
    r = ClaudeCliRunner(timeout_s=120)
    out = r.run("Ответь ровно одним словом без знаков препинания: пингвин")
    assert "пингвин" in out.lower()
