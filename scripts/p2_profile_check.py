#!/usr/bin/env python3
"""Verify a Liaison-installed named Colab profile without printing credentials."""
import argparse
import os
import stat
from pathlib import Path

ALLOWED = {
    'train': ('train_tk4', 'train_tk5', 'train_tk1', 'train_tk6'),
    'eval': ('eval_tk2', 'eval_tk3', 'eval_tk5'),
}


def verify_profile(kind, profile, home=None):
    if kind not in ALLOWED or profile not in ALLOWED[kind]:
        raise ValueError('unknown Colab credential profile')
    root = Path(home) if home else Path.home() / '.config' / 'vncolab'
    token_file = root / profile / 'token.json'
    if not token_file.is_file():
        raise FileNotFoundError(f'credential profile {profile} is not installed')
    if stat.S_IMODE(token_file.stat().st_mode) & 0o077:
        raise PermissionError(f'credential profile {profile} must be mode 0600')
    suffix = profile.removeprefix('train_').removeprefix('eval_').upper()
    expected = os.environ.get(f'P2_{kind.upper()}_{suffix}_EMAIL', '').strip()
    if not expected:
        raise RuntimeError(f'expected identity is not configured for profile {profile}')
    from google.auth.transport.requests import AuthorizedSession, Request
    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_file(str(token_file))
    if not creds.valid:
        if not creds.expired or not creds.refresh_token:
            raise RuntimeError(f'credential profile {profile} cannot refresh')
        creds.refresh(Request())
    response = AuthorizedSession(creds).get(
        'https://www.googleapis.com/oauth2/v1/userinfo?alt=json', timeout=30)
    response.raise_for_status()
    actual = (response.json().get('email') or '').strip()
    if not actual or actual.casefold() != expected.casefold():
        raise RuntimeError(f'credential identity verification failed for profile {profile}')
    return {'profile': profile, 'verified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=tuple(ALLOWED), required=True)
    parser.add_argument('--profile', required=True)
    args = parser.parse_args()
    result = verify_profile(args.kind, args.profile)
    print(f"PROFILE_VERIFIED kind={args.kind} profile={result['profile']}")


if __name__ == '__main__':
    main()
