from __future__ import annotations

import utils.auth as auth


class FakeStreamlit:
    def __init__(self) -> None:
        self.session_state = {}


def test_authenticated_session_times_out_after_configured_inactivity(monkeypatch):
    fake_st = FakeStreamlit()
    fake_st.session_state.update(
        {
            "authenticated": True,
            "authenticated_username": "owner",
            "session_timeout_minutes": 15,
            "_last_activity_time": 1_000.0,
        }
    )
    monkeypatch.setattr(auth, "st", fake_st)
    monkeypatch.setattr(auth.time, "time", lambda: 1_901.0)

    assert auth.is_authenticated() is False
    assert fake_st.session_state["authenticated"] is False
    assert "authenticated_username" not in fake_st.session_state
    assert "_last_activity_time" not in fake_st.session_state


def test_authenticated_session_refreshes_activity_before_timeout(monkeypatch):
    fake_st = FakeStreamlit()
    fake_st.session_state.update(
        {
            "authenticated": True,
            "authenticated_username": "owner",
            "session_timeout_minutes": 15,
            "_last_activity_time": 1_000.0,
        }
    )
    monkeypatch.setattr(auth, "st", fake_st)
    monkeypatch.setattr(auth.time, "time", lambda: 1_899.0)

    assert auth.is_authenticated() is True
    assert fake_st.session_state["authenticated"] is True
    assert fake_st.session_state["authenticated_username"] == "owner"
    assert fake_st.session_state["_last_activity_time"] == 1_899.0
