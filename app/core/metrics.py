import time

BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

requests = {}
durations = {}
started = time.time()


def observe(method, path, status, seconds):
    key = (method, path, str(status))
    requests[key] = requests.get(key, 0) + 1
    hist = durations.setdefault((method, path), {"buckets": [0] * len(BUCKETS), "sum": 0.0, "count": 0})
    for i, bound in enumerate(BUCKETS):
        if seconds <= bound:
            hist["buckets"][i] += 1
    hist["sum"] += seconds
    hist["count"] += 1


def label(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def line(name, value, **labels):
    if labels:
        body = ",".join(f'{k}="{label(v)}"' for k, v in labels.items())
        return f"{name}{{{body}}} {value}"
    return f"{name} {value}"


def head(name, kind, text):
    return [f"# HELP {name} {text}", f"# TYPE {name} {kind}"]


def render_http():
    out = head("viskas_http_requests_total", "counter", "HTTP requests")
    for (method, path, status), n in sorted(requests.items()):
        out.append(line("viskas_http_requests_total", n, method=method, path=path, status=status))
    out += head("viskas_http_request_duration_seconds", "histogram", "HTTP request duration")
    for (method, path), hist in sorted(durations.items()):
        for bound, n in zip(BUCKETS, hist["buckets"]):
            out.append(
                line("viskas_http_request_duration_seconds_bucket", n, method=method, path=path, le=bound)
            )
        out.append(
            line("viskas_http_request_duration_seconds_bucket", hist["count"], method=method, path=path, le="+Inf")
        )
        out.append(line("viskas_http_request_duration_seconds_sum", round(hist["sum"], 6), method=method, path=path))
        out.append(line("viskas_http_request_duration_seconds_count", hist["count"], method=method, path=path))
    out += head("viskas_uptime_seconds", "gauge", "App uptime")
    out.append(line("viskas_uptime_seconds", round(time.time() - started)))
    return out
