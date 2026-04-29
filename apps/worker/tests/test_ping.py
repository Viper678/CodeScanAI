from worker.tasks.ping import ping


def test_ping_task_returns_pong() -> None:
    assert ping.run() == "pong"
