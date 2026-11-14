import asyncio
import json
import pathlib
import shutil
import tempfile

import pytest
import websockets
from mcp.server.mcpserver.exceptions import ToolError

from reflets import bridge as bridge_module
from reflets import server
from reflets.bridge import PROTO, Bridge, BridgeError


class Plugin:
    def __init__(self, unanswered=()):
        self.received = []
        self.unanswered = list(unanswered)
        self.open = set()

    async def __call__(self, socket):
        self.open.add(socket)
        try:
            async for text in socket:
                rid, verb = text.split(" ")[:2]
                self.received.append(verb)
                if verb == "hello":
                    await socket.send(f"{rid} ok proto={PROTO}")
                elif verb in self.unanswered:
                    self.unanswered.remove(verb)
                else:
                    await socket.send(f"{rid} ok\nanswer to {verb}")
        finally:
            self.open.discard(socket)


def run(plugin, tmp_path: pathlib.Path, scene):
    async def main():
        async with websockets.serve(plugin, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            token = tmp_path / "token.txt"
            token.write_text("secret")
            return await scene(Bridge(port, token))

    return asyncio.run(main())


@pytest.fixture(autouse=True)
def short_wait(monkeypatch):
    monkeypatch.setattr(bridge_module, "TIMEOUT", 0.2)


@pytest.mark.parametrize("line", ["write 0 480 idea\nv 0 0", "color 0 480 0 #000000 keep idea", "undo", "redo"])
def test_a_change_with_no_answer_is_sent_once_and_reported(tmp_path, line):
    verb = line.split(" ")[0].split("\n")[0]
    plugin = Plugin(unanswered=[verb])

    async def scene(bridge):
        with pytest.raises(BridgeError, match="did not answer"):
            await bridge.request(line)

    run(plugin, tmp_path, scene)
    assert plugin.received.count(verb) == 1


def test_a_read_with_no_answer_is_asked_again(tmp_path):
    plugin = Plugin(unanswered=["read"])

    async def scene(bridge):
        return await bridge.request("read 0 480")

    _, lines = run(plugin, tmp_path, scene)
    assert lines == ["answer to read"]
    assert plugin.received.count("read") == 2


def test_a_change_goes_through_a_connection_that_closed_while_idle(tmp_path):
    plugin = Plugin()

    async def scene(bridge):
        await bridge.request("info")
        for socket in list(plugin.open):
            await socket.close()
        await asyncio.sleep(0.05)
        return await bridge.request("write 0 480 idea\nv 0 0")

    _, lines = run(plugin, tmp_path, scene)
    assert lines == ["answer to write"]
    assert plugin.received.count("write") == 1


def test_a_dropped_connection_is_closed(tmp_path):
    plugin = Plugin(unanswered=["read"])

    async def scene(bridge):
        await bridge.request("read 0 480")
        await asyncio.sleep(0.05)
        return len(plugin.open)

    assert run(plugin, tmp_path, scene) == 1


CHORALE = json.loads((pathlib.Path(__file__).parent / "data" / "reading" / "chorale.json").read_text())
INFO = [line for line in CHORALE["info"] if not line.startswith("L ")]
SOPRANO_IDEA = "N1x div=2 ts=4/4 ks=3s\nm2 len=8\n1.1: 1 A4 B4 2 G#4 F#4[fermata] A4"


def tick(line):
    return int(line.split(" ")[1])


def soprano(line, start):
    return line.startswith("C ") and line.split(" ")[2] == "0" and start <= tick(line) < start + 1920


def with_bar_3_soprano_in_bar_2(lines):
    kept = [line for line in lines if not soprano(line, 2400)]
    moved = [" ".join([words[0], str(int(words[1]) - 1920), *words[2:]]) for words in (line.split(" ") for line in lines if soprano(line, 4320))]
    return kept + moved


class Score:
    def __init__(self, lines):
        self.lines = list(lines)
        self.done, self.undone = [], []
        self.writes = []
        self.info = INFO
        self.verbs = []
        self.replies = {}

    def read(self, start, end):
        return [line for line in self.lines if start <= tick(line) < end]

    async def __call__(self, socket):
        async for text in socket:
            rid, verb, *words = text.split("\n")[0].split(" ")
            body = []
            self.verbs.append(verb)
            if verb == "hello":
                words = [f"proto={PROTO}", f"division={CHORALE['division']}"]
            elif verb == "info":
                body = self.info
            elif verb == "read":
                body = self.read(int(words[0]), int(words[1]))
            elif verb == "write":
                after, answered, *info = self.writes.pop(0) if self.writes else (self.lines, True)
                self.info = info[0] if info else self.info
                if after is not None:
                    self.done.append(self.lines)
                    self.lines = after
                if not answered:
                    continue
                body = self.read(int(words[0]), int(words[1]))
            elif verb == "undo":
                self.undone.append(self.lines)
                self.lines = self.done.pop()
            elif verb == "redo":
                self.done.append(self.lines)
                self.lines = self.undone.pop()
            elif verb == "export":
                shutil.copyfile(pathlib.Path(__file__).parent / "data" / "bwv66.6.musicxml", " ".join(words))
            if (verb, self.verbs.count(verb)) in self.replies:
                if reply := self.replies[verb, self.verbs.count(verb)]:
                    await socket.send(f"{rid} {reply}")
                continue
            head = " ".join([rid, "ok", *words]) if verb == "hello" else f"{rid} ok"
            await socket.send("\n".join([head, *body]))


def served(tmp_path, monkeypatch, score, scene):
    async def main():
        async with websockets.serve(score, "127.0.0.1", 0) as listening:
            token = tmp_path / "reflets-token.txt"
            token.write_text("secret")
            monkeypatch.setenv("REFLETS_TOKEN_FILE", str(token))
            monkeypatch.setenv("REFLETS_PORT", str(listening.sockets[0].getsockname()[1]))
            return await scene()

    return asyncio.run(main())


def test_an_answered_write_is_open_and_discard_removes_it(tmp_path, monkeypatch):
    score = Score(CHORALE["read"])
    changed = with_bar_3_soprano_in_bar_2(CHORALE["read"])
    score.writes = [(changed, True)]

    async def scene():
        written = await server.propose(SOPRANO_IDEA, replace=True)
        assert "Read-back matched" in written
        return await server.discard("p1")

    assert served(tmp_path, monkeypatch, score, scene).startswith("Discarded p1")
    assert score.lines == CHORALE["read"]


def test_a_write_that_landed_with_no_answer_is_open_at_the_next_call(tmp_path, monkeypatch):
    score = Score(CHORALE["read"])
    score.writes = [(with_bar_3_soprano_in_bar_2(CHORALE["read"]), False)]

    async def scene():
        with pytest.raises(ToolError, match="p1"):
            await server.propose(SOPRANO_IDEA, replace=True)
        return await server.discard("p1")

    assert "Discarded p1" in served(tmp_path, monkeypatch, score, scene)
    assert sorted(score.lines) == sorted(CHORALE["read"])


def test_a_write_that_never_landed_leaves_nothing_and_the_next_propose_works(tmp_path, monkeypatch):
    score = Score(CHORALE["read"])
    changed = with_bar_3_soprano_in_bar_2(CHORALE["read"])
    score.writes = [(None, False), (changed, True)]

    async def scene():
        with pytest.raises(ToolError, match="p1"):
            await server.propose(SOPRANO_IDEA, replace=True)
        return await server.propose(SOPRANO_IDEA, replace=True)

    written = served(tmp_path, monkeypatch, score, scene)
    assert "p1 never reached the score" in written
    assert "proposal id: p2" in written
    assert score.lines == changed
    assert list(server.stored()["open"]) == ["p2"]


def test_bars_that_match_neither_state_are_named_and_left_alone(tmp_path, monkeypatch):
    score = Score(CHORALE["read"])
    score.writes = [(with_bar_3_soprano_in_bar_2(CHORALE["read"]), False)]

    async def scene():
        with pytest.raises(ToolError, match="p1"):
            await server.propose(SOPRANO_IDEA, replace=True)
        score.lines = [line for line in score.lines if not (line.startswith("C 2400 4 "))]
        edited = list(score.lines)
        with pytest.raises(ToolError, match="bar 2") as refused:
            await server.discard("p1")
        assert score.lines == edited
        return str(refused.value)

    assert "neither" in served(tmp_path, monkeypatch, score, scene)
    assert server.stored()["open"] == {}


def test_a_restore_whose_second_write_landed_with_no_answer_is_open_at_the_next_call(tmp_path, monkeypatch):
    fermata = "A 3360 0 Fermata fermataAbove "
    changed = with_bar_3_soprano_in_bar_2(CHORALE["read"])
    checkpoint = [line for line in CHORALE["read"] if line != fermata]
    score = Score(changed)
    score.writes = [([line for line in changed if line != fermata], True), (checkpoint, False)]

    async def scene():
        folder = server.checkpoint_folder("bwv66.6.musicxml")
        folder.mkdir(parents=True)
        (folder / "001 before.json").write_text(json.dumps({"name": "before", "saved": "2026-11-13 10:00", "info": INFO, "read": checkpoint}))
        with pytest.raises(ToolError, match="p1, its first step") as lost:
            await server.restore(1, "2")
        assert "nothing changed" not in str(lost.value)
        assert "Discarded p2" in await server.discard("p2")
        return await server.discard("p1")

    assert "Discarded p1" in served(tmp_path, monkeypatch, score, scene)
    assert sorted(score.lines) == sorted(changed)


def test_a_refused_call_still_says_what_became_of_the_unanswered_write(tmp_path, monkeypatch):
    score = Score(CHORALE["read"])
    score.writes = [(with_bar_3_soprano_in_bar_2(CHORALE["read"]), False)]

    async def scene():
        with pytest.raises(ToolError, match="p1"):
            await server.propose(SOPRANO_IDEA, replace=True)
        with pytest.raises(ToolError) as refused:
            await server.propose(SOPRANO_IDEA)
        return str(refused.value)

    refusal = served(tmp_path, monkeypatch, score, scene)
    assert "p1, whose write MuseScore did not answer, did land" in refusal
    assert "already have notes" in refusal
    assert list(server.stored()["open"]) == ["p1"]


def test_after_a_restart_bars_that_changed_are_named_and_left_alone(tmp_path, monkeypatch):
    score = Score(CHORALE["read"])
    changed = with_bar_3_soprano_in_bar_2(CHORALE["read"])
    score.writes = [(changed, False)]

    async def scene():
        with pytest.raises(ToolError, match="p1"):
            await server.propose(SOPRANO_IDEA, replace=True)
        server.written_checks.clear()
        with pytest.raises(ToolError, match="server restarted") as refused:
            await server.keep("p1")
        return str(refused.value)

    assert "bar 2" in served(tmp_path, monkeypatch, score, scene)
    assert score.lines == changed
    assert server.stored()["open"] == {}


def test_score_info_lists_the_open_ideas_of_the_open_score(tmp_path, monkeypatch):
    score = Score(CHORALE["read"])
    score.writes = [(with_bar_3_soprano_in_bar_2(CHORALE["read"]), True)]

    async def scene():
        await server.propose(SOPRANO_IDEA, "soprano", replace=True)
        data = server.stored()
        data["open"]["p9"] = {**data["open"]["p1"], "title": "Another score"}
        server.proposals_file().write_text(json.dumps(data))
        return await server.score_info()

    report = served(tmp_path, monkeypatch, score, scene)
    assert 'Open ideas in "bwv66.6.musicxml", not yet kept or discarded: p1 "soprano", bar 2.' in report
    assert "p9" not in report


def test_render_shows_the_bars_as_an_image_and_names_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    async def scene():
        return await server.mcp.call_tool("render", {"bars": "1-2"})

    result = served(tmp_path, monkeypatch, Score(CHORALE["read"]), scene)
    text, image = result.content
    assert text.type == "text" and text.text.startswith("Bars 1-2: ") and text.text.endswith(".png")
    assert image.type == "image" and image.mime_type == "image/png"
    assert pathlib.Path(text.text.removeprefix("Bars 1-2: ")).exists()


def test_score_info_leaves_out_an_idea_undone_in_musescore_or_stale_and_answers_with_an_unreadable_proposals_file(tmp_path, monkeypatch):
    score = Score(CHORALE["read"])
    score.writes = [(with_bar_3_soprano_in_bar_2(CHORALE["read"]), True)]

    async def scene():
        await server.propose(SOPRANO_IDEA, "soprano", replace=True)
        score.lines = list(CHORALE["read"])
        undone = await server.score_info()
        score.lines = with_bar_3_soprano_in_bar_2(CHORALE["read"])
        data = server.stored()
        data["open"]["p7"] = {**data["open"]["p1"], "label": "stale", "pre": ["C 1920 0 1/4 1:1:1"], "post": ["C 1920 0 1/4 2:2:2"]}
        server.proposals_file().write_text(json.dumps(data))
        stale = await server.score_info()
        server.proposals_file().write_text("{")
        return undone, stale, await server.score_info()

    undone, stale, unreadable = served(tmp_path, monkeypatch, score, scene)
    assert "Open ideas" not in undone
    assert 'p1 "soprano"' in stale and "p7" not in stale
    assert "connected" in unreadable and "Open ideas" not in unreadable


BAR_7_FERMATA = "A 12960 0 Fermata fermataAbove "
BAR_5_IDEA = "N1x div=2 ts=4/4 ks=3s\nm5 len=8\n1.1: 2 A4 B4 C#5[fermata] A4"


def soprano_of(lines, source, target):
    kept = [line for line in lines if not soprano(line, target)]
    return kept + [" ".join([words[0], str(int(words[1]) - source + target), *words[2:]]) for words in (line.split(" ") for line in lines if soprano(line, source))]


def unfermata(lines, at):
    return [line for line in lines if line != f"A {at} 0 Fermata fermataAbove "]


def without_bar_7_fermata(lines):
    return [line for line in lines if line != BAR_7_FERMATA]


def edited_after(score):
    score.done.append(score.lines)
    score.lines = without_bar_7_fermata(score.lines)


def test_discard_of_the_last_step_undoes_it(tmp_path, monkeypatch):
    score = Score(CHORALE["read"])
    score.writes = [(with_bar_3_soprano_in_bar_2(CHORALE["read"]), True)]

    async def scene():
        await server.propose(SOPRANO_IDEA, replace=True)
        return await server.discard("p1")

    assert served(tmp_path, monkeypatch, score, scene) == "Discarded p1: the score is back as it was in bar 2."
    assert score.verbs.count("undo") == 1 and score.verbs.count("write") == 1 and "color" not in score.verbs


def test_discard_after_an_edit_elsewhere_writes_the_bars_back_in_black(tmp_path, monkeypatch):
    score = Score(CHORALE["read"])
    first = with_bar_3_soprano_in_bar_2(CHORALE["read"])
    score.writes = [(first, True), (unfermata(without_bar_7_fermata(first), 3360), True), (without_bar_7_fermata(CHORALE["read"]), True)]

    async def scene():
        await server.propose(SOPRANO_IDEA, "soprano", replace=True)
        edited_after(score)
        return await server.discard("p1")

    result = served(tmp_path, monkeypatch, score, scene)
    assert result.startswith("Discarded p1: the score is back as it was in bar 2, in black.")
    assert 'in 3 undo steps "Reflets: discard soprano"' in result
    assert score.lines == without_bar_7_fermata(CHORALE["read"])
    assert score.verbs[-1] == "color" and score.verbs.count("write") == 3
    assert server.stored()["open"] == {}


def test_discarding_an_older_idea_leaves_the_later_one_open_without_undoing(tmp_path, monkeypatch):
    first = with_bar_3_soprano_in_bar_2(CHORALE["read"])
    both = soprano_of(first, 10080, 8160)
    second = soprano_of(CHORALE["read"], 10080, 8160)
    score = Score(CHORALE["read"])
    score.writes = [(first, True), (both, True), (unfermata(both, 3360), True), (second, True), (unfermata(second, 9120), True), (CHORALE["read"], True)]

    async def scene():
        await server.propose(SOPRANO_IDEA, "A", replace=True)
        await server.propose(BAR_5_IDEA, "B", replace=True)
        older = await server.discard("p1")
        assert "undo" not in score.verbs
        assert score.lines == second and list(server.stored()["open"]) == ["p2"]
        return older, await server.discard("p2")

    older, later = served(tmp_path, monkeypatch, score, scene)
    assert "Discarded p1" in older and "Discarded p2" in later
    assert score.lines == CHORALE["read"] and server.stored()["open"] == {}


def test_discard_of_bars_the_user_edited_since_is_refused(tmp_path, monkeypatch):
    score = Score(CHORALE["read"])
    score.writes = [(with_bar_3_soprano_in_bar_2(CHORALE["read"]), True)]

    async def scene():
        await server.propose(SOPRANO_IDEA, replace=True)
        score.done.append(score.lines)
        score.lines = [line for line in score.lines if line != "A 3360 0 Fermata fermataAbove "]
        edited = list(score.lines)
        with pytest.raises(ToolError, match="changed since p1 was written") as refused:
            await server.discard("p1")
        assert score.lines == edited and "write" not in score.verbs[-3:]
        return str(refused.value)

    served(tmp_path, monkeypatch, score, scene)
    assert list(server.stored()["open"]) == ["p1"]


def info_with(extra, after="M 1 0 2400 4/4 4/4 0 0 2"):
    at = INFO.index(after) + 1
    return INFO[:at] + extra + INFO[at:]


GLISSANDO = [line.replace("C 2400 4 1/8 B2 64:18:18", "C 2400 4 1/8 B2 64:18:18:g0") for line in CHORALE["read"]]
TIED = [line.replace("C 1920 0 1/4 S2 76:18:18", "C 1920 0 1/4 S2 73:21:21:f").replace("C 2400 0 1/4 S2 73:21:21", "C 2400 0 1/4 S2 73:21:21:b") for line in CHORALE["read"]]
UNTIED = [line.replace("73:21:21:f", "73:21:21") for line in with_bar_3_soprano_in_bar_2(TIED)]


@pytest.mark.parametrize("base, post, change, reason", [
    (CHORALE["read"], with_bar_3_soprano_in_bar_2(CHORALE["read"]), lambda score: setattr(score, "info", [line.replace("M 1 0 2400 4/4 4/4", "M 1 0 2400 3/4 3/4") for line in INFO]), "the meter of bar 2"),
    (CHORALE["read"], with_bar_3_soprano_in_bar_2(CHORALE["read"]), lambda score: setattr(score, "info", info_with(["K 2400 0 2"])), "the key of bar 2"),
    (CHORALE["read"], with_bar_3_soprano_in_bar_2(CHORALE["read"]), lambda score: setattr(score, "info", info_with(["B 2400 33"])), "the bar lines, repeats, voltas"),
    (CHORALE["read"], with_bar_3_soprano_in_bar_2(CHORALE["read"]), lambda score: setattr(score, "info", [line.replace("M 1 0 2400 4/4 4/4 0 0 2", "M 1 0 2400 4/4 4/4 0 1 2") for line in INFO]), "the bar lines, repeats, voltas"),
    (CHORALE["read"], with_bar_3_soprano_in_bar_2(CHORALE["read"]), lambda score: server.proposals_file().write_text(json.dumps({**server.stored(), "open": {"p1": {**server.stored()["open"]["p1"], "fields": None}}})), "did not note"),
    (TIED, UNTIED, lambda score: None, "cut a tie from the bar before"),
    (GLISSANDO, with_bar_3_soprano_in_bar_2(GLISSANDO), lambda score: None, "glissandos"),
])
def test_a_discard_that_cannot_write_the_bars_back_is_refused_by_name(tmp_path, monkeypatch, base, post, change, reason):
    score = Score(base)
    score.writes = [(post, True)]

    async def scene():
        await server.propose(SOPRANO_IDEA, replace=True)
        change(score)
        edited_after(score)
        edited = list(score.lines)
        with pytest.raises(ToolError, match="not the last step") as refused:
            await server.discard("p1")
        assert score.lines == edited and score.verbs.count("write") == 1
        return str(refused.value)

    refusal = served(tmp_path, monkeypatch, score, scene)
    assert reason in refusal and "Nothing changed" in refusal and "p1 stays open" in refusal
    assert list(server.stored()["open"]) == ["p1"]


def test_a_discard_of_appended_bars_after_another_step_is_refused(tmp_path, monkeypatch):
    score = Score(CHORALE["read"])
    appended = [line for line in INFO if line != "B 15840 32"] + ["M 9 0 17760 4/4 4/4 0 0 2"]
    post = CHORALE["read"] + ["C 17760 0 1/1 69:17:17", "R 17760 4 1/1", "R 17760 8 1/1", "R 17760 12 1/1"]
    score.writes = [(post, True, appended)]

    async def scene():
        await server.propose("N1x div=2 ts=4/4 ks=3s\nm10 len=8\n1.1: 8 A4")
        edited_after(score)
        with pytest.raises(ToolError, match="added bars at the end") as refused:
            await server.discard("p1")
        return str(refused.value)

    assert "Nothing changed" in served(tmp_path, monkeypatch, score, scene)
    assert list(server.stored()["open"]) == ["p1"]


def test_a_write_back_that_does_not_read_back_as_before_is_undone(tmp_path, monkeypatch):
    first = with_bar_3_soprano_in_bar_2(CHORALE["read"])
    score = Score(CHORALE["read"])
    wrong = [line.replace("C 2400 0 1/4 S2 73:21:21", "C 2400 0 1/4 S1 73:21:21") for line in without_bar_7_fermata(CHORALE["read"])]
    score.writes = [(first, True), (unfermata(without_bar_7_fermata(first), 3360), True), (wrong, True)]

    async def scene():
        await server.propose(SOPRANO_IDEA, replace=True)
        edited_after(score)
        with pytest.raises(ToolError) as refused:
            await server.discard("p1")
        return str(refused.value)

    refusal = served(tmp_path, monkeypatch, score, scene)
    assert "did not read back as they were before it, so the write was undone. p1 stays open" in refusal
    assert score.lines == without_bar_7_fermata(first) and "color" not in score.verbs
    assert list(server.stored()["open"]) == ["p1"]


CLEARED = unfermata(without_bar_7_fermata(with_bar_3_soprano_in_bar_2(CHORALE["read"])), 3360)


def test_a_keep_the_plugin_could_not_colour_leaves_the_idea_open(tmp_path, monkeypatch):
    score = Score(CHORALE["read"])
    score.writes = [(with_bar_3_soprano_in_bar_2(CHORALE["read"]), True)]
    score.replies = {("color", 1): "err color-failed TypeError: no stem"}

    async def scene():
        await server.propose(SOPRANO_IDEA, replace=True)
        with pytest.raises(ToolError) as failed:
            await server.keep("p1")
        assert list(server.stored()["open"]) == ["p1"]
        return str(failed.value), await server.keep("p1")

    failed, kept = served(tmp_path, monkeypatch, score, scene)
    assert "could not turn the notes of p1 black" in failed and "color-failed: TypeError: no stem" in failed and "p1 stays open" in failed
    assert kept.startswith("Kept p1") and server.stored()["open"] == {}


def test_a_write_back_whose_first_step_landed_with_no_answer_names_it_to_discard_first(tmp_path, monkeypatch):
    first = with_bar_3_soprano_in_bar_2(CHORALE["read"])
    score = Score(CHORALE["read"])
    score.writes = [(first, True), (CLEARED, False), (CLEARED, True), (without_bar_7_fermata(CHORALE["read"]), True)]

    async def scene():
        await server.propose(SOPRANO_IDEA, replace=True)
        edited_after(score)
        with pytest.raises(ToolError) as lost:
            await server.discard("p1")
        assert sorted(server.stored()["open"]) == ["p1", "p2"]
        step = await server.discard("p2")
        return str(lost.value), step, await server.discard("p1")

    lost, step, result = served(tmp_path, monkeypatch, score, scene)
    assert "recorded as p2" in lost and 'p1 stays open. Call discard("p2"), then discard("p1") again' in lost
    assert "p2, whose write MuseScore did not answer, did land" in step and "Discarded p2" in step
    assert result.startswith("Discarded p1: the score is back as it was in bar 2, in black.")
    assert score.lines == without_bar_7_fermata(CHORALE["read"]) and server.stored()["open"] == {}


def test_a_write_back_undone_with_no_answer_leaves_its_steps_open_newest_first(tmp_path, monkeypatch):
    first = with_bar_3_soprano_in_bar_2(CHORALE["read"])
    wrong = [line.replace("C 2400 0 1/4 S2 73:21:21", "C 2400 0 1/4 S1 73:21:21") for line in without_bar_7_fermata(CHORALE["read"])]
    score = Score(CHORALE["read"])
    score.writes = [(first, True), (CLEARED, True), (wrong, True)]
    score.replies = {("undo", 2): None}

    async def scene():
        await server.propose(SOPRANO_IDEA, replace=True)
        edited_after(score)
        with pytest.raises(ToolError) as lost:
            await server.discard("p1")
        assert sorted(server.stored()["open"]) == ["p1", "p2", "p3"]
        return str(lost.value), await server.discard("p3"), await server.discard("p2")

    lost, last, cleared = served(tmp_path, monkeypatch, score, scene)
    assert "did not answer the undo" in lost and 'Call discard("p3"), then discard("p2"), then discard("p1") again' in lost
    assert "p3 is no longer in the score" in last and "Discarded p2" in cleared
    assert score.lines == without_bar_7_fermata(first) and list(server.stored()["open"]) == ["p1"]


@pytest.mark.parametrize("reply, said", [(None, "did not answer the recolouring"), ("err color-failed TypeError: no stem", "could not recolour them")])
def test_a_write_back_whose_colouring_failed_leaves_one_idea_open_for_keep(tmp_path, monkeypatch, reply, said):
    first = with_bar_3_soprano_in_bar_2(CHORALE["read"])
    score = Score(CHORALE["read"])
    score.writes = [(first, True), (CLEARED, True), (without_bar_7_fermata(CHORALE["read"]), True)]
    score.replies = {("color", 1): reply}

    async def scene():
        await server.propose(SOPRANO_IDEA, "soprano", replace=True)
        edited_after(score)
        with pytest.raises(ToolError) as failed:
            await server.discard("p1")
        assert list(server.stored()["open"]) == ["p4"]
        return str(failed.value), await server.keep("p4")

    failed, kept = served(tmp_path, monkeypatch, score, scene)
    assert failed.startswith("Discarded p1: the score is back as it was in bar 2, but MuseScore") and said in failed and 'keep("p4") turns them black; do not discard p4' in failed
    assert kept.startswith("Kept p4") and server.stored()["open"] == {}
    assert score.lines == without_bar_7_fermata(CHORALE["read"]) and score.verbs.count("color") == 2
