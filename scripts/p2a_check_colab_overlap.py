#!/usr/bin/env python3
"""Refuse a P2a smoke while another Colab training workflow is active."""
import json
import os
import urllib.error
import urllib.request


def other_active_runs(runs, current_run_id):
    current = str(current_run_id)
    return [run for run in runs
            if str(run.get('id')) != current
            and run.get('status') in ('queued', 'in_progress')]


def check_overlap(repository, current_run_id, token, opener=urllib.request.urlopen):
    request = urllib.request.Request(
        f'https://api.github.com/repos/{repository}/actions/workflows/run-colab.yml/runs?per_page=100',
        headers={'Accept':'application/vnd.github+json',
                 'Authorization':f'Bearer {token}',
                 'X-GitHub-Api-Version':'2022-11-28',
                 'User-Agent':'vn-stock-ai-p2a-smoke'},
    )
    try:
        with opener(request, timeout=30) as response:
            payload=json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'GitHub workflow overlap query failed HTTP {error.code}') from None
    active=other_active_runs(payload.get('workflow_runs',[]),current_run_id)
    if active:
        raise RuntimeError(f'{len(active)} other Colab training workflow(s) queued or active; refusing GPU allocation')
    return len(active)


def main():
    repository=os.environ.get('GITHUB_REPOSITORY','')
    run_id=os.environ.get('GITHUB_RUN_ID','')
    token=os.environ.get('GITHUB_TOKEN','')
    if not repository or not run_id or not token:
        raise SystemExit('GITHUB_REPOSITORY, GITHUB_RUN_ID and GITHUB_TOKEN are required for overlap guard')
    check_overlap(repository,run_id,token)
    print('No other Colab training workflow is queued or active; safe to allocate smoke GPU.')


if __name__=='__main__':
    main()
