"""
Gemini API 客户端模块

处理 Google Gemini API 的配置和初始化
"""

import logging

import google.generativeai as genai

from config import GEMINI_API_KEY
from utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# 默认初始化
model = None
vision_model = None
GEMINI_AVAILABLE = False

# 创建 Gemini API 请求限流器 (15 RPM = 每分钟 15 次请求)
gemini_limiter = RateLimiter(max_calls=15, time_frame=60)


def configure_gemini_api():
    """
    配置 Google Gemini API 并初始化模型

    返回：
        bool: 配置是否成功
    """
    global model, vision_model, GEMINI_AVAILABLE

    try:
        if not GEMINI_API_KEY:
            logger.warning("未设置 GEMINI_API_KEY，Gemini 功能将不可用")
            return False

        genai.configure(api_key=GEMINI_API_KEY)

        # 初始化原始模型
        _model = genai.GenerativeModel("gemini-2.5-flash-lite")
        _vision_model = genai.GenerativeModel("gemini-2.5-flash")

        # 为 generate_content 方法添加速率限制
        model = _create_rate_limited_model(_model)
        vision_model = _create_rate_limited_model(_vision_model)

        GEMINI_AVAILABLE = True
        logger.info("Gemini API 配置成功，已启用请求频率限制 (15 RPM)")
        return True
    except Exception as e:
        logger.error(f"配置 Gemini API 时出错：{e}")
        GEMINI_AVAILABLE = False
        return False


def _create_rate_limited_model(original_model):
    """
    创建具有请求频率限制的模型包装器

    参数：
        original_model: 原始 Gemini 模型

    返回：
        具有相同接口但有请求限制的模型对象
    """

    # 包装原始模型，不修改其他属性和方法
    class RateLimitedModel:
        def __init__(self, model):
            self._model = model
            # 包装 generate_content 方法
            self.generate_content = gemini_limiter(model.generate_content)

        def __getattr__(self, name):
            # 对于其他方法和属性，直接代理到原始模型
            return getattr(self._model, name)

    return RateLimitedModel(original_model)


# 自动初始化
configure_gemini_api()
