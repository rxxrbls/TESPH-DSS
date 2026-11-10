"""Client timer helpers that replace stale inactivity reload schedules."""


def reload_delay_ms(deadline: float, now: float) -> int:
    return max(250, int((deadline - now) * 1_000))


def guarded_reload_script(deadline: float, delay_ms: int) -> str:
    return f"""
    <script>
    const host = window.parent;
    const token = {deadline!r};
    const timerKey = "__tesphSessionTimeoutReloadTimer";
    const activeToken = Number(host.__tesphSessionTimeoutReloadToken);
    if (Number.isFinite(activeToken) && activeToken > token) return;
    if (host[timerKey]) host.clearTimeout(host[timerKey]);
    host.__tesphSessionTimeoutReloadToken = token;
    const checkDeadline = () => {{
      if (host.__tesphSessionTimeoutReloadToken !== token) return;
      const remaining = token * 1000 - Date.now();
      if (remaining <= 0) {{
        host[timerKey] = null;
        host.location.reload();
        return;
      }}
      host[timerKey] = host.setTimeout(checkDeadline, Math.max(250, remaining));
    }};
    host[timerKey] = host.setTimeout(checkDeadline, {delay_ms});
    </script>
    """


def clear_reload_script() -> str:
    return """
    <script>
    const host = window.parent;
    if (host.__tesphSessionTimeoutReloadTimer) {
      host.clearTimeout(host.__tesphSessionTimeoutReloadTimer);
      host.__tesphSessionTimeoutReloadTimer = null;
    }
    host.__tesphSessionTimeoutReloadToken = null;
    </script>
    """
