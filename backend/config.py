import os
from openai import OpenAI
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

class ModelConfig:
    """
    统一模型配置中心
    管理 DeepSeek (意图/问答) 和 Qwen (向量化) 的配置
    """

    # ==============================
    # 1. 业务数据库配置 (SQLite)
    # ==============================
    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "customer_service.db")

    # ==============================
    # 2. 对话/意图模型配置 (DeepSeek)
    # ==============================
    # 使用 DeepSeek 进行意图识别和最终的 RAG 回复生成
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "") # 请在系统变量中设置或在此填入
    DEEPSEEK_BASE_URL = "https://api.deepseek.com"
    DEEPSEEK_MODEL_NAME = "deepseek-chat" # 或 deepseek-reasoner

    # ==============================
    # 3. 向量化模型配置 (Aliyun Qwen)
    # ==============================
    # 使用阿里云百炼 (DashScope) 的 text-embedding-v4 进行知识库切片向量化
    # 注意：新加坡和北京地域 Base URL 不同，默认使用北京配置
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "") # 请在系统变量中设置或在此填入
    # 兼容 OpenAI 格式的 Base URL
    DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1" 
    EMBEDDING_MODEL_NAME = "text-embedding-v4"
    
    # Qwen text-embedding-v4 输出维度 (用于创建数据库表结构)
    # 通常 v3/v4 是 1024 维，具体需参考阿里文档或动态获取，这里默认配置为 1536 (兼容OpenAI) 或 1024
    # 暂定 768/1024/1536，建议首次运行时校验
    EMBEDDING_DIM = 1536 

    @classmethod
    def get_chat_client(cls) -> OpenAI:
        """获取用于对话/意图识别的 DeepSeek 客户端"""
        if not cls.DEEPSEEK_API_KEY:
             raise ValueError("⚠️ 未配置 DEEPSEEK_API_KEY，请检查环境变量或配置文件")
        
        return OpenAI(
            api_key=cls.DEEPSEEK_API_KEY,
            base_url=cls.DEEPSEEK_BASE_URL
        )

    @classmethod
    def get_embedding_client(cls) -> OpenAI:
        """获取用于向量化的 Qwen (DashScope) 客户端"""
        if not cls.DASHSCOPE_API_KEY:
            raise ValueError("⚠️ 未配置 DASHSCOPE_API_KEY，请检查环境变量或配置文件")

        return OpenAI(
            api_key=cls.DASHSCOPE_API_KEY,
            base_url=cls.DASHSCOPE_BASE_URL
        )

# 使用示例
if __name__ == "__main__":
    try:
        # 测试 DeepSeek 客户端连接
        chat_client = ModelConfig.get_chat_client()
        print(f"DeepSeek Client Ready. Base URL: {chat_client.base_url}")

        # 测试 Qwen Embedding 客户端连接
        emb_client = ModelConfig.get_embedding_client()
        print(f"Qwen Client Ready. Base URL: {emb_client.base_url}")
        
    except Exception as e:
        print(f"Configuration Error: {e}")
