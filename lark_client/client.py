"""
Lark delivery layer (Worker 3's hands).

Three interchangeable implementations behind one interface so the rest of the
pipeline never cares how a tender reaches Lark:

  * BotClient     -- Open API: uploads the actual PDF file + sends an interactive
                     card. This is the mode you publish as a real Lark app.
  * WebhookClient -- posts a message card to a group's incoming webhook. Quick to
                     set up, but can't upload a file (links only).
  * NoopClient    -- logs what *would* be sent. Default, so nothing breaks before
                     you've configured credentials.

`send(doc)` raises LarkError on a recoverable failure (network/5xx/ratelimit) so
the uploader knows to hand the doc to the retry queue.
"""

from __future__ import annotations

import abc
import base64
import hashlib
import hmac
import time
from pathlib import Path

from config import LARK, LarkConfig
from core.logging_setup import get_logger
from core.models import TenderDoc

try:
    import requests  # type: ignore
except ImportError:
    requests = None


class LarkError(Exception):
    """Recoverable Lark failure — caller should retry."""


class BaseLarkClient(abc.ABC):
    def __init__(self, config: LarkConfig) -> None:
        self.config = config
        self.log = get_logger("lark")

    @abc.abstractmethod
    def send(self, doc: TenderDoc) -> None:
        ...

    # Shared human-readable summary used by every implementation.
    @staticmethod
    def _summary(doc: TenderDoc) -> str:
        val = f"₹{doc.value:,.0f}" if doc.value is not None else "N/A"
        close = doc.closing_date.isoformat() if doc.closing_date else "N/A"
        return (
            f"📄 New tender: {doc.title}\n"
            f"• Source: {doc.source}\n"
            f"• ID: {doc.doc_id}\n"
            f"• Value: {val}\n"
            f"• Closing: {close}"
        )

    @staticmethod
    def _require_requests():
        if requests is None:
            raise LarkError("the 'requests' package is not installed")


# --------------------------------------------------------------------------- #
class NoopClient(BaseLarkClient):
    def send(self, doc: TenderDoc) -> None:
        self.log.info("[noop] would deliver to Lark:\n%s", self._summary(doc))


# --------------------------------------------------------------------------- #
class WebhookClient(BaseLarkClient):
    def send(self, doc: TenderDoc) -> None:
        self._require_requests()
        if not self.config.webhook_url:
            raise LarkError("LARK_WEBHOOK_URL is not set")

        payload = {
            "msg_type": "interactive",
            "card": _tender_card(doc),
        }
        # Optional signature (only if the webhook has 'signature verification' on).
        if self.config.webhook_secret:
            ts = str(int(time.time()))
            payload["timestamp"] = ts
            payload["sign"] = _webhook_sign(ts, self.config.webhook_secret)

        try:
            resp = requests.post(self.config.webhook_url, json=payload, timeout=20)
        except requests.RequestException as exc:  # network problem -> retry
            raise LarkError(f"webhook request failed: {exc}") from exc

        _raise_for_lark(resp)
        self.log.info("Delivered %s to Lark via webhook", doc.doc_id)


# --------------------------------------------------------------------------- #
class BotClient(BaseLarkClient):
    """Open API bot: token -> upload file -> send card with a file button."""

    def __init__(self, config: LarkConfig) -> None:
        super().__init__(config)
        self._token = ""
        self._token_expiry = 0.0

    def _base(self) -> str:
        return self.config.api_base.rstrip("/")

    def _tenant_token(self) -> str:
        self._require_requests()
        # Cache the token until ~2 min before it expires.
        if self._token and time.time() < self._token_expiry - 120:
            return self._token
        if not (self.config.app_id and self.config.app_secret):
            raise LarkError("LARK_APP_ID / LARK_APP_SECRET are not set")

        url = f"{self._base()}/open-apis/auth/v3/tenant_access_token/internal"
        try:
            resp = requests.post(
                url,
                json={"app_id": self.config.app_id, "app_secret": self.config.app_secret},
                timeout=20,
            )
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise LarkError(f"token request failed: {exc}") from exc

        if data.get("code") != 0:
            raise LarkError(f"token error {data.get('code')}: {data.get('msg')}")
        self._token = data["tenant_access_token"]
        self._token_expiry = time.time() + data.get("expire", 7200)
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._tenant_token()}"}

    def _upload_file(self, pdf_path: Path) -> str | None:
        """Upload the PDF to Lark's file store; return a file_key (or None)."""
        if not pdf_path or not Path(pdf_path).exists():
            return None
        url = f"{self._base()}/open-apis/im/v1/files"
        try:
            with open(pdf_path, "rb") as fh:
                resp = requests.post(
                    url,
                    headers=self._headers(),
                    data={"file_type": "pdf", "file_name": Path(pdf_path).name},
                    files={"file": (Path(pdf_path).name, fh, "application/pdf")},
                    timeout=60,
                )
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise LarkError(f"file upload failed: {exc}") from exc
        if data.get("code") != 0:
            raise LarkError(f"file upload error {data.get('code')}: {data.get('msg')}")
        return data["data"]["file_key"]

    def _upload_bitable_file(self, pdf_path: Path) -> str | None:
        """Upload the PDF to Lark Drive for Bitable; return a file_token (or None)."""
        if not pdf_path or not Path(pdf_path).exists():
            return None
        url = f"{self._base()}/open-apis/drive/v1/medias/upload_all"
        try:
            with open(pdf_path, "rb") as fh:
                resp = requests.post(
                    url,
                    headers=self._headers(),
                    data={
                        "file_name": Path(pdf_path).name,
                        "parent_type": "bitable_file",
                        "parent_node": self.config.bitable_app_token,
                        "size": Path(pdf_path).stat().st_size,
                    },
                    files={"file": (Path(pdf_path).name, fh, "application/pdf")},
                    timeout=60,
                )
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            self.log.error("Bitable file upload failed: %s", exc)
            return None
        if data.get("code") != 0:
            self.log.error("Bitable file upload error %s: %s", data.get('code'), data.get('msg'))
            return None
        return data["data"]["file_token"]

    def _send_message(self, msg_type: str, content: str) -> None:
        url = f"{self._base()}/open-apis/im/v1/messages"
        params = {"receive_id_type": self.config.receive_id_type}
        body = {
            "receive_id": self.config.receive_id,
            "msg_type": msg_type,
            "content": content,
        }
        try:
            resp = requests.post(
                url, headers=self._headers(), params=params, json=body, timeout=20
            )
        except requests.RequestException as exc:
            raise LarkError(f"send message failed: {exc}") from exc
        _raise_for_lark(resp)

    def _insert_bitable(self, doc: TenderDoc) -> None:
        url = f"{self._base()}/open-apis/bitable/v1/apps/{self.config.bitable_app_token}/tables/{self.config.bitable_table_id}/records"
        
        fields = {
            "PROJECT ID": doc.doc_id,
            "Project Details": doc.title,
            "Customer Name": doc.source,
        }
        
        if doc.value is not None:
            fields["Tender Amount"] = doc.value
            
        if doc.closing_date:
            import datetime
            dt = datetime.datetime.combine(doc.closing_date, datetime.time.min)
            fields["Bid Submission Date"] = int(dt.timestamp() * 1000)
            
        if doc.published_date:
            import datetime
            dt = datetime.datetime.combine(doc.published_date, datetime.time.min)
            fields["NIT Date"] = int(dt.timestamp() * 1000)
            
        if doc.pdf_path:
            file_token = self._upload_bitable_file(Path(doc.pdf_path))
            if file_token:
                fields["Tender Doc"] = [{"file_token": file_token}]
                
        body = {"fields": fields}
        try:
            resp = requests.post(url, headers=self._headers(), json=body, timeout=20)
            _raise_for_lark(resp)
            self.log.info("Inserted %s into Bitable", doc.doc_id)
        except Exception as exc:
            self.log.error("Failed to insert into Bitable: %s", exc)
            # We don't raise here, so we don't fail the whole uploader if just Bitable fails,
            # or you can re-raise if Bitable is strictly required.

    def send(self, doc: TenderDoc) -> None:
        import json

        if not self.config.receive_id:
            raise LarkError("LARK_RECEIVE_ID is not set")

        # 1) Send the rich card (works even if the file upload later fails).
        self._send_message("interactive", json.dumps(_tender_card(doc)))

        # 2) Upload + send the PDF itself, if we have one.
        file_key = self._upload_file(Path(doc.pdf_path)) if doc.pdf_path else None
        if file_key:
            self._send_message("file", json.dumps({"file_key": file_key}))

        self.log.info("Delivered %s to Lark via bot API", doc.doc_id)

        # 3) Insert into Bitable if configured
        if self.config.bitable_app_token and self.config.bitable_table_id:
            self._insert_bitable(doc)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _tender_card(doc: TenderDoc) -> dict:
    val = f"₹{doc.value:,.0f}" if doc.value is not None else "N/A"
    close = doc.closing_date.isoformat() if doc.closing_date else "N/A"
    fields = [
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**Source**\n{doc.source}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**ID**\n{doc.doc_id}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**Value**\n{val}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**Closing**\n{close}"}},
    ]
    elements = [{"tag": "div", "fields": fields}]
    if doc.detail_url:
        elements.append({
            "tag": "action",
            "actions": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "Open tender"},
                "url": doc.detail_url,
                "type": "primary",
            }],
        })
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": f"📄 {doc.title[:80] or 'New tender'}"},
        },
        "elements": elements,
    }


def _webhook_sign(timestamp: str, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), b"", hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _raise_for_lark(resp) -> None:
    """Turn an HTTP/Lark error into a retryable LarkError."""
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 500 or resp.status_code == 429:
        raise LarkError(f"Lark HTTP {resp.status_code}")
    if data.get("code") not in (0, None):
        raise LarkError(f"Lark error {data.get('code')}: {data.get('msg')}")
    if resp.status_code >= 400:
        raise LarkError(f"Lark HTTP {resp.status_code}: {resp.text[:200]}")


_CLIENTS = {"bot": BotClient, "webhook": WebhookClient, "noop": NoopClient}


def build_lark_client(config: LarkConfig = LARK) -> BaseLarkClient:
    cls = _CLIENTS.get(config.mode.lower(), NoopClient)
    return cls(config)
