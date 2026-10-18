"""Read-only Telegram access diagnostics; output only explicitly selected fields."""

import json
import os
import socket
import sys
from urllib import error, parse, request

CHANNELS = (-1004382412226, "@svoi_zvenigorod")
METHODS = {"getMe", "getChat", "getChatMember"}


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def category(code, description):
    # Inspect descriptions only for classification; never print them.
    text = description.lower() if isinstance(description, str) else ""
    if "chat not found" in text:
        return "CHAT_NOT_FOUND_OR_INACCESSIBLE"
    if code == 401:
        return "UNAUTHORIZED_TOKEN"
    if code == 403:
        return "FORBIDDEN"
    if code == 429:
        return "RATE_LIMITED"
    if "not enough rights" in text or "administrator rights" in text:
        return "INSUFFICIENT_RIGHTS"
    if code == 400:
        return "BAD_REQUEST"
    if isinstance(code, int) and code >= 500:
        return "TELEGRAM_SERVER_ERROR"
    return "API_ERROR"


def api(token, method, **params):
    if method not in METHODS:
        return None, "METHOD_NOT_ALLOWED"
    req = request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=parse.urlencode(params).encode("ascii"),
        method="POST",
    )
    try:
        opener = request.build_opener(NoRedirect())
        try:
            response = opener.open(req, timeout=20)
        except error.HTTPError as exc:
            response = exc
        with response:
            code = response.code
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            return None, "RESPONSE_TOO_LARGE"
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            return None, "INVALID_RESPONSE"
        if not isinstance(payload, dict):
            return None, "INVALID_RESPONSE"
        if code != 200 or payload.get("ok") is not True:
            return None, category(code, payload.get("description"))
        result = payload.get("result")
        if not isinstance(result, dict):
            return None, "INVALID_RESPONSE"
        return result, None
    except (TimeoutError, socket.timeout):
        return None, "TIMEOUT"
    except error.URLError:
        return None, "NETWORK_OR_TLS_ERROR"
    except Exception:
        # Exceptions may contain the credential-bearing URL. Never serialize them.
        return None, "REQUEST_FAILED"


def emit(token, **fields):
    # JSON escapes line breaks/control characters, preventing workflow commands.
    line = json.dumps(fields, ensure_ascii=True)
    print(line.replace(token, "[REDACTED]") if token else line, flush=True)


def selected(data, fields):
    return {
        key: data[key]
        for key, expected_type in fields.items()
        if type(data.get(key)) is expected_type
    }


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        emit(token, method="getMe", error="MISSING_TOKEN")
        return 1
    me, failure = api(token, "getMe")
    identity = selected(me or {}, {"id": int, "username": str, "is_bot": bool})
    bot_id = identity.get("id")
    if failure is None and (bot_id is None or identity.get("is_bot") is not True):
        failure = "INVALID_BOT_IDENTITY"
    emit(token, method="getMe", result="error" if failure else "ok",
         error=failure, **identity)
    failed = bool(failure)
    for chat_id in CHANNELS:
        chat, chat_failure = api(token, "getChat", chat_id=chat_id)
        emit(token, chat_id=chat_id, method="getChat",
             result="error" if chat_failure else "ok", error=chat_failure,
             **selected(chat or {}, {"id": int, "title": str, "type": str}))
        failed = failed or bool(chat_failure)
        if failure:
            emit(token, chat_id=chat_id, method="getChatMember",
                 result="skipped", error="BOT_ID_UNAVAILABLE")
            continue
        member, member_failure = api(token, "getChatMember",
                                     chat_id=chat_id, user_id=bot_id)
        rights = selected(member or {}, {"status": str, "can_post_messages": bool})
        if member_failure is None and rights.get("status") not in {
            "creator", "administrator", "member", "restricted", "left", "kicked"
        }:
            member_failure = "INVALID_MEMBER_STATUS"
        emit(token, chat_id=chat_id, method="getChatMember",
             result="error" if member_failure else "ok", error=member_failure,
             **rights)
        failed = failed or bool(member_failure)
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
