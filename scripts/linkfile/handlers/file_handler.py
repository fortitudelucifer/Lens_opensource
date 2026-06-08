"""
FileHandler - 文件传输处理器

处理 sub_type=6 的文件传输消息，提取文件名、扩展名和类型分类。

文件传输包含以下信息：
- file_name: 文件名
- file_ext: 文件扩展名（小写）
- file_category: 文件类型分类（根据扩展名匹配 linkfile.yaml 中的规则）
- file_size_bytes: 文件大小（如果文件存在）
- media_path: 媒体文件路径

Requirements: 4.1, 4.2, 4.3
"""

import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from scripts.linkfile.handlers.base import SubTypeHandler


logger = logging.getLogger(__name__)


class FileHandler(SubTypeHandler):
    """
    处理 sub_type=6 的文件传输
    
    文件传输是微信中发送的文件，包含文件名和路径。处理器会根据文件扩展名
    匹配 linkfile.yaml 中定义的 file_categories 规则，对文件进行分类。
    
    支持的文件类型包括：
    - document: 文档（pdf, doc, docx, xls, xlsx, ppt, pptx, txt, md 等）
    - archive: 压缩包（zip, rar, 7z, tar, gz 等）
    - audio: 音频（mp3, wav, flac, aac, m4a 等）
    - video: 视频（mp4, avi, mkv, mov 等）
    - image: 图片（jpg, jpeg, png, gif, bmp, webp 等）
    - code: 代码（py, js, ts, java, c, cpp 等）
    - data: 数据文件（json, xml, yaml, csv, sql 等）
    - executable: 可执行文件（exe, msi, dmg, app, apk 等）
    - other: 其他（默认）
    
    Args:
        file_categories: 文件类型分类配置，格式为：
            {
                "document": {"extensions": ["pdf", "doc", "docx", ...]},
                "archive": {"extensions": ["zip", "rar", "7z", ...]},
                ...
            }
        workspace_root: 工作空间根目录，用于获取文件大小
    
    Example:
        >>> categories = {
        ...     "document": {"extensions": ["pdf", "doc", "docx"]},
        ...     "archive": {"extensions": ["zip", "rar"]}
        ... }
        >>> handler = FileHandler(file_categories=categories, workspace_root=Path("/data/demo"))
        >>> msg = {
        ...     'msg_uid': 'P1:123',
        ...     'sub_type': 6,
        ...     'link_title': '报告.pdf',
        ...     'media_path': 'file/2025-01/报告.pdf'
        ... }
        >>> result = handler.extract(msg, {})
        >>> result['link_sub_type']
        'file'
        >>> result['file_ext']
        'pdf'
        >>> result['file_category']
        'document'
    """
    
    def __init__(self, file_categories: Dict[str, Dict[str, Any]], workspace_root: Path):
        """
        初始化 FileHandler
        
        Args:
            file_categories: 文件类型分类配置，每个分类包含：
                - extensions: 该分类包含的文件扩展名列表
            workspace_root: 工作空间根目录，用于构建文件完整路径以获取文件大小
        """
        self.file_categories = file_categories or {}
        self.workspace_root = Path(workspace_root) if workspace_root else None
        
        # 构建扩展名到分类的反向映射，提高查找效率
        self._ext_to_category: Dict[str, str] = {}
        for category, config in self.file_categories.items():
            extensions = config.get("extensions", [])
            for ext in extensions:
                # 扩展名统一小写存储
                self._ext_to_category[ext.lower()] = category
    
    @property
    def sub_types(self) -> List[int]:
        """返回此处理器支持的 sub_type 列表"""
        return [6]
    
    @property
    def link_sub_type(self) -> str:
        """返回统一的 link_sub_type 值"""
        return "file"
    
    def extract(self, msg: Dict[str, Any], html_quote_lookup: Dict[str, Any]) -> Dict[str, Any]:
        """
        提取文件传输字段
        
        从消息中提取 file_name、file_ext、media_path 字段，并根据扩展名
        确定 file_category。如果文件存在，还会获取 file_size_bytes。
        
        文件名提取优先级：
        1. link_title 字段（通常包含原始文件名）
        2. media_path 字段的文件名部分
        
        Args:
            msg: 原始消息记录，包含：
                - msg_uid: 消息唯一标识
                - sub_type: 应为 6
                - link_title: 链接标题（通常是文件名）
                - media_path: 媒体文件路径
                
            html_quote_lookup: HTML 解析的引用信息查找表（此处理器不使用）
                
        Returns:
            Dict[str, Any]: 提取的字段字典
                {
                    "link_sub_type": "file",
                    "file_name": str,        # 文件名
                    "file_ext": str,         # 文件扩展名（小写）
                    "file_category": str,    # 文件类型分类
                    "media_path": str,       # 媒体文件路径
                    "file_size_bytes": int   # 文件大小（可选，文件存在时）
                }
        """
        # 提取文件名：优先从 link_title，其次从 media_path
        file_name = self._extract_file_name(msg)
        
        # 提取扩展名（小写）
        file_ext = self._extract_file_ext(file_name)
        
        # 获取 media_path
        media_path = msg.get("media_path", "") or ""
        
        # 分类文件类型
        file_category = self._classify_file_category(file_ext)
        
        # 尝试获取文件大小
        file_size_bytes = self._get_file_size(media_path)
        
        result = {
            "link_sub_type": self.link_sub_type,
            "file_name": file_name,
            "file_ext": file_ext,
            "file_category": file_category,
            "media_path": media_path,
        }
        
        # 只有当文件大小可获取时才添加该字段
        if file_size_bytes is not None:
            result["file_size_bytes"] = file_size_bytes
        
        return result
    
    def _extract_file_name(self, msg: Dict[str, Any]) -> str:
        """
        从消息中提取文件名
        
        优先级：
        1. link_title 字段（通常包含原始文件名）
        2. media_path 字段的文件名部分
        
        Args:
            msg: 原始消息记录
            
        Returns:
            str: 文件名，如果无法获取则返回空字符串
            
        Example:
            >>> handler = FileHandler({}, Path("/data"))
            >>> handler._extract_file_name({'link_title': '报告.pdf'})
            '报告.pdf'
            >>> handler._extract_file_name({'media_path': 'file/2025-01/文档.docx'})
            '文档.docx'
        """
        # 优先使用 link_title
        link_title = msg.get("link_title", "") or ""
        if link_title:
            return link_title
        
        # 其次从 media_path 提取文件名
        media_path = msg.get("media_path", "") or ""
        if media_path:
            return Path(media_path).name
        
        return ""
    
    def _extract_file_ext(self, file_name: str) -> str:
        """
        从文件名中提取扩展名
        
        扩展名会转换为小写，不包含点号。
        
        Args:
            file_name: 文件名
            
        Returns:
            str: 文件扩展名（小写），如果没有扩展名则返回空字符串
            
        Example:
            >>> handler = FileHandler({}, Path("/data"))
            >>> handler._extract_file_ext("报告.PDF")
            'pdf'
            >>> handler._extract_file_ext("README")
            ''
            >>> handler._extract_file_ext("archive.tar.gz")
            'gz'
        """
        if not file_name:
            return ""
        
        # 使用 Path.suffix 获取扩展名，去掉点号并转小写
        suffix = Path(file_name).suffix
        if suffix:
            return suffix[1:].lower()  # 去掉开头的点号
        
        return ""
    
    def _classify_file_category(self, ext: str) -> str:
        """
        根据扩展名分类文件类型
        
        使用预构建的扩展名到分类的映射表进行查找。如果扩展名不在任何
        已定义的分类中，返回 "other"。
        
        Args:
            ext: 文件扩展名（应为小写）
            
        Returns:
            str: 文件类型分类标识符
            
        Example:
            >>> categories = {
            ...     "document": {"extensions": ["pdf", "doc", "docx"]},
            ...     "archive": {"extensions": ["zip", "rar"]}
            ... }
            >>> handler = FileHandler(categories, Path("/data"))
            >>> handler._classify_file_category("pdf")
            'document'
            >>> handler._classify_file_category("zip")
            'archive'
            >>> handler._classify_file_category("xyz")
            'other'
        """
        if not ext:
            return "other"
        
        # 确保扩展名是小写
        ext_lower = ext.lower()
        
        # 从预构建的映射表中查找
        return self._ext_to_category.get(ext_lower, "other")
    
    def _get_file_size(self, media_path: str) -> Optional[int]:
        """
        获取文件大小
        
        根据 media_path 构建完整路径，如果文件存在则返回文件大小（字节）。
        文件路径构建规则：workspace_root / 'raw' / media_path
        
        Args:
            media_path: 媒体文件相对路径
            
        Returns:
            Optional[int]: 文件大小（字节），如果文件不存在或无法访问则返回 None
            
        Example:
            >>> handler = FileHandler({}, Path("/data/demo"))
            >>> # 假设文件存在
            >>> handler._get_file_size("file/2025-01/报告.pdf")
            1024  # 文件大小
            >>> # 文件不存在
            >>> handler._get_file_size("file/nonexistent.pdf")
            None
        """
        if not media_path or not self.workspace_root:
            return None
        
        try:
            # 构建完整路径：workspace_root / 'raw' / media_path
            full_path = self.workspace_root / "raw" / media_path
            
            if full_path.exists() and full_path.is_file():
                return full_path.stat().st_size
        except (OSError, PermissionError) as e:
            logger.warning(f"Failed to get file size for {media_path}: {e}")
        
        return None
