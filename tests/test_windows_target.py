from realtime_voice_typing.windows_target import TargetTracker


class FakeApi:
    def __init__(self):
        self.foreground = 0
        self.pid_map = {}
        self.valid = set()
        self.own_pid = 1234

    def get_foreground_window(self):
        return self.foreground

    def get_window_pid(self, hwnd):
        return self.pid_map.get(hwnd, self.own_pid)

    def is_window(self, hwnd):
        return hwnd in self.valid

    def set_foreground_window(self, hwnd):
        self.foreground = hwnd


def test_ignores_own_window_and_tracks_external():
    api = FakeApi()
    api.pid_map = {10: 999, 20: 1234}
    api.valid = {10, 20}
    tracker = TargetTracker(api=api)

    api.foreground = 20  # own window
    assert tracker.observe_foreground() is None

    api.foreground = 10  # external window
    assert tracker.observe_foreground() == 10

    api.foreground = 20  # back to own window: keep last external
    tracker.observe_foreground()
    assert tracker.resolve_last_focus() == 10


def test_resolve_last_focus_returns_none_initially():
    api = FakeApi()
    tracker = TargetTracker(api=api)
    assert tracker.resolve_last_focus() is None


def test_focus_for_insert_sets_foreground():
    api = FakeApi()
    api.valid = {42}
    tracker = TargetTracker(api=api)
    assert tracker.focus_for_insert(42) is True
    assert api.foreground == 42


def test_resolve_target_follow_cursor():
    api = FakeApi()
    api.pid_map = {10: 999, 20: 1234}
    api.valid = {10, 20}
    tracker = TargetTracker(api=api)

    # own window foreground, nothing seen yet -> None
    api.foreground = 20
    assert tracker.resolve_target("follow_cursor") is None

    # external foreground -> return it directly
    api.foreground = 10
    tracker.observe_foreground()
    assert tracker.resolve_target("follow_cursor") == 10

    # own window foreground -> fall back to last external
    api.foreground = 20
    assert tracker.resolve_target("follow_cursor") == 10

    # last_focus mode -> always last external
    assert tracker.resolve_target("last_focus") == 10
