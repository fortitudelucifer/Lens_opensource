"""
test_file_handler.py
FileHandler 文件传输处理器的单元测试

测试内容：
1. 基本属性测试（sub_types, link_sub_type）
2. 文件字段提取（file_name, file_ext, media_path）
3. 文件类型分类（_classify_file_category）
4. 文件大小获取（_get_file_size）
5. 边界情况处理

运行方式：
    python tests/test_file_handler.py
    pytest tests/test_file_handler.py -v

Requirements: 4.1, 4.2, 4.3
"""

import tempfile
import unittest
from pathlib import Path

from scripts.linkfile.handlers.file_handler import FileHandler


# 测试用的文件类型分类配置（模拟 linkfile.yaml 配置）
TEST_FILE_CATEGORIES = {
    "document": {
        "extensions": ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "md"],
        "description": "文档"
    },
    "archive": {
        "extensions": ["zip", "rar", "7z", "tar", "gz"],
        "description": "压缩包"
    },
    "audio": {
        "extensions": ["mp3", "wav", "flac", "aac", "m4a"],
        "description": "音频"
    },
    "video": {
        "extensions": ["mp4", "avi", "mkv", "mov"],
        "description": "视频"
    },
    "image": {
        "extensions": ["jpg", "jpeg", "png", "gif", "bmp", "webp"],
        "description": "图片"
    },
    "code": {
        "extensions": ["py", "js", "ts", "java", "c", "cpp"],
        "description": "代码"
    },
}


class TestFileHandlerProperties(unittest.TestCase):
    """测试 FileHandler 基本属性"""
    
    def setUp(self):
        self.handler = FileHandler(
            file_categories=TEST_FILE_CATEGORIES,
            workspace_root=Path("/tmp/test_workspace")
        )
    
    def test_sub_types(self):
        """测试 sub_types 返回 [6]"""
        self.assertEqual(self.handler.sub_types, [6])
    
    def test_link_sub_type(self):
        """测试 link_sub_type 返回 'file'"""
        self.assertEqual(self.handler.link_sub_type, "file")
    
    def test_init_with_categories(self):
        """测试初始化时传入分类配置"""
        handler = FileHandler(
            file_categories=TEST_FILE_CATEGORIES,
            workspace_root=Path("/tmp")
        )
        self.assertEqual(handler.file_categories, TEST_FILE_CATEGORIES)
    
    def test_init_with_empty_categories(self):
        """测试初始化时传入空分类配置"""
        handler = FileHandler(file_categories={}, workspace_root=Path("/tmp"))
        self.assertEqual(handler.file_categories, {})
    
    def test_init_with_none_categories(self):
        """测试初始化时传入 None"""
        handler = FileHandler(file_categories=None, workspace_root=Path("/tmp"))
        self.assertEqual(handler.file_categories, {})
    
    def test_init_builds_ext_to_category_map(self):
        """测试初始化时构建扩展名到分类的映射"""
        handler = FileHandler(
            file_categories=TEST_FILE_CATEGORIES,
            workspace_root=Path("/tmp")
        )
        # 检查映射是否正确构建
        self.assertEqual(handler._ext_to_category.get("pdf"), "document")
        self.assertEqual(handler._ext_to_category.get("zip"), "archive")
        self.assertEqual(handler._ext_to_category.get("mp3"), "audio")
        self.assertEqual(handler._ext_to_category.get("py"), "code")


class TestFileHandlerExtract(unittest.TestCase):
    """测试 FileHandler.extract() 方法"""
    
    def setUp(self):
        self.handler = FileHandler(
            file_categories=TEST_FILE_CATEGORIES,
            workspace_root=Path("/tmp/test_workspace")
        )
    
    def test_extract_basic_pdf(self):
        """测试基本 PDF 文件提取"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 6,
            "link_title": "报告.pdf",
            "media_path": "file/2025-01/报告.pdf",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["link_sub_type"], "file")
        self.assertEqual(result["file_name"], "报告.pdf")
        self.assertEqual(result["file_ext"], "pdf")
        self.assertEqual(result["file_category"], "document")
        self.assertEqual(result["media_path"], "file/2025-01/报告.pdf")
    
    def test_extract_archive_file(self):
        """测试压缩包文件提取"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 6,
            "link_title": "资料.zip",
            "media_path": "file/2025-01/资料.zip",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["file_ext"], "zip")
        self.assertEqual(result["file_category"], "archive")
    
    def test_extract_code_file(self):
        """测试代码文件提取"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 6,
            "link_title": "script.py",
            "media_path": "file/2025-01/script.py",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["file_ext"], "py")
        self.assertEqual(result["file_category"], "code")
    
    def test_extract_file_name_from_media_path(self):
        """测试从 media_path 提取文件名（当 link_title 为空时）"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 6,
            "link_title": "",
            "media_path": "file/2025-01/文档.docx",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["file_name"], "文档.docx")
        self.assertEqual(result["file_ext"], "docx")
        self.assertEqual(result["file_category"], "document")

    
    def test_extract_missing_link_title(self):
        """测试缺少 link_title 字段"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 6,
            "media_path": "file/2025-01/音乐.mp3",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["file_name"], "音乐.mp3")
        self.assertEqual(result["file_ext"], "mp3")
        self.assertEqual(result["file_category"], "audio")
    
    def test_extract_none_link_title(self):
        """测试 link_title 为 None"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 6,
            "link_title": None,
            "media_path": "file/2025-01/视频.mp4",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["file_name"], "视频.mp4")
        self.assertEqual(result["file_ext"], "mp4")
        self.assertEqual(result["file_category"], "video")
    
    def test_extract_empty_media_path(self):
        """测试空 media_path"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 6,
            "link_title": "文件.txt",
            "media_path": "",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["file_name"], "文件.txt")
        self.assertEqual(result["media_path"], "")
    
    def test_extract_both_empty(self):
        """测试 link_title 和 media_path 都为空"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 6,
            "link_title": "",
            "media_path": "",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["file_name"], "")
        self.assertEqual(result["file_ext"], "")
        self.assertEqual(result["file_category"], "other")
    
    def test_extract_unknown_extension(self):
        """测试未知扩展名"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 6,
            "link_title": "文件.xyz",
            "media_path": "file/2025-01/文件.xyz",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["file_ext"], "xyz")
        self.assertEqual(result["file_category"], "other")
    
    def test_extract_ignores_html_quote_lookup(self):
        """测试 extract 不使用 html_quote_lookup"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 6,
            "link_title": "文件.pdf",
            "media_path": "file/文件.pdf",
        }
        html_quote_lookup = {"123456": {"some": "data"}}
        
        result = self.handler.extract(msg, html_quote_lookup)
        
        self.assertEqual(result["link_sub_type"], "file")
        self.assertEqual(result["file_name"], "文件.pdf")


class TestFileHandlerExtractFileName(unittest.TestCase):
    """测试 FileHandler._extract_file_name() 方法"""
    
    def setUp(self):
        self.handler = FileHandler(
            file_categories=TEST_FILE_CATEGORIES,
            workspace_root=Path("/tmp")
        )
    
    def test_extract_from_link_title(self):
        """测试从 link_title 提取文件名"""
        msg = {"link_title": "报告.pdf", "media_path": "file/other.doc"}
        self.assertEqual(self.handler._extract_file_name(msg), "报告.pdf")
    
    def test_extract_from_media_path(self):
        """测试从 media_path 提取文件名"""
        msg = {"link_title": "", "media_path": "file/2025-01/文档.docx"}
        self.assertEqual(self.handler._extract_file_name(msg), "文档.docx")
    
    def test_extract_priority_link_title(self):
        """测试 link_title 优先级高于 media_path"""
        msg = {"link_title": "优先.pdf", "media_path": "file/次要.doc"}
        self.assertEqual(self.handler._extract_file_name(msg), "优先.pdf")
    
    def test_extract_empty_both(self):
        """测试两者都为空"""
        msg = {"link_title": "", "media_path": ""}
        self.assertEqual(self.handler._extract_file_name(msg), "")
    
    def test_extract_missing_both(self):
        """测试两者都缺失"""
        msg = {}
        self.assertEqual(self.handler._extract_file_name(msg), "")


class TestFileHandlerExtractFileExt(unittest.TestCase):
    """测试 FileHandler._extract_file_ext() 方法"""
    
    def setUp(self):
        self.handler = FileHandler(
            file_categories=TEST_FILE_CATEGORIES,
            workspace_root=Path("/tmp")
        )
    
    def test_extract_pdf_ext(self):
        """测试提取 PDF 扩展名"""
        self.assertEqual(self.handler._extract_file_ext("报告.pdf"), "pdf")
    
    def test_extract_uppercase_ext(self):
        """测试大写扩展名转小写"""
        self.assertEqual(self.handler._extract_file_ext("报告.PDF"), "pdf")
    
    def test_extract_mixed_case_ext(self):
        """测试混合大小写扩展名"""
        self.assertEqual(self.handler._extract_file_ext("文档.DocX"), "docx")
    
    def test_extract_no_ext(self):
        """测试无扩展名"""
        self.assertEqual(self.handler._extract_file_ext("README"), "")
    
    def test_extract_empty_filename(self):
        """测试空文件名"""
        self.assertEqual(self.handler._extract_file_ext(""), "")
    
    def test_extract_double_ext(self):
        """测试双扩展名（如 .tar.gz）"""
        # Path.suffix 只返回最后一个扩展名
        self.assertEqual(self.handler._extract_file_ext("archive.tar.gz"), "gz")
    
    def test_extract_hidden_file(self):
        """测试隐藏文件（如 .gitignore）"""
        # Python pathlib 将 .gitignore 视为没有扩展名的隐藏文件
        # 因为整个名称被视为 stem，没有 suffix
        self.assertEqual(self.handler._extract_file_ext(".gitignore"), "")
    
    def test_extract_dot_only(self):
        """测试只有点号的文件名"""
        self.assertEqual(self.handler._extract_file_ext("."), "")


class TestFileHandlerClassifyFileCategory(unittest.TestCase):
    """测试 FileHandler._classify_file_category() 方法"""
    
    def setUp(self):
        self.handler = FileHandler(
            file_categories=TEST_FILE_CATEGORIES,
            workspace_root=Path("/tmp")
        )
    
    def test_classify_document_pdf(self):
        """测试 PDF 分类为文档"""
        self.assertEqual(self.handler._classify_file_category("pdf"), "document")
    
    def test_classify_document_docx(self):
        """测试 DOCX 分类为文档"""
        self.assertEqual(self.handler._classify_file_category("docx"), "document")
    
    def test_classify_archive_zip(self):
        """测试 ZIP 分类为压缩包"""
        self.assertEqual(self.handler._classify_file_category("zip"), "archive")
    
    def test_classify_archive_rar(self):
        """测试 RAR 分类为压缩包"""
        self.assertEqual(self.handler._classify_file_category("rar"), "archive")
    
    def test_classify_audio_mp3(self):
        """测试 MP3 分类为音频"""
        self.assertEqual(self.handler._classify_file_category("mp3"), "audio")
    
    def test_classify_video_mp4(self):
        """测试 MP4 分类为视频"""
        self.assertEqual(self.handler._classify_file_category("mp4"), "video")
    
    def test_classify_image_jpg(self):
        """测试 JPG 分类为图片"""
        self.assertEqual(self.handler._classify_file_category("jpg"), "image")
    
    def test_classify_image_png(self):
        """测试 PNG 分类为图片"""
        self.assertEqual(self.handler._classify_file_category("png"), "image")
    
    def test_classify_code_py(self):
        """测试 PY 分类为代码"""
        self.assertEqual(self.handler._classify_file_category("py"), "code")
    
    def test_classify_code_js(self):
        """测试 JS 分类为代码"""
        self.assertEqual(self.handler._classify_file_category("js"), "code")
    
    def test_classify_unknown_ext(self):
        """测试未知扩展名返回 other"""
        self.assertEqual(self.handler._classify_file_category("xyz"), "other")
    
    def test_classify_empty_ext(self):
        """测试空扩展名返回 other"""
        self.assertEqual(self.handler._classify_file_category(""), "other")
    
    def test_classify_case_insensitive(self):
        """测试扩展名大小写不敏感"""
        self.assertEqual(self.handler._classify_file_category("PDF"), "document")
        self.assertEqual(self.handler._classify_file_category("Pdf"), "document")
    
    def test_classify_with_empty_categories(self):
        """测试空分类配置时返回 other"""
        handler = FileHandler(file_categories={}, workspace_root=Path("/tmp"))
        self.assertEqual(handler._classify_file_category("pdf"), "other")


class TestFileHandlerGetFileSize(unittest.TestCase):
    """测试 FileHandler._get_file_size() 方法"""
    
    def setUp(self):
        # 创建临时目录作为工作空间
        self.temp_dir = tempfile.mkdtemp()
        self.workspace_root = Path(self.temp_dir)
        self.handler = FileHandler(
            file_categories=TEST_FILE_CATEGORIES,
            workspace_root=self.workspace_root
        )
        
        # 创建 raw 目录和测试文件
        raw_dir = self.workspace_root / "raw" / "file"
        raw_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建一个测试文件
        self.test_file = raw_dir / "test.txt"
        self.test_file.write_text("Hello, World!")  # 13 字节
    
    def tearDown(self):
        # 清理临时目录
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_get_file_size_existing_file(self):
        """测试获取存在文件的大小"""
        size = self.handler._get_file_size("file/test.txt")
        self.assertEqual(size, 13)
    
    def test_get_file_size_nonexistent_file(self):
        """测试获取不存在文件的大小"""
        size = self.handler._get_file_size("file/nonexistent.txt")
        self.assertIsNone(size)
    
    def test_get_file_size_empty_path(self):
        """测试空路径"""
        size = self.handler._get_file_size("")
        self.assertIsNone(size)
    
    def test_get_file_size_none_path(self):
        """测试 None 路径"""
        size = self.handler._get_file_size(None)
        self.assertIsNone(size)
    
    def test_get_file_size_no_workspace_root(self):
        """测试没有 workspace_root 时"""
        handler = FileHandler(
            file_categories=TEST_FILE_CATEGORIES,
            workspace_root=None
        )
        size = handler._get_file_size("file/test.txt")
        self.assertIsNone(size)
    
    def test_extract_includes_file_size_when_exists(self):
        """测试 extract 方法在文件存在时包含 file_size_bytes"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 6,
            "link_title": "test.txt",
            "media_path": "file/test.txt",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertIn("file_size_bytes", result)
        self.assertEqual(result["file_size_bytes"], 13)
    
    def test_extract_excludes_file_size_when_not_exists(self):
        """测试 extract 方法在文件不存在时不包含 file_size_bytes"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 6,
            "link_title": "nonexistent.txt",
            "media_path": "file/nonexistent.txt",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertNotIn("file_size_bytes", result)


class TestFileHandlerEdgeCases(unittest.TestCase):
    """测试边界情况"""
    
    def setUp(self):
        self.handler = FileHandler(
            file_categories=TEST_FILE_CATEGORIES,
            workspace_root=Path("/tmp/test_workspace")
        )
    
    def test_chinese_filename(self):
        """测试中文文件名"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 6,
            "link_title": "中文文档.pdf",
            "media_path": "file/中文文档.pdf",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["file_name"], "中文文档.pdf")
        self.assertEqual(result["file_ext"], "pdf")
    
    def test_special_characters_in_filename(self):
        """测试文件名中的特殊字符"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 6,
            "link_title": "文件 (1) [副本].pdf",
            "media_path": "file/文件 (1) [副本].pdf",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["file_name"], "文件 (1) [副本].pdf")
    
    def test_very_long_filename(self):
        """测试超长文件名"""
        long_name = "a" * 200 + ".pdf"
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 6,
            "link_title": long_name,
            "media_path": f"file/{long_name}",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["file_name"], long_name)
        self.assertEqual(result["file_ext"], "pdf")
    
    def test_nested_media_path(self):
        """测试嵌套的 media_path"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 6,
            "link_title": "",
            "media_path": "file/2025-01/subdir/deep/文档.docx",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["file_name"], "文档.docx")
        self.assertEqual(result["media_path"], "file/2025-01/subdir/deep/文档.docx")
    
    def test_file_with_multiple_dots(self):
        """测试多个点号的文件名"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 6,
            "link_title": "file.name.with.dots.pdf",
            "media_path": "file/file.name.with.dots.pdf",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["file_name"], "file.name.with.dots.pdf")
        self.assertEqual(result["file_ext"], "pdf")
    
    def test_all_file_categories(self):
        """测试所有文件类型分类"""
        test_cases = [
            ("doc.pdf", "document"),
            ("doc.docx", "document"),
            ("doc.txt", "document"),
            ("archive.zip", "archive"),
            ("archive.rar", "archive"),
            ("music.mp3", "audio"),
            ("music.wav", "audio"),
            ("video.mp4", "video"),
            ("video.avi", "video"),
            ("image.jpg", "image"),
            ("image.png", "image"),
            ("script.py", "code"),
            ("script.js", "code"),
            ("unknown.xyz", "other"),
        ]
        
        for filename, expected_category in test_cases:
            with self.subTest(filename=filename):
                msg = {
                    "msg_uid": "P1:123456",
                    "sub_type": 6,
                    "link_title": filename,
                    "media_path": f"file/{filename}",
                }
                result = self.handler.extract(msg, {})
                self.assertEqual(
                    result["file_category"], 
                    expected_category,
                    f"Expected {filename} to be {expected_category}"
                )


# =============================================================================
# 运行测试
# =============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
