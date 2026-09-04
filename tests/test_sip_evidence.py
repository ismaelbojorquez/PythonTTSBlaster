import json

import pytest

from blaster.telephony.sip_evidence import invite_response


def test_response_keeps_only_numeric_evidence_and_handles_folded_reason():
    message = (
        'SIP/2.0 480 Temporarily Unavailable\r\n'
        'CSeq: 12 INVITE\r\n'
        'Reason: Q.850;cause=20;text="Subscriber absent, password=secret",\r\n'
        ' SIP;cause=480;text="Unavailable"\r\n'
        'Retry-After: 120 (wait)\r\n'
        'Authorization: Digest username="private", response="secret"\r\n'
        'Contact: <sip:private@host>\r\n\r\n'
        'Reason: Q.850;cause=99\r\n'
    )
    result = invite_response(message)
    assert result == {
        "code": 480, "cseq": 12, "retry_after": 120,
        "reason_causes": [{"protocol": "Q.850", "cause": 20}, {"protocol": "SIP", "cause": 480}],
    }
    assert "secret" not in json.dumps(result)
    assert "private" not in json.dumps(result)


def test_reason_is_optional_and_never_inferred_from_480():
    assert invite_response("SIP/2.0 480 Temporarily Unavailable\r\nCSeq: 9 INVITE\r\n\r\n") == {
        "code": 480, "cseq": 9, "retry_after": 0, "reason_causes": [],
    }


def test_multiple_reason_headers_and_quoted_fake_cause():
    result = invite_response(
        'SIP/2.0 503 Unavailable\nCSeq: 20 INVITE\n'
        'Reason: Q.850;text="fake;cause=17, SIP;cause=486";cause=34\n'
        'Reason: SIP;cause=503\nRetry-After: 9999999999\n\n'
    )
    assert result["retry_after"] == 86400
    assert result["reason_causes"] == [
        {"protocol": "Q.850", "cause": 34}, {"protocol": "SIP", "cause": 503},
    ]


@pytest.mark.parametrize("message", [
    "INVITE sip:100@localhost SIP/2.0\r\nCSeq: 1 INVITE\r\n\r\n",
    "SIP/2.0 200 OK\r\nCSeq: 1 BYE\r\n\r\n",
    "SIP/2.0 200 OK\r\nCSeq: 1 REGISTER\r\n\r\n",
    "SIP/2.0 480 Unavailable\r\n\r\nCSeq: 1 INVITE\r\n",
    "",
])
def test_only_invite_responses_are_classified(message):
    assert invite_response(message) is None
