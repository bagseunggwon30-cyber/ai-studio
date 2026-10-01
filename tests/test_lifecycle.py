"""Lifecycle regressions: temporary companies only; no authenticated runtimes."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from studio import gitops, runtimes
from studio.store import Store, StoreLockedError, StaleTaskError
from tests.helpers import TempStudio
from tests.test_engine import build_task


class ProcessLockTests(unittest.TestCase):
    def test_same_process_contenders_and_nonowner_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Store(Path(tmp)), Store(Path(tmp))
            first.acquire_process_lock()
            try:
                first.acquire_process_lock()  # idempotent only for the owner
                with self.assertRaises(StoreLockedError):
                    second.acquire_process_lock()
                second.release_process_lock()
                with self.assertRaises(StoreLockedError):
                    second.acquire_process_lock()
            finally:
                first.release_process_lock()
            self.assertTrue((Path(tmp) / 'studio.lock').exists())
            second.acquire_process_lock()
            second.release_process_lock()

    def test_concurrent_processes_and_owner_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = '''
import sys, time
from pathlib import Path
from studio.store import Store, StoreLockedError
s = Store(Path(sys.argv[1]))
try:
    s.acquire_process_lock()
except StoreLockedError:
    print('locked', flush=True)
else:
    print('owner', flush=True)
    time.sleep(30)
'''
            children = [subprocess.Popen([sys.executable, '-c', script, tmp], stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True) for _ in range(4)]
            try:
                results = [p.stdout.readline().strip() for p in children]
                self.assertEqual(results.count('owner'), 1, results)
                self.assertEqual(results.count('locked'), 3, results)
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.communicate(timeout=5)
            successor = Store(Path(tmp))
            successor.acquire_process_lock()
            successor.release_process_lock()

    def test_stale_task_cannot_erase_cancellation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            stale = store.create_task(title='test', kind='plan', role='producer', project='', status='queued')
            fresh = store.get(stale.id)
            store.transition(fresh, 'cancelled')
            history = store.get(stale.id).history
            with self.assertRaises(StaleTaskError):
                store.save(stale)
            with self.assertRaises(StaleTaskError):
                store.transition(stale, 'running')
            self.assertEqual(store.get(stale.id).history, history)
            self.assertEqual(store.get(stale.id).status, 'cancelled')


class ChildProcessTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'POSIX process-group regression')
    def test_timeout_isolates_and_reaps_child(self):
        # Run in a separate supervisor so the regression cannot kill the test runner.
        script = '''
import os, sys, tempfile
from pathlib import Path
from studio.runtimes import run_process
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    code, reason, duration = run_process(
        [sys.executable, '-c', 'import time; time.sleep(30)'], cwd=root,
        stdin_text='', stdout_path=root/'out', stderr_path=root/'err',
        timeout_s=0, should_stop=lambda: False, env=dict(os.environ))
    assert code is not None and reason == 'timeout', (code, reason)
print('supervisor survived')
'''
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('supervisor survived', result.stdout)

    def test_already_stopped_does_not_launch(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(runtimes.subprocess, 'Popen') as launch:
            root = Path(tmp)
            code, reason, _ = runtimes.run_process(['child'], cwd=root, stdin_text='',
                stdout_path=root/'out', stderr_path=root/'err', timeout_s=60,
                should_stop=lambda: True, env={})
        self.assertIsNone(code)
        self.assertEqual(reason, 'stopped')
        launch.assert_not_called()

    def test_slow_termination_is_reaped_before_return(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired('child', 15), -9]
        proc.returncode = -9
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(runtimes.subprocess, 'Popen', return_value=proc), \
                mock.patch.object(runtimes, 'kill_tree') as kill:
            root = Path(tmp)
            code, reason, _ = runtimes.run_process(['child'], cwd=root, stdin_text='',
                stdout_path=root/'out', stderr_path=root/'err', timeout_s=60,
                should_stop=mock.Mock(side_effect=[False, True]), env={})
        self.assertEqual(reason, 'stopped')
        self.assertEqual(code, -9)
        self.assertEqual(kill.call_count, 2)
        proc.kill.assert_called_once()
        self.assertEqual(proc.wait.call_args_list, [mock.call(15), mock.call()])


class EngineLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.company = TempStudio()
        self.engine = self.company.engine
        self.store = self.company.store

    def tearDown(self):
        self.company.close()

    def test_cancel_during_staging_is_terminal(self):
        task = build_task(self.engine)
        original = gitops.staged_changes
        cancelled_history = []
        def staging(*args, **kwargs):
            if not cancelled_history:
                self.engine.cancel(task.id)
                cancelled_history.extend(self.store.get(task.id).history)
            return original(*args, **kwargs)
        with mock.patch.object(gitops, 'staged_changes', side_effect=staging), \
                mock.patch('studio.engine.run_qa') as qa, mock.patch.object(self.engine, '_review') as review:
            self.engine._run_build(self.store.get(task.id))
        fresh = self.store.get(task.id)
        self.assertEqual(fresh.status, 'cancelled')
        self.assertEqual(fresh.history, cancelled_history)
        qa.assert_not_called()
        review.assert_not_called()

    def test_shutdown_reaches_runtime_predicate(self):
        task = build_task(self.engine)
        observed = []
        runtime = mock.Mock()
        from studio.runtimes import RunResult
        def run(spec, stop):
            self.engine._shutdown.set()
            observed.append(stop())
            return RunResult(False, 'fake', '', -9, 0, error_kind='stopped', error='stopped')
        runtime.run.side_effect = run
        self.engine.runtime_factory = lambda name: runtime
        self.engine._run_build(self.store.get(task.id))
        self.assertEqual(observed, [True])
        self.assertEqual(self.store.get(task.id).status, 'blocked')

    def test_shutdown_reaches_qa_and_blocks_review(self):
        task = build_task(self.engine)
        observed = []
        def qa(cfg, project, sha, out, stop, **kwargs):
            self.engine._shutdown.set()
            observed.append(stop())
            return {'verdict': 'stopped', 'reason': 'stopped'}
        with mock.patch('studio.engine.run_qa', side_effect=qa), mock.patch.object(self.engine, '_review') as review:
            self.engine._run_build(self.store.get(task.id))
        self.assertEqual(observed, [True])
        self.assertEqual(self.store.get(task.id).status, 'blocked')
        review.assert_not_called()

    def test_shutdown_before_agent_does_not_construct_runtime(self):
        task = build_task(self.engine)
        self.engine._shutdown.set()
        factory = mock.Mock()
        self.engine.runtime_factory = factory
        result = self.engine._agent_run(task, 'builder', 'prompt', self.company.root,
                                        sandbox='workspace-write', stage='build1')
        self.assertEqual(result.error_kind, 'stopped')
        factory.assert_not_called()

    def test_shutdown_during_staging_prevents_qa(self):
        task = build_task(self.engine)
        original = gitops.staged_changes
        def staging(*args, **kwargs):
            self.engine._shutdown.set()
            return original(*args, **kwargs)
        with mock.patch.object(gitops, 'staged_changes', side_effect=staging), \
                mock.patch('studio.engine.run_qa') as qa:
            self.engine._run_build(self.store.get(task.id))
        qa.assert_not_called()
        self.assertEqual(self.store.get(task.id).status, 'blocked')

    def test_shutdown_after_passing_qa_prevents_review(self):
        task = build_task(self.engine)
        def qa(*args, **kwargs):
            self.engine._shutdown.set()
            return {'verdict': 'pass', 'reason': 'ok'}
        with mock.patch('studio.engine.run_qa', side_effect=qa), \
                mock.patch.object(self.engine, '_review') as review:
            self.engine._run_build(self.store.get(task.id))
        review.assert_not_called()
        self.assertEqual(self.store.get(task.id).status, 'blocked')

    def test_shutdown_reports_worker_still_alive(self):
        release = threading.Event()
        self.engine._thread = threading.Thread(target=release.wait)
        self.engine._thread.start()
        try:
            self.assertFalse(self.engine.shutdown(0.01))
        finally:
            release.set()
            self.assertTrue(self.engine.shutdown(None))


class ServerShutdownTests(unittest.TestCase):
    def test_worker_join_precedes_lock_release(self):
        from studio import server
        events = []
        cfg = mock.Mock(fake_runtimes=True, port=8765, name='Test')
        store = mock.Mock()
        engine = mock.Mock()
        srv = mock.Mock()
        srv.remote.settings.return_value = {'lan': False}
        srv.serve_forever.side_effect = KeyboardInterrupt
        engine.shutdown.side_effect = lambda timeout: events.append(('joined', timeout))
        store.release_process_lock.side_effect = lambda: events.append(('released',))
        with mock.patch.object(server, 'Store', return_value=store), \
                mock.patch.object(server, 'Engine', return_value=engine), \
                mock.patch.object(server, 'StudioServer', return_value=srv), mock.patch('builtins.print'):
            server.serve(cfg, open_browser=False)
        self.assertEqual(events, [('joined', None), ('released',)])
