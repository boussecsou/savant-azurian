"""Exercise real Uvicorn output with synthetic credentials, including failures."""
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from savant.bff_logging import SafeFormatter


@pytest.mark.parametrize('name', ['azure.core', 'httpx', 'uvicorn.error', 'savant.bff'])
def test_formatter_never_interpolates_payloads_or_tracebacks(name):
    try:
        raise RuntimeError('synthetic-exception-secret')
    except RuntimeError:
        record = logging.LogRecord(name, logging.ERROR, 'synthetic-private-path', 1,
                                   'synthetic-message-%s', ('synthetic-token',), sys.exc_info())
    record.stack_info = 'synthetic-stack-secret'
    record.authorization = 'synthetic-header-secret'
    formatted = SafeFormatter().format(record)
    assert formatted.startswith('ERROR bff_')
    assert 'synthetic' not in formatted


def test_real_uvicorn_logs_do_not_capture_requests_or_exception_secrets():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    source = '''
import logging,sys,warnings
from types import SimpleNamespace
import uvicorn
from savant.bff_logging import LOGGING_CONFIG,configure_bff_logging
from savant.oauth_callback import create_callback_app
from savant.notion_oauth import OAuthError
configure_bff_logging()
warnings.warn('synthetic-warning-secret')
async def finish(state,code,error):
    logging.getLogger('azure.synthetic').warning('Authorization: Bearer synthetic-bearer Cookie: synthetic-cookie access_token=synthetic-access refresh_token=synthetic-refresh client_secret=synthetic-client')
    logging.getLogger('httpx').info('https://private.example?code=synthetic-code')
    if code == 'reject': raise OAuthError('synthetic-provider-secret')
    if code == 'fail': raise RuntimeError('synthetic-exception-secret')
app=create_callback_app(SimpleNamespace(store=SimpleNamespace(),finish=finish))
@app.get('/failure')
async def failure():
    raise RuntimeError('synthetic-unhandled-secret')
uvicorn.run(app,host='127.0.0.1',port=int(sys.argv[1]),log_config=LOGGING_CONFIG,access_log=True)
'''
    env = {'PATH': os.environ['PATH'], 'PYTHONPATH': str(Path('src').resolve())}
    process = subprocess.Popen([sys.executable, '-c', source, str(port)], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    def get(path):
        request = urllib.request.Request(f'http://127.0.0.1:{port}{path}', headers={
            'Authorization': 'Bearer synthetic-bearer', 'Cookie': 'session=synthetic-cookie'})
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code
    try:
        for _ in range(100):
            try:
                if get('/readiness') == 200: break
            except urllib.error.URLError:
                time.sleep(.05)
        else:
            pytest.fail('Synthetic server did not start')
        for code, status in [('synthetic-code', 200), ('reject', 400), ('fail', 503)]:
            assert get('/oauth/notion/callback?state=synthetic-state&code='+code+'&error=synthetic-error') == status
        assert get('/failure?code=synthetic-code') == 500
    finally:
        process.terminate()
        output, _ = process.communicate(timeout=10)
    assert 'synthetic' not in output
    assert '/oauth/' not in output and 'Authorization' not in output and 'Cookie' not in output
    for event in ['oauth_callback_completed','oauth_callback_rejected','oauth_callback_failed','bff_server_error','bff_dependency_warning']:
        assert event in output


def test_startup_failure_does_not_print_exception_or_credentials():
    source = '''
import savant.oauth_runtime as runtime
import dotenv
from savant.oauth_callback import main
dotenv.load_dotenv=lambda **kwargs: None
def fail(*args): raise RuntimeError('synthetic-startup-secret')
runtime.build_oauth_service=fail
main()
'''
    result = subprocess.run([sys.executable, '-c', source], capture_output=True, text=True,
                            env={'PATH':os.environ['PATH'],'PYTHONPATH':str(Path('src').resolve())})
    assert result.returncode == 1
    assert result.stderr.strip() == 'ERROR bff_startup_failed'
    assert not result.stdout


def _relay_record(**extra):
    record = logging.LogRecord('savant.bff', logging.WARNING, 'synthetic-private-path', 1, 'chat_relay_failed', (), None)
    for name, value in extra.items():
        setattr(record, name, value)
    return record


@pytest.mark.parametrize('extra,expected', [
    ({'agent_status': 400}, 'WARNING chat_relay_failed status=400'),
    ({'error_type': 'ConnectError'}, 'WARNING chat_relay_failed type=ConnectError'),
    ({}, 'WARNING chat_relay_failed'),
    ({'agent_status': '400 synthetic-secret'}, 'WARNING chat_relay_failed'),
    ({'agent_status': True}, 'WARNING chat_relay_failed'),
    ({'agent_status': 99999}, 'WARNING chat_relay_failed'),
    ({'error_type': 'synthetic secret=1'}, 'WARNING chat_relay_failed'),
    ({'error_type': 'A' * 80}, 'WARNING chat_relay_failed'),
])
def test_relay_failures_expose_only_a_status_code_or_exception_name(extra, expected):
    assert SafeFormatter().format(_relay_record(**extra)) == expected


def test_relay_detail_is_ignored_for_other_events():
    record = logging.LogRecord('azure.core', logging.WARNING, 'synthetic-private-path', 1, 'chat_relay_failed', (), None)
    record.agent_status = 400
    assert SafeFormatter().format(record) == 'WARNING bff_dependency_warning'


@pytest.mark.parametrize('event', ['chat_stream_failed', 'warmup_failed'])
def test_stream_and_warmup_failures_use_the_same_safe_detail(event):
    record = logging.LogRecord('savant.bff', logging.WARNING, 'synthetic-private-path', 1, event, (), None)
    record.error_type = 'ConnectError'
    assert SafeFormatter().format(record) == f'WARNING {event} type=ConnectError'
    record.error_type = 'synthetic secret=1'
    assert SafeFormatter().format(record) == f'WARNING {event}'
