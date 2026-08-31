import gzip
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "stubs"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import CommonServerPython as csp  # noqa: E402
import requests as fake_requests  # noqa: E402  (stub)
import CiscoUmbrellaS3EventCollector as col  # noqa: E402

SENT = []


def sender(events):
    SENT.extend(events)

PREFIX = "1234567_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"

DNS_ROWS = [
    '"2026-08-28 09:15:01","LAPTOP-1","LAPTOP-1,AD Site","10.1.2.3","203.0.113.9",'
    '"Blocked","1 (A)","NOERROR","malware.example.com","Malware","AD Computers",'
    '"AD Computers,AD Users","Malware"',
    '"2026-08-28 09:15:02","LAPTOP-2","LAPTOP-2","10.1.2.4","203.0.113.9",'
    '"Allowed","1 (A)","NOERROR","www.cisco.com","Software/Technology","AD Computers",'
    '"AD Computers",""',
]

AUDIT_ROWS = [
    "id,timestamp,email,user,type,action,ip,before,after",
    '1234,"2026-08-28 08:00:00","admin@corp.com","Admin","policy","update","198.51.100.7","{}","{}"',
]


class FakeS3:
    """Stands in for UmbrellaS3Client without touching boto3."""

    def __init__(self, objects):
        self.prefix = PREFIX
        self.bucket = "cisco-managed-us-west-1"
        self.objects = objects
        self.reads = []

    def list_keys(self, log_type, start_after, limit):
        keys = sorted(k for k in self.objects if k.startswith(f"{self.prefix}/{log_type}/"))
        if start_after:
            keys = [k for k in keys if k > start_after]
        return keys[:limit]

    def get_object_lines(self, key):
        self.reads.append(key)
        return self.objects[key]


def gz_roundtrip_check():
    """The real client gunzips; make sure our decode assumption holds."""
    raw = gzip.compress("\n".join(DNS_ROWS).encode())
    assert gzip.decompress(raw).decode().splitlines() == DNS_ROWS


def test_parse_dns():
    key = f"{PREFIX}/dnslogs/2026-08-28/2026-08-28-09-15-a1b2.csv.gz"
    events = col.parse_file(DNS_ROWS, "dnslogs", key, {})
    assert len(events) == 2, events
    first = events[0]
    assert first["domain"] == "malware.example.com"
    assert first["action"] == "Blocked"
    assert first["policy_identity"] == "LAPTOP-1"
    assert first["blocked_categories"] == "Malware"
    assert first["_time"] == "2026-08-28T09:15:01.000Z"
    assert first["source_log_type"] == "dnslogs"
    assert first["s3_key"] == key
    print("parse dns ok:", first["_time"], first["domain"])


def test_parse_audit_header_skipped():
    key = f"{PREFIX}/auditlogs/2026-08-28/2026-08-28-08-00-ffff.csv.gz"
    events = col.parse_file(AUDIT_ROWS, "auditlogs", key, {})
    assert len(events) == 1, events
    assert events[0]["email"] == "admin@corp.com"
    assert events[0]["_time"] == "2026-08-28T08:00:00.000Z"
    print("audit header skipped ok")


def test_v13_columns_and_overflow():
    """dnslogs is 16 columns at schema v13; anything beyond survives as col_N."""
    row = DNS_ROWS[0] + ',"r-1","GB","1234567","FUTURE_V14_FIELD"'
    events = col.parse_file([row], "dnslogs", "k", {})
    assert events[0]["rule_id"] == "r-1"
    assert events[0]["destination_country"] == "GB"
    assert events[0]["org_id"] == "1234567"
    assert events[0]["col_16"] == "FUTURE_V14_FIELD"
    assert len(col.LOG_TYPE_COLUMNS["firewalllogs"]) == 36
    assert col.LOG_TYPE_COLUMNS["firewalllogs"][2] == "identities"
    assert "dlplogs" in col.LOG_TYPE_COLUMNS and "intrusionlogs" in col.LOG_TYPE_COLUMNS
    print("v13 columns ok; overflow ->", events[0]["col_16"])


def test_column_override():
    events = col.parse_file(DNS_ROWS[:1], "dnslogs", "k", {"dnslogs": ["ts", "who"]})
    assert events[0]["ts"] == "2026-08-28 09:15:01"
    assert events[0]["who"] == "LAPTOP-1"
    assert events[0]["col_2"].startswith("LAPTOP-1")
    print("column override ok")


def test_time_fallback_from_key():
    events = col.parse_file(['"not-a-time","x"'], "dnslogs",
                            f"{PREFIX}/dnslogs/2026-08-28/2026-08-28-09-20-aaaa.csv.gz", {})
    assert events[0]["_time"] == "2026-08-28T09:20:00.000Z", events[0]["_time"]
    print("key time fallback ok")


def test_collect_and_resume():
    SENT.clear()
    k1 = f"{PREFIX}/dnslogs/2026-08-27/2026-08-27-23-50-aaaa.csv.gz"
    k2 = f"{PREFIX}/dnslogs/2026-08-28/2026-08-28-00-00-bbbb.csv.gz"
    k3 = f"{PREFIX}/dnslogs/2026-08-28/2026-08-28-00-10-cccc.csv.gz"
    client = FakeS3({k1: DNS_ROWS, k2: DNS_ROWS, k3: DNS_ROWS})
    first_fetch = datetime(2026, 8, 27)

    display, state, sent = col.collect_log_type(
        client, "dnslogs", {}, first_fetch, max_files=2, max_events=10**6,
        columns_override={}, send=sender)
    assert sent == 4, sent
    assert client.reads == [k1, k2]
    assert set(state["seen_keys"]) == {k1, k2}

    display, state2, sent2 = col.collect_log_type(
        client, "dnslogs", state, first_fetch, max_files=10, max_events=10**6,
        columns_override={}, send=sender)
    assert sent2 == 2, sent2
    assert client.reads == [k1, k2, k3]
    assert k3 in state2["seen_keys"]

    _, _, sent3 = col.collect_log_type(
        client, "dnslogs", state2, first_fetch, max_files=10, max_events=10**6,
        columns_override={}, send=sender)
    assert sent3 == 0
    assert len(SENT) == 6
    print("collect + resume + no-replay ok")


def test_late_arriving_object_is_not_skipped():
    """The v1 cursor parked at max(key) lost files uploaded out of order."""
    SENT.clear()
    late = f"{PREFIX}/dnslogs/2026-08-28/2026-08-28-00-05-aaaa.csv.gz"
    early = f"{PREFIX}/dnslogs/2026-08-28/2026-08-28-00-05-zzzz.csv.gz"
    client = FakeS3({early: DNS_ROWS})
    _, state, _ = col.collect_log_type(
        client, "dnslogs", {}, datetime(2026, 8, 28), max_files=10, max_events=10**6,
        columns_override={}, send=sender)
    assert client.reads == [early]

    client.objects[late] = DNS_ROWS          # sorts BEFORE the key already processed
    _, state2, sent = col.collect_log_type(
        client, "dnslogs", state, datetime(2026, 8, 28), max_files=10, max_events=10**6,
        columns_override={}, send=sender)
    assert late in client.reads, "late-arriving object was skipped"
    assert sent == 2, f"expected only the late file to be re-sent, got {sent}"
    print("late-arriving object collected, no replay of the earlier one")


def test_time_budget_stops_cleanly():
    """A run that runs long must commit what it has, not lose it to a kill."""
    SENT.clear()
    keys = {f"{PREFIX}/dnslogs/2026-08-28/2026-08-28-0{i}-00-aaaa.csv.gz": DNS_ROWS
            for i in range(1, 6)}
    client = FakeS3(keys)
    saved = []
    _, state, sent = col.collect_log_type(
        client, "dnslogs", {}, datetime(2026, 8, 28), max_files=10, max_events=10**6,
        columns_override={}, send=sender, persist=saved.append,
        deadline=0)  # already expired
    assert sent == 0 and client.reads == [], "expired budget must read nothing"

    import time as _t
    _, state2, sent2 = col.collect_log_type(
        client, "dnslogs", {}, datetime(2026, 8, 28), max_files=10, max_events=10**6,
        columns_override={}, send=sender, persist=saved.append,
        deadline=_t.time() + 30)
    assert sent2 == 10, sent2
    print("time budget stops cleanly and commits ok")


def test_state_persisted_per_flush():
    SENT.clear()
    saved = []
    k = f"{PREFIX}/dnslogs/2026-08-28/2026-08-28-00-00-aaaa.csv.gz"
    client = FakeS3({k: DNS_ROWS})
    col.collect_log_type(client, "dnslogs", {}, datetime(2026, 8, 28), 10, 10**6, {},
                         send=sender, persist=saved.append)
    assert saved and k in saved[-1]["seen_keys"]
    print("state persisted via callback ok")


def test_first_fetch_marker_skips_old_days():
    SENT.clear()
    old = f"{PREFIX}/dnslogs/2026-08-01/2026-08-01-10-00-aaaa.csv.gz"
    new = f"{PREFIX}/dnslogs/2026-08-28/2026-08-28-10-00-bbbb.csv.gz"
    client = FakeS3({old: DNS_ROWS, new: DNS_ROWS})
    _, state, sent = col.collect_log_type(
        client, "dnslogs", {}, datetime(2026, 8, 27), max_files=10, max_events=10**6,
        columns_override={}, send=sender)
    assert client.reads == [new], client.reads
    assert sent == 2
    print("first-fetch marker ok:", col.key_start_marker(PREFIX, "dnslogs", datetime(2026, 8, 27)))


def test_bad_object_does_not_stall():
    SENT.clear()
    good = f"{PREFIX}/dnslogs/2026-08-28/2026-08-28-01-00-aaaa.csv.gz"
    bad = f"{PREFIX}/dnslogs/2026-08-28/2026-08-28-02-00-bbbb.csv.gz"
    after = f"{PREFIX}/dnslogs/2026-08-28/2026-08-28-03-00-cccc.csv.gz"

    class Broken(FakeS3):
        def get_object_lines(self, key):
            self.reads.append(key)
            if key == bad:
                raise IOError("corrupt gzip")
            return self.objects[key]

    client = Broken({good: DNS_ROWS, bad: DNS_ROWS, after: DNS_ROWS})
    _, state, sent = col.collect_log_type(
        client, "dnslogs", {}, datetime(2026, 8, 28), max_files=10, max_events=10**6,
        columns_override={}, send=sender)
    assert sent == 4, sent
    assert bad in state["seen_keys"] and after in state["seen_keys"]
    print("bad object skipped ok")


def test_http_collector_posts_ndjson():
    import gzip as _gzip
    fake_requests.CALLS.clear()
    fake_requests.handler = None
    collector = col.XsiamHttpCollector(
        "https://api-acme.xdr.us.paloaltonetworks.com/logs/v1/event", " tok3n ", verify=True)
    collector.send([{"a": 1, "_time": "2026-08-28T00:00:00.000Z"}, {"a": 2}])
    call = fake_requests.CALLS[0]
    assert call["headers"]["Authorization"] == "tok3n"
    assert call["headers"]["Content-Encoding"] == "gzip"
    lines = _gzip.decompress(call["data"]).decode().split("\n")
    assert len(lines) == 2 and json.loads(lines[1])["a"] == 2
    print("collector posts gzipped NDJSON ok")


def test_http_collector_uncompressed_mode():
    fake_requests.CALLS.clear()
    fake_requests.handler = None
    collector = col.XsiamHttpCollector("https://x/logs/v1/event", "t", verify=True,
                                       compress=False)
    collector.send([{"a": 1}])
    call = fake_requests.CALLS[0]
    assert "Content-Encoding" not in call["headers"]
    assert json.loads(call["data"].decode())["a"] == 1
    print("uncompressed mode sends plain NDJSON ok")


def test_http_collector_raises_on_auth_failure():
    fake_requests.CALLS.clear()
    fake_requests.handler = lambda u, d, h: fake_requests.Response(403, "forbidden")
    collector = col.XsiamHttpCollector("https://x/logs/v1/event", "bad", verify=True)
    try:
        collector.send([{"a": 1}])
    except Exception as exc:
        assert "403" in str(exc)
        assert len(fake_requests.CALLS) == 1, "must not retry a 403"
    else:
        raise AssertionError("expected a failure on 403")
    finally:
        fake_requests.handler = None
    print("collector fails fast on 403 ok")


def test_failed_send_leaves_keys_unseen():
    """A transport failure must not mark keys as done - they retry next run."""
    SENT.clear()
    k = f"{PREFIX}/dnslogs/2026-08-28/2026-08-28-00-00-aaaa.csv.gz"
    client = FakeS3({k: DNS_ROWS})
    saved = []

    def broken_sender(events):
        raise RuntimeError("collector unreachable")

    try:
        col.collect_log_type(client, "dnslogs", {}, datetime(2026, 8, 28), 10, 10**6,
                             {}, send=broken_sender, persist=saved.append)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected the send failure to propagate")
    assert all(k not in st.get("seen_keys", []) for st in saved), \
        "key marked seen despite the send failing"

    # and the retry actually re-reads it
    _, state, sent = col.collect_log_type(
        client, "dnslogs", {}, datetime(2026, 8, 28), 10, 10**6, {}, send=sender)
    assert sent == 2 and k in state["seen_keys"]
    print("failed send leaves keys unseen; retry succeeds ok")


def test_oversized_event_is_dropped_not_wedged():
    """One giant event must not permanently block its log type."""
    fake_requests.CALLS.clear()
    fake_requests.handler = None
    old = col.MAX_POST_BYTES
    col.MAX_POST_BYTES = 200
    try:
        collector = col.XsiamHttpCollector("https://x/logs/v1/event", "t", verify=True)
        collector.send([{"blob": "A" * 1000, "s3_key": "big"}, {"ok": 1}])
        assert len(fake_requests.CALLS) == 1, "small event should still post"
        body = gzip.decompress(fake_requests.CALLS[0]["data"]).decode()
        assert '"ok": 1' in body and "AAAA" not in body
    finally:
        col.MAX_POST_BYTES = old
    print("oversized event dropped, feed keeps moving ok")


def test_transport_error_is_retried():
    fake_requests.CALLS.clear()
    attempts = []

    def flaky(url, data, headers):
        attempts.append(1)
        if len(attempts) == 1:
            raise fake_requests.RequestException("connection reset")
        return fake_requests.Response(200)

    fake_requests.handler = flaky
    old_sleep, col.time.sleep = col.time.sleep, lambda s: None
    try:
        col.XsiamHttpCollector("https://x/logs/v1/event", "t", verify=True).send([{"a": 1}])
        assert len(attempts) == 2, attempts
    finally:
        fake_requests.handler = None
        col.time.sleep = old_sleep
    print("transport error retried ok")


def test_401_message_reports_key_shape():
    fake_requests.CALLS.clear()
    fake_requests.handler = lambda u, d, h: fake_requests.Response(401, "")
    collector = col.XsiamHttpCollector("https://x/logs/v1/event", "abcd1234wxyz\n",
                                       verify=True)
    try:
        collector.send([{"a": 1}])
    except Exception as exc:
        msg = str(exc)
        assert "12 characters" in msg, msg
        assert "line break" in msg, msg
        assert "abcd" not in msg and "wxyz" not in msg, "must not leak key characters"
    else:
        raise AssertionError("expected a failure on 401")
    finally:
        fake_requests.handler = None
    print("401 reports the stored key's shape ok")


def test_collector_url_is_validated():
    for bad in ("", "https://api-acme.xdr.us.paloaltonetworks.com/"):
        try:
            col.build_collector({"xsiam_url": bad, "xsiam_token": "t"})
        except Exception as exc:
            assert "logs/v1/event" in str(exc) or "required" in str(exc)
        else:
            raise AssertionError(f"expected rejection of {bad!r}")
    ok = col.build_collector({
        "xsiam_url": "https://api-acme.xdr.us.paloaltonetworks.com/logs/v1/event",
        "xsiam_token": {"password": "k"}})
    assert ok.token == "k"
    print("collector url/token validation ok")


def test_build_client_validation():
    try:
        col.build_client({"credentials": {"identifier": "AK", "password": "SK"}})
    except Exception as exc:
        assert "prefix" in str(exc)
        print("missing prefix rejected ok")
    else:
        raise AssertionError("expected a failure on missing prefix")


if __name__ == "__main__":
    gz_roundtrip_check()
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("\nALL TESTS PASSED")
