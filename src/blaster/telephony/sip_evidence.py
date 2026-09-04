"""Extract numeric response evidence without retaining SIP messages or Digest headers."""

from __future__ import annotations

import re


def invite_response(message: str) -> dict | None:
    # Ignore the body, including SDP, and bound work on untrusted header values.
    headers = re.split(r"\r?\n\r?\n", message[:65536], maxsplit=1)[0]
    headers = re.sub(r"\r?\n[ \t]+", " ", headers)
    status = re.match(r"SIP/2\.0[ \t]+([1-6][0-9]{2})\b", headers)
    cseq = re.search(r"(?im)^CSeq:[ \t]*([0-9]{1,10})[ \t]+INVITE[ \t]*\r?$", headers)
    if not status or not cseq:
        return None
    retry = re.search(r"(?im)^Retry-After:[ \t]*([0-9]{1,10})\b", headers)
    result = {
        "code": int(status[1]),
        "cseq": int(cseq[1]),
        "retry_after": min(86400, int(retry[1])) if retry else 0,
        "reason_causes": [],
    }
    for header in re.findall(r"(?im)^Reason:[ \t]*([^\r\n]*)", headers):
        # Quoted text may contain commas or fake parameters; it is never stored.
        header = re.sub(r'"(?:\\.|[^"\\])*"', '""', header)
        for value in header.split(","):
            parts = value.strip().split(";")
            protocol = parts[0].strip().upper()
            if protocol not in {"SIP", "Q.850"}:
                continue
            for part in parts[1:]:
                cause = re.fullmatch(r"\s*cause\s*=\s*([0-9]{1,3})\s*", part, re.I)
                if cause and len(result["reason_causes"]) < 4:
                    result["reason_causes"].append({"protocol": protocol, "cause": int(cause[1])})
                    break
    return result
