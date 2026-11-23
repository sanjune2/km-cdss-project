"""Loopback-only, cancellable JSON completion using a resident llama.cpp model."""
import json
import os
from time import monotonic
from urllib.parse import urlsplit


def server_completion(base_url, prompt, schema, cancelled, *, limit, timeout):
    import httpx

    address = urlsplit(base_url)
    if (address.scheme != 'http' or address.hostname not in ('127.0.0.1', 'localhost', '::1')
            or address.username or address.password or address.path not in ('', '/')
            or address.query or address.fragment):
        raise ValueError('설명 서버는 인증정보가 없는 로컬 HTTP 주소여야 합니다.')
    started = monotonic()
    content = []
    completed = None
    payload = {'prompt': prompt, 'json_schema': schema, 'n_predict': limit,
               'temperature': 0, 'seed': 42, 'stream': True, 'cache_prompt': True,
               'sse_ping_interval': 1}
    # No redirects or environment proxies: patient context remains on this PC.
    key = os.getenv('KM_CDSS_LLAMA_SERVER_API_KEY', '').strip()
    headers = {'Authorization':f'Bearer {key}'} if key else {}
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=3), trust_env=False,
                      follow_redirects=False) as client:
        with client.stream('POST', base_url.rstrip('/') + '/completion', json=payload, headers=headers) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if cancelled():
                    raise InterruptedError('로컬 모델 요청을 중단했습니다.')
                if monotonic() - started >= timeout:
                    raise TimeoutError('로컬 모델 요청 제한시간을 초과했습니다.')
                if not line.startswith('data: '):
                    continue
                item = json.loads(line[6:])
                if 'error' in item:
                    raise ValueError('로컬 모델 요청을 완료하지 못했습니다.')
                content.append(item.get('content', ''))
                if item.get('stop') is True:
                    completed = item
                    break
    if completed is None or completed.get('stop_type') not in ('eos', 'word'):
        raise ValueError('로컬 모델 응답이 출력 한도 안에서 종료되지 않았습니다.')
    document = json.loads(''.join(content))
    if not isinstance(document, dict):
        raise ValueError('로컬 모델 응답이 JSON 객체가 아닙니다.')
    return document, completed.get('timings', {})
