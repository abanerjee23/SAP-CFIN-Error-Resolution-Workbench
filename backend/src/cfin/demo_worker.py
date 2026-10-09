"""Process only the configured synthetic demo workspace using the existing worker."""
import argparse
import asyncio
import json
import multiprocessing
import signal
import time
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from fastapi import HTTPException

from cfin.config import Settings
from cfin.gateway import ServiceGateway
from cfin.worker import process_one


async def process_demo_once(cloud: ServiceGateway, settings: Settings, worker_id: str) -> dict:
    if not (settings.local_demo_enabled and settings.demo_workspace_id
            and settings.models_configured):
        raise RuntimeError('Enable the local demo and bounded model execution first')
    workspace_id = str(settings.demo_workspace_id)
    workspaces = await cloud.rows('workspaces', {'id': 'eq.' + workspace_id})
    if (len(workspaces) != 1 or workspaces[0].get('id') != workspace_id
            or workspaces[0].get('synthetic') is not True):
        raise RuntimeError('A synthetic demo workspace is required')
    jobs = await cloud.rows('jobs', {
        'workspace_id': 'eq.' + workspace_id, 'state': 'in.(queued,running)',
        'available_at': 'lte.' + datetime.now(UTC).isoformat(),
        'order': 'available_at.asc,id.asc', 'limit': '25',
    })
    for job in jobs:
        if job.get('workspace_id') != workspace_id:
            raise RuntimeError('Queue response is outside the configured demo workspace')
        runs = await cloud.rows('analysis_runs', {
            'workspace_id': 'eq.' + workspace_id, 'id': 'eq.' + job['run_id'],
            'workflow_version': 'eq.error-analysis-v1',
        })
        if not runs:
            continue
        if (len(runs) != 1 or runs[0].get('workspace_id') != workspace_id
                or runs[0].get('id') != job['run_id']
                or runs[0].get('workflow_version') != 'error-analysis-v1'):
            raise RuntimeError('Run response does not match the demo job')
        result = await process_one(cloud, settings, worker_id, target_run_id=job['run_id'])
        if result.get('claimed'):
            return result
    return {'claimed': False}


async def run(once: bool) -> None:
    settings = Settings()
    worker_id = 'cfin-demo-' + str(uuid4())
    async with httpx.AsyncClient(timeout=20) as client:
        cloud = ServiceGateway(settings, client)
        transient_failures = 0
        while True:
            try:
                result = await process_demo_once(cloud, settings, worker_id)
            except (HTTPException, httpx.RequestError) as exc:
                status = exc.status_code if isinstance(exc, HTTPException) else None
                if once or (status is not None and status not in (408, 429) and status < 500):
                    raise
                transient_failures += 1
                delay = min(30, 2 ** min(transient_failures, 5))
                print(json.dumps({'event': 'demo_worker_retry', 'status': status,
                                  'retry_in_seconds': delay}), flush=True)
                await asyncio.sleep(delay)
                continue
            transient_failures = 0
            if result.get('claimed') or once:
                print(json.dumps({key: result.get(key) for key in
                                  ('claimed', 'run_id', 'succeeded', 'promoted')}), flush=True)
            if once:
                return
            await asyncio.sleep(3)


def run_worker(once: bool) -> None:
    """Each process owns its event loop and Arize's global instrumentation."""
    asyncio.run(run(once))


def run_workers(count: int) -> None:
    """Supervise a fixed process pool; the database independently caps claims."""
    if count not in (1, 2):
        raise ValueError('The demo permits one or two workers')
    context = multiprocessing.get_context('spawn')
    children = [context.Process(target=run_worker, args=(False,), name=f'cfin-demo-{i + 1}')
                for i in range(count)]

    def stop(signum, frame):
        raise SystemExit(0)

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        for child in children:
            child.start()
        while all(child.is_alive() for child in children):
            time.sleep(0.5)
        raise RuntimeError('A demo worker exited; restart the worker supervisor')
    finally:
        signal.signal(signal.SIGTERM, previous)
        for child in children:
            if child.pid is not None and child.is_alive():
                child.terminate()
        for child in children:
            if child.pid is not None:
                child.join(timeout=10)
                if child.is_alive():
                    child.kill()
                    child.join(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--workers', type=int, choices=(1, 2), default=2,
                        help='Independent worker processes (default: 2; --once runs one job)')
    args = parser.parse_args()
    try:
        if args.once or args.workers == 1:
            run_worker(args.once)
        else:
            run_workers(args.workers)
    except (RuntimeError, HTTPException, httpx.RequestError):
        parser.exit(2, 'Demo worker stopped; check configuration and saved run records.\n')


if __name__ == '__main__':
    main()
