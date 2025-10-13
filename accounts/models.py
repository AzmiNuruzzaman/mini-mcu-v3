# accounts/models.py

from dataclasses import dataclass
from typing import Optional

@dataclass
class User:
    """
    Minimal User model for reference.
    We use Supabase 'users' table for actual data storage.
    """
    username: str
    role: str
    uid: Optional[str] = None
    password: Optional[str] = None  # hashed password
