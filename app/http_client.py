"""共用 HTTP 連線工具。

櫃買中心的 TLS 憑證缺少 Subject Key Identifier，Python 3.13 預設啟用的
VERIFY_X509_STRICT 會直接拒絕連線。這裡只關閉該項嚴格合規檢查，
仍保留完整的憑證鏈與主機名稱驗證。
"""
import logging
import ssl
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

from app import config

logger = logging.getLogger(__name__)


class RelaxedSSLAdapter(HTTPAdapter):
    """放寬 X509 嚴格合規檢查的傳輸層。"""

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        context = ssl.create_default_context()
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kwargs["ssl_context"] = context
        self.poolmanager = PoolManager(
            num_pools=connections, maxsize=maxsize, block=block, **kwargs
        )


def build_session():
    """建立共用的 requests Session。"""
    session = requests.Session()
    session.headers.update({"User-Agent": config.USER_AGENT})
    session.mount("https://", RelaxedSSLAdapter())
    return session


_session = None


def get_session():
    global _session
    if _session is None:
        _session = build_session()
    return _session


def fetch(url, params=None, as_json=True, encoding=None):
    """發送 GET 請求，失敗時重試，回傳 JSON 或文字內容。"""
    session = get_session()
    last_error = None
    for attempt in range(1, config.MAX_RETRY + 1):
        try:
            resp = session.get(url, params=params, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            if as_json:
                return resp.json()
            if encoding:
                return resp.content.decode(encoding, errors="replace")
            return resp.text
        except Exception as exc:
            last_error = exc
            logger.warning("請求失敗 (第 %d 次)：%s %s", attempt, url, exc)
            if attempt < config.MAX_RETRY:
                time.sleep(config.RETRY_BACKOFF * attempt)
    raise RuntimeError(f"請求連續失敗 {config.MAX_RETRY} 次：{url}") from last_error
