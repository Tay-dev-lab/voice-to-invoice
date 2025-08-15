import sqlite3
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from contextlib import contextmanager
from pathlib import Path

from config import config

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DATABASE_URL.replace("sqlite:///", "")
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Create sessions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP
                )
            """)
            
            # Create invoices table for completed invoices
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT UNIQUE,
                    invoice_data TEXT NOT NULL,
                    pdf_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                )
            """)
            
            # Create index for faster lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_expires 
                ON sessions(expires_at)
            """)
            
            conn.commit()
            logger.info("Database initialized successfully")
    
    @contextmanager
    def get_connection(self):
        """Get database connection context manager"""
        conn = sqlite3.connect(
            self.db_path,
            timeout=30.0,
            isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def create_session(self, session_id: str, initial_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create a new session"""
        data = initial_data or {
            "step": "start",
            "items": [],
            "created_at": datetime.utcnow().isoformat()
        }
        
        expires_at = datetime.utcnow() + timedelta(hours=24)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sessions (session_id, data, expires_at)
                VALUES (?, ?, ?)
            """, (session_id, json.dumps(data), expires_at))
            
        logger.info(f"Created session: {session_id}")
        return data
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT data, expires_at FROM sessions 
                WHERE session_id = ?
            """, (session_id,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            # Check if session is expired
            expires_at = datetime.fromisoformat(row['expires_at'])
            if expires_at < datetime.utcnow():
                self.delete_session(session_id)
                return None
            
            return json.loads(row['data'])
    
    def update_session(self, session_id: str, data: Dict[str, Any]) -> bool:
        """Update session data"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sessions 
                SET data = ?, updated_at = CURRENT_TIMESTAMP
                WHERE session_id = ?
            """, (json.dumps(data), session_id))
            
            return cursor.rowcount > 0
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a session"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM sessions WHERE session_id = ?
            """, (session_id,))
            
            return cursor.rowcount > 0
    
    def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM sessions 
                WHERE expires_at < CURRENT_TIMESTAMP
            """)
            
            deleted = cursor.rowcount
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} expired sessions")
            
            return deleted
    
    def save_invoice(self, session_id: str, invoice_data: Dict[str, Any], pdf_path: str = None) -> int:
        """Save completed invoice data"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO invoices (session_id, invoice_data, pdf_path)
                VALUES (?, ?, ?)
            """, (session_id, json.dumps(invoice_data), pdf_path))
            
            return cursor.lastrowid
    
    def get_invoice(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get saved invoice data"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT invoice_data, pdf_path, created_at 
                FROM invoices 
                WHERE session_id = ?
            """, (session_id,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            return {
                "data": json.loads(row['invoice_data']),
                "pdf_path": row['pdf_path'],
                "created_at": row['created_at']
            }

# Create global database instance
db = Database()