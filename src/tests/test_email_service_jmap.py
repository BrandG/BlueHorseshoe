"""JMAP backend tests — mock the Fastmail API; guard the dual-'s' response parsing."""
# pylint: disable=protected-access,redefined-outer-name
from types import SimpleNamespace

import pytest

import bluehorseshoe.core.email_service as es

SESSION = {
    "apiUrl": "https://api.example/jmap",
    "uploadUrl": "https://api.example/upload/{accountId}",
    "primaryAccounts": {"urn:ietf:params:jmap:mail": "acct"},
}
META = {"methodResponses": [
    ["Mailbox/get", {"list": [{"id": "D", "role": "drafts"}, {"id": "S", "role": "sent"}]}, "m"],
    ["Identity/get", {"list": [{"id": "ID", "email": "bluehorseshoe@fastmail.com"}]}, "i"],
]}


class _Resp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d

    def raise_for_status(self):
        pass


def _fake_requests(submission_ok=True, capture=None):
    if submission_ok:
        sub = {"created": {"s": {"id": "SUB1", "undoStatus": "final"}}, "notCreated": None}
    else:
        sub = {"created": None, "notCreated": {"s": {"type": "forbiddenFrom"}}}
    # The real API appends an implicit Email/set (moving to Sent) that SHARES cid "s".
    send_resp = {"methodResponses": [
        ["Email/set", {"created": {"d": {"id": "E1"}}, "notCreated": None}, "c"],
        ["EmailSubmission/set", sub, "s"],
        ["Email/set", {"updated": {"E1": None}, "created": None}, "s"],
    ]}

    def post(url, headers=None, json=None, data=None, timeout=None):
        if data is not None:                       # blob upload
            return _Resp({"blobId": "BLOB", "type": "text/csv", "size": len(data)})
        if capture is not None:
            capture.append(json)
        names = [c[0] for c in json["methodCalls"]]
        return _Resp(META if "Mailbox/get" in names else send_resp)

    def get(url, headers=None, timeout=None):
        return _Resp(SESSION)

    return SimpleNamespace(get=get, post=post)


@pytest.fixture
def jmap_service(monkeypatch):
    svc = es.EmailService()
    svc.backend = "jmap"
    svc.jmap_token = "tok"
    svc.sender = "bluehorseshoe@fastmail.com"
    svc.recipient = "brandg@gmail.com"
    return svc


def test_send_returns_guid_despite_implicit_email_set(jmap_service, monkeypatch):
    monkeypatch.setattr(es, "requests", _fake_requests(submission_ok=True))
    out = jmap_service._send_jmap("Subj [id:g1]", "g1", "<p>hi</p>", "hi", None)
    assert out == "g1"


def test_submission_failure_returns_none(jmap_service, monkeypatch):
    monkeypatch.setattr(es, "requests", _fake_requests(submission_ok=False))
    assert jmap_service._send_jmap("Subj [id:g2]", "g2", None, "hi", None) is None


def test_attachment_is_uploaded_and_referenced(jmap_service, monkeypatch, tmp_path):
    cap = []
    monkeypatch.setattr(es, "requests", _fake_requests(submission_ok=True, capture=cap))
    f = tmp_path / "a.csv"
    f.write_text("x,y\n1,2\n")
    out = jmap_service._send_jmap("S [id:g3]", "g3", None, "body", [str(f)])
    assert out == "g3"
    # the Email/set create must reference the uploaded blob as an attachment
    send_call = next(c for c in cap if any(m[0] == "Email/set" for m in c["methodCalls"]))
    email_create = send_call["methodCalls"][0][1]["create"]["d"]
    parts = email_create["bodyStructure"]["subParts"]
    assert any(p.get("blobId") == "BLOB" and p.get("disposition") == "attachment" for p in parts)
