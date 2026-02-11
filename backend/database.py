import sqlite3
import os
from .config import ModelConfig

# 定义数据库路径
DB_PATH = ModelConfig.DB_PATH

def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 允许通过列名访问
    return conn

def init_db():
    """初始化数据库表结构"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. 工单表 (tickets)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending_ai',  -- pending_ai, queued, in_progress, resolved, rated
        summary TEXT,
        score INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 2. 消息表 (messages)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        sender TEXT NOT NULL, -- user, ai, agent
        content TEXT NOT NULL,
        type TEXT DEFAULT 'text',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (ticket_id) REFERENCES tickets (id)
    )
    ''')

    # 3. QA 知识库表 (knowledge_qa)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS knowledge_qa (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        source TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 4. 向量知识库表 (knowledge_vector)
    # 注意: embedding 字段存储为 BLOB (numpy array bytes)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS knowledge_vector (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        embedding BLOB NOT NULL,
        source TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.commit()
    conn.close()
    print(f"Dataset initialized at: {DB_PATH}")

if __name__ == "__main__":
    init_db()
