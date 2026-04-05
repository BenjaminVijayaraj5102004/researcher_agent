import os
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self):
        self.supabase_url = os.getenv("SUPABASE_URL", "")
        self.supabase_key = os.getenv("SUPABASE_KEY", "")
        self._client = None
        self._connected = False

    def _get_client(self):
        if self._client and self._connected:
            return self._client
        if not self.supabase_url or not self.supabase_key:
            logger.warning("Supabase not configured — running in memory-only mode.")
            return None
        try:
            from supabase import create_client
            self._client = create_client(self.supabase_url, self.supabase_key)
            self._connected = True
            return self._client
        except Exception as e:
            logger.error(f"Supabase connection failed: {e}")
            return None

    async def save_research(self, record) -> Optional[Dict]:
        client = self._get_client()
        if not client:
            return {"id": record.id}
        try:
            data = {k: v for k, v in {
                "id": record.id, "topic": record.topic, "status": record.status,
                "created_at": record.created_at,
            }.items() if v is not None}
            resp = client.table("research_sessions").insert(data).execute()
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"DB save error: {e}")
            return None

    async def update_research(self, research_id: str, updates: Dict[str, Any]) -> Optional[Dict]:
        client = self._get_client()
        if not client:
            return {"id": research_id}
        try:
            serialized = {}
            for k, v in updates.items():
                if hasattr(v, "model_dump"):
                    serialized[k] = v.model_dump()
                elif hasattr(v, "value"):
                    serialized[k] = v.value
                else:
                    serialized[k] = v
            resp = client.table("research_sessions").update(serialized).eq("id", research_id).execute()
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"DB update error: {e}")
            return None

    async def get_all_research(self, limit: int = 50) -> List[Dict]:
        client = self._get_client()
        if not client:
            return []
        try:
            resp = (
                client.table("research_sessions")
                .select("id, topic, status, created_at, completed_at")
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return resp.data or []
        except Exception as e:
            logger.error(f"DB fetch error: {e}")
            return []

    async def get_research(self, research_id: str) -> Optional[Dict]:
        client = self._get_client()
        if not client:
            return None
        try:
            resp = client.table("research_sessions").select("*").eq("id", research_id).single().execute()
            return resp.data
        except Exception as e:
            logger.error(f"DB get error: {e}")
            return None
