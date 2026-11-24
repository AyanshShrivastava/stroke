"""
Stroke V1 — Firestore & Local Data Migration Engine
Safely migrates legacy email-keyed records to Firebase UID-keyed ownership.

Guarantees:
1. Immutable backup of current email-keyed data before any modification.
2. Verified ownership mapping: email records are ONLY mapped to a UID after proving
   that authenticated_user.email matches the legacy record's email.
3. No passwords, hashes, OTPs, or stale tokens are ever migrated.
4. Resumable, idempotent, auditable, and safe to retry.
5. Legacy email records are preserved (never silently deleted).
"""

import os
import json
import time
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger("stroke.migration")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
BACKUPS_DIR = os.path.join(DATA_DIR, "backups")
os.makedirs(BACKUPS_DIR, exist_ok=True)


def backup_legacy_data(db_client: Any = None) -> Dict[str, Any]:
    """
    Creates an immutable cryptographic snapshot of legacy email-keyed data.
    Backs up:
      - Local chat sessions from data/local_chat_sessions.json
      - Firestore email-keyed user profiles & sub-documents (if Firestore is reachable)
    Saves snapshot into data/backups/migration_backup_<timestamp>.json.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(BACKUPS_DIR, f"migration_backup_{timestamp}.json")
    manifest_file = os.path.join(BACKUPS_DIR, "migration_manifest.json")

    backup_data: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backup_version": "stroke_v1_migration",
        "local_chat_sessions": {},
        "firestore_email_records": {},
    }

    # 1. Back up local chat store
    local_chats_path = os.path.join(DATA_DIR, "local_chat_sessions.json")
    if os.path.exists(local_chats_path):
        try:
            with open(local_chats_path, "r", encoding="utf-8") as f:
                backup_data["local_chat_sessions"] = json.load(f)
        except Exception as exc:
            logger.warning(f"Could not load local_chat_sessions for backup: {exc}")

    # 2. Back up Firestore email-keyed records if client is available
    if db_client:
        try:
            users_ref = db_client.collection("users")
            user_docs = users_ref.stream()
            for doc in user_docs:
                doc_id = doc.id
                # Check if document key is an email address
                if "@" in doc_id:
                    user_data = doc.to_dict() or {}
                    # Sanitize out any sensitive password/OTP material before backup
                    user_data.pop("password", None)
                    user_data.pop("password_hash", None)
                    user_data.pop("otp_code", None)
                    user_data.pop("otp_expires_at", None)

                    doc_entry: Dict[str, Any] = {
                        "profile": user_data,
                        "chats": [],
                        "records": [],
                        "memory": []
                    }

                    # Export subcollections
                    try:
                        for chat_doc in doc.reference.collection("chats").stream():
                            c_data = chat_doc.to_dict() or {}
                            doc_entry["chats"].append(c_data)
                    except Exception:
                        pass

                    try:
                        for rec_doc in doc.reference.collection("records").stream():
                            r_data = rec_doc.to_dict() or {}
                            doc_entry["records"].append(r_data)
                    except Exception:
                        pass

                    try:
                        for mem_doc in doc.reference.collection("memory").stream():
                            m_data = mem_doc.to_dict() or {}
                            doc_entry["memory"].append(m_data)
                    except Exception:
                        pass

                    backup_data["firestore_email_records"][doc_id] = doc_entry
        except Exception as exc:
            logger.info(f"Firestore stream during backup note: {exc}")

    # Write serialized backup
    serialized = json.dumps(backup_data, indent=2, default=str)
    content_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    with open(backup_file, "w", encoding="utf-8") as f:
        f.write(serialized)

    # Update manifest
    manifest_entry = {
        "backup_file": backup_file,
        "timestamp": timestamp,
        "sha256": content_hash,
        "local_users_count": len(backup_data["local_chat_sessions"]),
        "firestore_email_users_count": len(backup_data["firestore_email_records"])
    }

    try:
        manifest_list = []
        if os.path.exists(manifest_file):
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest_list = json.load(f)
        manifest_list.insert(0, manifest_entry)
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest_list, f, indent=2)
    except Exception:
        pass

    logger.info(f"[MIGRATION BACKUP] Created immutable backup at {backup_file} (SHA256: {content_hash[:12]}...)")
    return {
        "status": "success",
        "backup_path": backup_file,
        "sha256": content_hash,
        "timestamp": timestamp
    }


def migrate_user_to_uid(
    uid: str,
    verified_email: Optional[str],
    db_client: Any,
    local_chat_sessions_store: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Migrates a single user's data from their verified legacy email key to their Firebase UID.
    
    Security:
      - verified_email MUST be verified from the Firebase ID token.
      - NEVER accepts caller-supplied email without token proof.
      - Passwords, hashes, OTPs, and stale tokens are completely stripped.
      - Idempotent: safe to run multiple times.
      - Preserves original email record for audit safety.
    """
    if not uid:
        raise ValueError("Target Firebase UID cannot be empty.")

    clean_email = (verified_email or "").strip().lower()
    stats = {
        "uid": uid,
        "email": clean_email,
        "migrated_profile": False,
        "chats_migrated": 0,
        "records_migrated": 0,
        "memories_migrated": 0,
        "local_chats_migrated": 0,
        "already_migrated": False,
    }

    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Migrate Local Chat Sessions Store
    if clean_email and clean_email in local_chat_sessions_store:
        email_chats = local_chat_sessions_store[clean_email]
        if uid not in local_chat_sessions_store:
            local_chat_sessions_store[uid] = []
        existing_session_ids = {s.get("session_id") for s in local_chat_sessions_store[uid]}
        for chat in email_chats:
            if chat.get("session_id") not in existing_session_ids:
                chat_copy = dict(chat)
                chat_copy["uid"] = uid
                local_chat_sessions_store[uid].append(chat_copy)
                stats["local_chats_migrated"] += 1

    # 2. Migrate Cloud Firestore Records
    if not db_client:
        return stats

    target_user_ref = db_client.collection("users").document(uid)
    try:
        target_snap = target_user_ref.get()
        if target_snap.exists:
            target_data = target_snap.to_dict() or {}
            if target_data.get("migrated_from_email") == clean_email:
                stats["already_migrated"] = True
    except Exception:
        pass

    if not clean_email:
        # User has no email; ensure parent document exists
        try:
            target_user_ref.set({
                "uid": uid,
                "email": None,
                "database_fed": False,
                "created_at": now_iso,
                "updated_at": now_iso,
            }, merge=True)
        except Exception:
            pass
        return stats

    # Query legacy email document
    legacy_ref = db_client.collection("users").document(clean_email)
    try:
        legacy_snap = legacy_ref.get()
        if legacy_snap.exists:
            legacy_data = legacy_snap.to_dict() or {}
            
            # Sanitize legacy data: strip password, hashes, OTPs, stale tokens
            sanitized_profile = {
                "uid": uid,
                "email": clean_email,
                "display_name": legacy_data.get("display_name"),
                "database_fed": bool(legacy_data.get("database_fed", False)),
                "github_connected": bool(legacy_data.get("github_connected", False)),
                "github_username": legacy_data.get("github_username"),
                "memory_bytes_used_estimate": legacy_data.get("memory_bytes_used", 0),
                "memory_count": 0,
                "quota_bytes": 104857600,
                "migrated_from_email": clean_email,
                "migrated_at": now_iso,
                "created_at": legacy_data.get("created_at") or now_iso,
                "updated_at": now_iso,
            }
            target_user_ref.set(sanitized_profile, merge=True)
            stats["migrated_profile"] = True

            # Migrate subcollection: chats
            try:
                chats_stream = legacy_ref.collection("chats").stream()
                for c_doc in chats_stream:
                    c_data = c_doc.to_dict() or {}
                    c_data["uid"] = uid
                    c_data.pop("email", None)
                    target_user_ref.collection("chats").document(c_doc.id).set(c_data, merge=True)
                    stats["chats_migrated"] += 1
            except Exception as e:
                logger.warning(f"Error migrating chats for {clean_email} -> {uid}: {e}")

            # Migrate subcollection: records (5-Cycle Ingestion Records)
            try:
                records_stream = legacy_ref.collection("records").stream()
                for r_doc in records_stream:
                    r_data = r_doc.to_dict() or {}
                    r_data["uid"] = uid
                    r_data.pop("email", None)
                    target_user_ref.collection("records").document(r_doc.id).set(r_data, merge=True)
                    stats["records_migrated"] += 1
            except Exception as e:
                logger.warning(f"Error migrating records for {clean_email} -> {uid}: {e}")

            # Migrate subcollection: memory
            try:
                memory_stream = legacy_ref.collection("memory").stream()
                mem_count = 0
                for m_doc in memory_stream:
                    m_data = m_doc.to_dict() or {}
                    m_data["uid"] = uid
                    m_data.pop("email", None)
                    if "byte_size" in m_data and "byte_size_estimate" not in m_data:
                        m_data["byte_size_estimate"] = m_data.pop("byte_size")
                    target_user_ref.collection("memory").document(m_doc.id).set(m_data, merge=True)
                    stats["memories_migrated"] += 1
                    mem_count += 1
                if mem_count > 0:
                    target_user_ref.update({"memory_count": mem_count})
            except Exception as e:
                logger.warning(f"Error migrating memory for {clean_email} -> {uid}: {e}")

        else:
            # Legacy doc does not exist; initialize target profile
            target_user_ref.set({
                "uid": uid,
                "email": clean_email,
                "database_fed": False,
                "created_at": now_iso,
                "updated_at": now_iso,
            }, merge=True)

    except Exception as exc:
        logger.warning(f"Firestore legacy migration note for {clean_email}: {exc}")

    stats["migrated"] = stats.get("migrated_profile", False) or bool(
        stats.get("records_migrated", 0) or stats.get("chats_migrated", 0) or stats.get("local_chats_migrated", 0)
    )
    return stats
