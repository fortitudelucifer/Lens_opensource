"""
错误处理、日志记录和显存管理模块

功能：
- 定义 Advisor 系统的统一异常层次结构（AdvisorError 基类 + 5 个子类）
- 提供标准化的日志设置（控制台 + 文件双输出）
- GPU 显存管理工具（清理、查询、OOM 自动恢复）
- API 调用安全装饰器（自动重试 + 指数退避）
- 错误日志装饰器（自动捕获并记录异常详情）
- 进度报告器（实时统计处理速度、ETA、错误率）

处理流程：
1. 异常体系：AdvisorError → ConfigError / ModelError / APIError / DataError / OOMError
2. OOM 处理：捕获 CUDA OOM → 清理显存 → 自动减半 batch_size → 重试
3. API 重试：捕获可重试错误（限流/超时/5xx）→ 指数退避等待 → 重试
4. 进度报告：实时计算处理速率和 ETA，支持错误计数

输入：
- 各模块的函数调用（通过装饰器模式集成）

输出：
- 日志文件（可选）
- 控制台日志输出
- 进度统计摘要

依赖：
- torch: GPU 显存管理（torch.cuda）
- logging: Python 标准日志库

使用示例：
    # 设置日志
    from scripts.advisor.errors import setup_logging
    logger = setup_logging('INFO', 'logs/advisor.log')
    
    # OOM 自动恢复装饰器
    from scripts.advisor.errors import handle_oom
    @handle_oom(reduce_batch_size=True)
    def train_step(batch_size=4):
        ...
    
    # API 安全调用装饰器
    from scripts.advisor.errors import safe_api_call
    @safe_api_call(max_retries=3, exponential_backoff=True)
    def call_openai(prompt):
        ...
    
    # 进度报告
    from scripts.advisor.errors import ProgressReporter
    reporter = ProgressReporter(total=100, desc="生成分析")
    reporter.update(1)
    reporter.report()

性能参考：
- clear_gpu_memory() 耗时约 50-200ms（取决于显存碎片程度）
- 指数退避最大等待时间 = retry_delay × 2^(max_retries-1)

注意事项：
- OOM 装饰器会自动减半 batch_size 直到 min_batch_size，无法再减时抛出 OOMError
- safe_api_call 仅对特定错误关键词（rate limit, timeout, 5xx 等）进行重试
- ProgressReporter 非线程安全，多线程场景需外部加锁

作者：[Author]
更新于：2026-02-15
"""

import functools
import gc
import logging
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

import torch

# 类型变量
T = TypeVar('T')


# =============================================================================
# 自定义异常
# =============================================================================

class AdvisorError(Exception):
    """顾问模块基础异常
    
    所有 Advisor 系统自定义异常的基类。
    捕获此异常可以统一处理所有 Advisor 相关错误。
    
    Example:
        >>> try:
        ...     raise AdvisorError("处理失败")
        ... except AdvisorError as e:
        ...     print(f"Advisor 错误: {e}")
    """
    pass


class ConfigError(AdvisorError):
    """配置错误
    
    配置文件缺失、格式错误或参数不合法时抛出。
    """
    pass


class ModelError(AdvisorError):
    """模型相关错误
    
    模型加载失败、推理异常或模型文件损坏时抛出。
    """
    pass


class APIError(AdvisorError):
    """API 调用错误
    
    LLM API 调用失败且已达最大重试次数时抛出。
    包含最后一次失败的原始错误信息。
    """
    pass


class DataError(AdvisorError):
    """数据处理错误
    
    输入数据格式错误、文件不存在或数据校验失败时抛出。
    """
    pass


class OOMError(AdvisorError):
    """显存不足错误
    
    GPU 显存不足且无法通过减小 batch_size 恢复时抛出。
    错误消息中包含恢复建议。
    """
    pass


# =============================================================================
# 日志设置
# =============================================================================

def setup_logging(
    level: str = 'INFO',
    log_file: Optional[str] = None,
    name: str = 'advisor',
) -> logging.Logger:
    """
    设置日志
    
    Args:
        level: 日志级别
        log_file: 日志文件路径
        name: 日志器名称
    
    Returns:
        Logger 对象
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # 清除现有处理器
    logger.handlers.clear()
    
    # 格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件处理器
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


# =============================================================================
# 显存管理
# =============================================================================

def clear_gpu_memory():
    """清理 GPU 显存
    
    执行 Python 垃圾回收 + CUDA 缓存清理 + 同步等待。
    建议在模型卸载后或 OOM 恢复时调用。
    """
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()


def get_gpu_memory_info() -> dict:
    """获取 GPU 显存信息
    
    Returns:
        dict: 显存信息字典，包含：
            - available (bool): GPU 是否可用
            - device_name (str): GPU 设备名称
            - total_memory_gb (float): 总显存（GB）
            - allocated_gb (float): 已分配显存（GB）
            - reserved_gb (float): 已预留显存（GB）
            - free_gb (float): 可用显存（GB）
    
    Example:
        >>> info = get_gpu_memory_info()
        >>> print(f"可用显存: {info['free_gb']:.1f} GB")
    """
    if not torch.cuda.is_available():
        return {'available': False}
    
    return {
        'available': True,
        'device_name': torch.cuda.get_device_name(0),
        'total_memory_gb': torch.cuda.get_device_properties(0).total_memory / 1e9,
        'allocated_gb': torch.cuda.memory_allocated(0) / 1e9,
        'reserved_gb': torch.cuda.memory_reserved(0) / 1e9,
        'free_gb': (torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated(0)) / 1e9,
    }


def handle_oom(
    reduce_batch_size: bool = True,
    clear_cache: bool = True,
    min_batch_size: int = 1,
) -> Callable:
    """
    OOM 错误处理装饰器
    
    Args:
        reduce_batch_size: 是否自动减小批次大小
        clear_cache: 是否清理缓存
        min_batch_size: 最小批次大小
    
    Returns:
        装饰器函数
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            batch_size = kwargs.get('batch_size', 1)
            
            while True:
                try:
                    if clear_cache:
                        clear_gpu_memory()
                    
                    return func(*args, **kwargs)
                    
                except (torch.cuda.OutOfMemoryError, RuntimeError) as e:
                    if 'out of memory' not in str(e).lower():
                        raise
                    
                    if clear_cache:
                        clear_gpu_memory()
                    
                    if reduce_batch_size and batch_size > min_batch_size:
                        batch_size = max(batch_size // 2, min_batch_size)
                        kwargs['batch_size'] = batch_size
                        print(f"OOM 错误，减小批次大小到 {batch_size}")
                        continue
                    
                    raise OOMError(
                        f"显存不足，当前批次大小 {batch_size}。"
                        f"建议：1) 减小 max_seq_length 2) 使用 4-bit 量化 3) 关闭其他 GPU 程序"
                    ) from e
        
        return wrapper
    return decorator


# =============================================================================
# API 调用处理
# =============================================================================

def safe_api_call(
    max_retries: int = 3,
    retry_delay: float = 5.0,
    exponential_backoff: bool = True,
) -> Callable:
    """
    安全 API 调用装饰器
    
    Args:
        max_retries: 最大重试次数
        retry_delay: 重试间隔（秒）
        exponential_backoff: 是否使用指数退避
    
    Returns:
        装饰器函数
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_error = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                    
                except Exception as e:
                    last_error = e
                    error_msg = str(e).lower()
                    
                    # 判断是否可重试
                    retryable = any(keyword in error_msg for keyword in [
                        'rate limit', 'timeout', 'connection',
                        'server error', '500', '502', '503', '504',
                        'overloaded', 'capacity',
                    ])
                    
                    if not retryable or attempt >= max_retries:
                        break
                    
                    # 计算等待时间
                    if exponential_backoff:
                        wait_time = retry_delay * (2 ** attempt)
                    else:
                        wait_time = retry_delay
                    
                    print(f"API 调用失败 (尝试 {attempt + 1}/{max_retries + 1}): {e}")
                    print(f"等待 {wait_time:.1f} 秒后重试...")
                    time.sleep(wait_time)
            
            raise APIError(f"API 调用失败（已重试 {max_retries} 次）: {last_error}") from last_error
        
        return wrapper
    return decorator


def log_errors(logger: Optional[logging.Logger] = None) -> Callable:
    """
    错误日志装饰器
    
    Args:
        logger: Logger 对象
    
    Returns:
        装饰器函数
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_info = {
                    'function': func.__name__,
                    'error_type': type(e).__name__,
                    'error_message': str(e),
                    'traceback': traceback.format_exc(),
                }
                
                if logger:
                    logger.error(f"函数 {func.__name__} 执行失败: {e}")
                    logger.debug(f"详细信息: {error_info}")
                else:
                    print(f"错误: {func.__name__} - {e}")
                
                raise
        
        return wrapper
    return decorator


# =============================================================================
# 进度报告
# =============================================================================

class ProgressReporter:
    """进度报告器
    
    提供实时的处理进度统计，包括完成百分比、处理速率、
    预计剩余时间（ETA）和错误计数。
    
    Attributes:
        total (int): 总任务数
        desc (str): 任务描述文本
        logger (logging.Logger): 日志器（可选，None 则输出到控制台）
        current (int): 当前已完成数
        errors (int): 错误计数
        start_time (float): 开始时间戳
    
    Example:
        >>> reporter = ProgressReporter(total=100, desc="生成分析")
        >>> for i in range(100):
        ...     do_work()
        ...     reporter.update(1)
        ...     if i % 10 == 0:
        ...         reporter.report()
        >>> print(reporter.summary())
    """
    
    def __init__(
        self,
        total: int,
        desc: str = '',
        logger: Optional[logging.Logger] = None,
    ):
        """
        初始化
        
        Args:
            total: 总数
            desc: 描述
            logger: Logger 对象
        """
        self.total = total
        self.desc = desc
        self.logger = logger
        self.current = 0
        self.errors = 0
        self.start_time = time.time()
    
    def update(self, n: int = 1, error: bool = False):
        """更新进度计数
        
        Args:
            n (int): 本次完成的任务数，默认 1
            error (bool): 本次是否为错误任务，默认 False
        """
        self.current += n
        if error:
            self.errors += n
    
    def report(self):
        """输出当前进度报告
        
        格式：{desc}: {current}/{total} ({percent}%) [{elapsed}s, {rate}it/s, ETA: {eta}s]
        """
        elapsed = time.time() - self.start_time
        rate = self.current / elapsed if elapsed > 0 else 0
        eta = (self.total - self.current) / rate if rate > 0 else 0
        
        msg = (
            f"{self.desc}: {self.current}/{self.total} "
            f"({self.current/self.total*100:.1f}%) "
            f"[{elapsed:.1f}s, {rate:.2f}it/s, ETA: {eta:.1f}s]"
        )
        
        if self.errors > 0:
            msg += f" (错误: {self.errors})"
        
        if self.logger:
            self.logger.info(msg)
        else:
            print(msg)
    
    def summary(self) -> dict:
        """返回进度统计摘要
        
        Returns:
            dict: 摘要字典，包含：
                - total (int): 总任务数
                - completed (int): 已完成数
                - errors (int): 错误数
                - success_rate (float): 成功率（0-1）
                - elapsed_seconds (float): 总耗时（秒）
                - items_per_second (float): 平均处理速率
        """
        elapsed = time.time() - self.start_time
        return {
            'total': self.total,
            'completed': self.current,
            'errors': self.errors,
            'success_rate': (self.current - self.errors) / self.total if self.total > 0 else 0,
            'elapsed_seconds': elapsed,
            'items_per_second': self.current / elapsed if elapsed > 0 else 0,
        }
