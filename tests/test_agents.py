"""Background agents: at most N at once, the rest queued; steps in words; results, pictures and questions handed
back; stop; and the flow chart / cards the tab draws. Fake processes stand in for Claude Code."""
import json
import queue
import threading
import time

import agents as ag
import panel_steps as ps


class FakeProc:
    """Streams the given events, but only after `gate` is set - so a test can hold agents 'running'."""
    def __init__(self, events, gate):
        self.events, self.gate, self.killed, self.pid = events, gate, False, 1

    @property
    def stdout(self):
        self.gate.wait(5)
        for e in self.events:
            if self.killed:
                return
            yield json.dumps(e) + "\n"

    def poll(self):
        return None

    def kill(self):
        self.killed = True
        self.gate.set()


def run_events(text, ok=True):
    return [{"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "python swx.py run b.py --background"}}]}},
            {"type": "result", "is_error": not ok, "result": text, "usage": {"output_tokens": 10}}]


def drain(q, until, timeout=5):
    seen, t0 = [], time.time()
    while time.time() - t0 < timeout:
        try:
            k, p = q.get(timeout=0.1)
        except queue.Empty:
            continue
        seen.append((k, p))
        if until(k, p):
            break
    return seen


def test_only_max_parallel_run_and_the_queue_follows():
    q, gates, started = queue.Queue(), {}, []

    def launch(a):
        started.append(a.name)
        gates[a.name] = threading.Event()
        return FakeProc(run_events(f"{a.name} built. [[IMAGE C:/w/{a.name}.png]]"), gates[a.name])
    m = ag.AgentManager(launch, q, max_parallel=2, lang="en")
    for n in ("base", "lid", "hinge", "clip"):
        m.add(n, f"build the {n}")
    assert started == ["base", "lid"] and len(m.running()) == 2
    assert [a.state for a in m.agents] == ["running", "running", "queued", "queued"]
    gates["base"].set()
    drain(q, lambda k, p: k == "agent" and p["name"] == "base" and p["state"] == "done")
    time.sleep(0.1)
    assert started == ["base", "lid", "hinge"]                       # a slot freed -> the next one starts
    for n in ("lid", "hinge"):
        gates[n].set()
    time.sleep(0.3)
    gates["clip"].set()
    seen = drain(q, lambda k, p: k == "agents_done")
    done = [p for k, p in seen if k == "agents_done"][0]
    assert [a["state"] for a in done] == ["done"] * 4
    assert done[0]["images"] == ["C:/w/base.png"] and "[[IMAGE" not in done[0]["text"]
    assert done[0]["steps"] == ["Working in SolidWorks"]


def test_failure_need_and_report():
    q, gate = queue.Queue(), threading.Event()
    gate.set()
    m = ag.AgentManager(lambda a: FakeProc(run_events("Missing the pipe size. [[NEED]] Pipe diameter?", ok=False),
                                           gate), q, lang="en")
    m.add("bracket", "build it")
    done = [p for k, p in drain(q, lambda k, p: k == "agents_done") if k == "agents_done"][0]
    a = done[0]
    assert a["state"] == "failed" and a["need"] == "Pipe diameter?" and "[[NEED]]" not in a["text"]
    msg = ag.results_message(done, "en")
    assert "NEEDS THE USER: Pipe diameter?" in msg and "## bracket (failed" in msg


def test_launch_error_is_a_failed_agent_not_a_crash():
    q = queue.Queue()

    def boom(a):
        raise OSError("claude.exe not found")
    m = ag.AgentManager(boom, q)
    m.add("x", "y")
    assert m.agents[0].state == "failed" and "not found" in m.agents[0].text


def test_stop_all():
    q, gates = queue.Queue(), {}

    def launch(a):
        gates[a.name] = threading.Event()
        return FakeProc(run_events("never"), gates[a.name])
    m = ag.AgentManager(launch, q, max_parallel=1)
    m.add("a", "t")
    m.add("b", "t")
    m.stop_all()
    assert [a.state for a in m.agents] == ["stopped", "stopped"] and not m.active()


def test_flow_and_cards_render():
    rows = [{"id": "a1", "name": "base plate", "state": "done", "step": "", "s": 41.2, "images": ["C:\\w\\b.png"]},
            {"id": "a2", "name": "hinge", "state": "running", "step": "Working in SolidWorks", "s": 12, "images": []},
            {"id": "a3", "name": "a very long agent name here", "state": "queued", "step": "", "s": 0, "images": []}]
    svg = ag.flow_svg(rows, "he")
    assert svg.startswith("<svg") and svg.count("<rect") == 5 and "ראשי" in svg and "איחוד" in svg
    assert "#34d399" in svg and "#38c8f0" in svg and "…" in svg
    card = ag.agent_card(rows[1], "en")
    assert "Working in SolidWorks" in card and "pulse" in card and "act('agent:a2')" in card
    assert 'src="file:///C:/w/b.png"' in ag.agent_card(rows[0], "en")
    assert "<script" not in ag.agent_card(dict(rows[2], name="<script>x</script>"), "en")


def test_reply_markers_for_agents_and_images():
    text, items = ps.parse_agents("Splitting it:\n[[AGENT base]] Build a 120x80x6 plate\n[[AGENT lid]] Build the lid")
    assert text == "Splitting it:" and items == [("base", "Build a 120x80x6 plate"), ("lid", "Build the lid")]
    t, imgs = ps.parse_images('Done.\n[[IMAGE "C:/out/a.png"]]')
    assert t == "Done." and imgs == ["C:/out/a.png"]
