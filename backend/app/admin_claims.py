"""Grant or revoke the Firebase admin custom claim from a trusted local CLI."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import firebase_admin
from dotenv import load_dotenv
from firebase_admin import auth, credentials

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def initialize_firebase() -> None:
    project_id = os.getenv("FIREBASE_PROJECT_ID")
    if not project_id:
        raise SystemExit("FIREBASE_PROJECT_ID is required in the repository-root .env file.")
    try:
        firebase_admin.get_app()
        return
    except ValueError:
        pass

    credential_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    credential = credentials.Certificate(credential_path) if credential_path else credentials.ApplicationDefault()
    firebase_admin.initialize_app(credential, {"projectId": project_id})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("grant", "revoke"), help="Grant or revoke admin access")
    parser.add_argument("email", help="Email address of an existing Firebase user")
    args = parser.parse_args()

    initialize_firebase()
    try:
        user = auth.get_user_by_email(args.email)
    except auth.UserNotFoundError as exc:
        raise SystemExit(f"No Firebase user exists for {args.email!r}.") from exc

    claims = dict(user.custom_claims or {})
    if args.action == "grant":
        claims["admin"] = True
    else:
        claims.pop("admin", None)
    auth.set_custom_user_claims(user.uid, claims or None)
    verb = "granted" if args.action == "grant" else "revoked"
    print(f"Admin claim {verb} for {user.email} ({user.uid}).")
    print("The user must refresh their ID token before the updated claim is reflected.")


if __name__ == "__main__":
    main()
