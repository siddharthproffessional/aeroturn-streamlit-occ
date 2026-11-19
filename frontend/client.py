import os
from urllib.parse import parse_qsl, urlsplit

import httpx
import streamlit as st

ORIGIN = os.getenv("AEROTURN_API", "http://127.0.0.1:8000").rstrip("/")
HOSTED = os.getenv("AEROTURN_COMMUNITY_CLOUD") == "1"


class ApiError(ValueError):
    def __init__(self, data, status=None):
        self.data = data
        self.status = status
        super().__init__(
            data.get("reason") or data.get("detail") or "Request unconfirmed"
        )


def request(path, body=None, token=None):
    key = (
        token
        if token is not None
        else st.session_state.get("access") or os.getenv("AEROTURN_OPS_TOKEN", "")
    )
    url = ORIGIN + path
    params = None
    if HOSTED:
        route = urlsplit(path)
        url = ORIGIN + "/api/occ/dashboard"
        params = dict(parse_qsl(route.query), path=route.path, room=st.session_state.get("room", "judges"))
    try:
        response = httpx.request(
            "GET" if body is None else "POST",
            url,
            params=params,
            json=body,
            headers={"Authorization": "Bearer " + key},
            timeout=330 if path in ("/api/recovery/analyse", "/agent/report") else 60,
            trust_env=False,
        )
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ApiError(
            {
                "detail": "No usable response from FastAPI. Check the transaction history before retrying."
            }
        ) from exc
    if not response.is_success:
        raise ApiError(
            data if isinstance(data, dict) else {"detail": response.reason_phrase},
            response.status_code,
        )
    return data


def fetch(path):
    try:
        return request(path)
    except ApiError as exc:
        st.error(str(exc))
        st.stop()


def classify(result):
    if not isinstance(result, dict):
        return "Unconfirmed"
    if result.get("tool") == "stage_controller_schedule_change" and isinstance(
        result.get("receipt"), dict
    ):
        return classify(result["receipt"])
    if result.get("transaction_id") and result.get("assignments"):
        return "Executed"
    if result.get("id") and result.get("status") in ("pending", "approved", "rejected"):
        return {"pending": "Staged", "approved": "Approved", "rejected": "Rejected"}[
            result["status"]
        ]
    if result.get("analysis_id") and result.get("executive_report"):
        return (
            "Recommended"
            if result.get("purpose") != "final report"
            else "Report generated"
        )
    if any(result.get(k) is True for k in ("legal", "clear", "dispatch_ready")):
        return "Validated"
    if (
        "delay" in result
        or result.get("signed_by")
        or result.get("crew")
        and "projected" in result
    ):
        return "Executed"
    return "Unconfirmed"


def action(label, path, body=None, token=None, disabled=False):
    if st.button(label, disabled=disabled):
        try:
            data = request(path, {} if body is None else body, token)
            status = classify(data)
        except ApiError as exc:
            data = exc.data
            status = (
                "Rejected"
                if exc.status
                and exc.status < 500
                and data.get("decision") == "rejected"
                else "Unconfirmed"
            )
            attempt = data.get("record_ids", {}).get("attempt_id")
            if attempt:
                try:
                    proof = request("/coordination/alerts/rollback/" + attempt)
                    evidence = proof.get("evidence", {})
                    if (
                        evidence.get("attempt_id") == attempt
                        and evidence.get("verified") is True
                    ):
                        data = {"decision": data, "rollback": evidence}
                        status = "Rolled back"
                except ApiError:
                    pass
        st.session_state["last_action"] = (status, label, data)
        st.rerun()
