"""Run every Python test in CI with no provider key, outbound sockets, or skips."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run():
    # A missing dependency must fail CI, rather than silently skipping API tests.
    import flask  # noqa: F401
    import anthropic  # noqa: F401

    os.environ.pop('ANTHROPIC_API_KEY', None)
    os.environ.pop('CHAT_ACCESS_TOKEN', None)
    network_attempts = []

    def block_network(*args, **kwargs):
        network_attempts.append(True)
        raise AssertionError('Outbound network calls are forbidden during tests')

    with ExitStack() as stack:
        for target in ('socket.socket.connect', 'socket.socket.connect_ex',
                       'socket.socket.sendto', 'socket.create_connection', 'socket.getaddrinfo'):
            stack.enter_context(patch(target, side_effect=block_network))
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
        result = unittest.TextTestRunner(verbosity=2).run(suite)

    if network_attempts:
        print('FAIL: tests attempted outbound network access', file=sys.stderr)
    if result.skipped:
        print('FAIL: CI must run all tests without skips', file=sys.stderr)
    print(f'Python/API tests: {result.testsRun} run, {len(result.skipped)} skipped; '
          f'outbound network attempts: {len(network_attempts)}')
    return 0 if (result.wasSuccessful() and result.testsRun > 0
                 and not result.skipped and not network_attempts) else 1


if __name__ == '__main__':
    sys.exit(run())
