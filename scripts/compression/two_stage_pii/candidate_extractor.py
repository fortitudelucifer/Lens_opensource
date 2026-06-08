# -*- coding: utf-8 -*-
"""
候选词提取器

从时间轴数据中提取可能的人名候选词。
使用正则匹配 2-4 个连续中文字符，并排除常见代词、称谓等。
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set
import yaml
from tqdm import tqdm

from .models import CandidateList, CandidateWord


class CandidateExtractor:
    """从文本中提取人名候选词"""
    
    # 与 agent_sft_l1.jsonl 完全匹配的文本字段
    DEFAULT_TEXT_FIELDS = [
        # 基础文本
        'text_raw',
        # 语音
        'voice_to_text', 'emotion_desc',
        # 图片
        'image_summary', 'image_ocr_text',
        # 视频
        'video_summary', 'video_voice_to_text',
        # 表情包
        'sticker_summary', 'sticker_ocr_text',
        # 链接/文件/引用
        'link_title', 'link_quote_text', 'link_file_summary',
        # 联系人
        'contact_nickname',
        # 位置
        'location_label', 'location_poiname',
    ]
    
    # 跳过的消息类型（不提取人名候选）
    SKIP_TYPES = ['time_gap']
    
    # 中文人名正则（2-4 个连续中文字符，但需要边界检测）
    # 使用非贪婪匹配，并检查前后是否为非中文字符
    CHINESE_NAME_PATTERN = re.compile(r'(?<![a-zA-Z\u4e00-\u9fff])([\u4e00-\u9fff]{2,4})(?![a-zA-Z\u4e00-\u9fff])')
    
    # 更精确的人名模式：常见姓氏 + 1-2 字名
    COMMON_SURNAMES = {
        '赵', '钱', '孙', '李', '周', '吴', '郑', '王', '冯', '陈',
        '褚', '卫', '蒋', '沈', '韩', '杨', '朱', '秦', '尤', '许',
        '何', '吕', '施', '张', '孔', '曹', '严', '华', '金', '魏',
        '陶', '姜', '戚', '谢', '邹', '喻', '柏', '水', '窦', '章',
        '云', '苏', '潘', '葛', '奚', '范', '彭', '郎', '鲁', '韦',
        '昌', '马', '苗', '凤', '花', '方', '俞', '任', '袁', '柳',
        '酆', '鲍', '史', '唐', '费', '廉', '岑', '薛', '雷', '贺',
        '倪', '汤', '滕', '殷', '罗', '毕', '郝', '邬', '安', '常',
        '乐', '于', '时', '傅', '皮', '卞', '齐', '康', '伍', '余',
        '元', '卜', '顾', '孟', '平', '黄', '和', '穆', '萧', '尹',
        '姚', '邵', '湛', '汪', '祁', '毛', '禹', '狄', '米', '贝',
        '明', '臧', '计', '伏', '成', '戴', '谈', '宋', '茅', '庞',
        '熊', '纪', '舒', '屈', '项', '祝', '董', '梁', '杜', '阮',
        '蓝', '闵', '席', '季', '麻', '强', '贾', '路', '娄', '危',
        '江', '童', '颜', '郭', '梅', '盛', '林', '刁', '钟', '徐',
        '邱', '骆', '高', '夏', '蔡', '田', '樊', '胡', '凌', '霍',
        '虞', '万', '支', '柯', '昝', '管', '卢', '莫', '经', '房',
        '裘', '缪', '干', '解', '应', '宗', '丁', '宣', '贲', '邓',
        '郁', '单', '杭', '洪', '包', '诸', '左', '石', '崔', '吉',
        '钮', '龚', '程', '嵇', '邢', '滑', '裴', '陆', '荣', '翁',
        '荀', '羊', '於', '惠', '甄', '曲', '家', '封', '芮', '羿',
        '储', '靳', '汲', '邴', '糜', '松', '井', '段', '富', '巫',
        '乌', '焦', '巴', '弓', '牧', '隗', '山', '谷', '车', '侯',
        '宓', '蓬', '全', '郗', '班', '仰', '秋', '仲', '伊', '宫',
        '宁', '仇', '栾', '暴', '甘', '钭', '厉', '戎', '祖', '武',
        '符', '刘', '景', '詹', '束', '龙', '叶', '幸', '司', '韶',
        '郜', '黎', '蓟', '薄', '印', '宿', '白', '怀', '蒲', '邰',
        '从', '鄂', '索', '咸', '籍', '赖', '卓', '蔺', '屠', '蒙',
        '池', '乔', '阴', '郁', '胥', '能', '苍', '双', '闻', '莘',
        '党', '翟', '谭', '贡', '劳', '逄', '姬', '申', '扶', '堵',
        '冉', '宰', '郦', '雍', '却', '璩', '桑', '桂', '濮', '牛',
        '寿', '通', '边', '扈', '燕', '冀', '郏', '浦', '尚', '农',
        '温', '别', '庄', '晏', '柴', '瞿', '阎', '充', '慕', '连',
        '茹', '习', '宦', '艾', '鱼', '容', '向', '古', '易', '慎',
        '戈', '廖', '庾', '终', '暨', '居', '衡', '步', '都', '耿',
        '满', '弘', '匡', '国', '文', '寇', '广', '禄', '阙', '东',
        '欧', '殳', '沃', '利', '蔚', '越', '夔', '隆', '师', '巩',
        '厍', '聂', '晁', '勾', '敖', '融', '冷', '訾', '辛', '阚',
        '那', '简', '饶', '空', '曾', '毋', '沙', '乜', '养', '鞠',
        '须', '丰', '巢', '关', '蒯', '相', '查', '后', '荆', '红',
        '游', '竺', '权', '逯', '盖', '益', '桓', '公', '仉', '督',
        '晋', '楚', '闫', '法', '汝', '鄢', '涂', '钦', '归', '海',
    }
    
    # 常见昵称前缀
    NICKNAME_PREFIXES = {'小', '大', '老', '阿'}
    
    # 常见昵称后缀
    NICKNAME_SUFFIXES = {'哥', '姐', '弟', '妹', '叔', '姨', '爷', '奶', '总', '老师'}
    
    # 内置排除列表（常见代词、称谓、动词等）
    BUILTIN_EXCLUSIONS = {
        # 代词
        '我', '你', '他', '她', '它', '我们', '你们', '他们', '她们',
        '自己', '对方', '人家', '别人', '大家', '谁', '什么',
        '这个', '那个', '哪个', '某个', '每个', '任何',
        # 称谓
        '朋友', '女生', '男生', '女孩', '男孩', '女人', '男人',
        '姐姐', '哥哥', '妹妹', '弟弟', '爸爸', '妈妈', '爷爷', '奶奶',
        '老师', '同学', '同事', '领导', '老板', '客户', '儿子', '女儿',
        '老爸', '老妈', '老头', '老太', '小孩', '孩子', '宝宝',
        '学生', '大学生', '研究生', '博士', '教授',
        '我妈', '我爸', '我妹', '我姐', '我哥', '我弟',
        '我妹妹', '我姐姐', '我哥哥', '我弟弟',
        '外婆', '外公', '姨妈', '姑妈', '舅舅', '叔叔', '阿姨',
        '学长', '学姐', '师兄', '师姐', '爸妈', '父母',
        '大叔', '大妈', '大爷', '大姐', '小哥', '小姐', '先生', '女士',
        '家人', '亲人', '爱人', '恋人',
        # 动物
        '猫咪', '猫猫', '狗狗', '小猫', '小狗', '宠物', '动物',
        # 常见动词/形容词
        '可以', '应该', '可能', '必须', '需要', '希望', '喜欢',
        '觉得', '认为', '知道', '明白', '理解', '相信',
        '开心', '高兴', '难过', '伤心', '生气', '害怕',
        '简单', '复杂', '容易', '困难', '严格', '宽松',
        '相关', '相同', '相似', '相反',
        # 时间词
        '今天', '明天', '昨天', '后天', '前天', '现在', '以后', '之前',
        '上午', '下午', '晚上', '凌晨', '早上', '中午',
        '星期', '周末', '工作日', '假期', '节日',
        '时候', '时间', '时期', '时代', '时刻',
        '周六', '周日', '周一', '周二', '周三', '周四', '周五',
        '白天', '黑夜', '那天', '哪天', '每天',
        # 方位词
        '这里', '那里', '哪里', '前面', '后面', '上面', '下面',
        '左边', '右边', '旁边', '对面', '里面', '外面',
        '那边', '这边', '哪边', '周围', '附近',
        '左侧', '右侧', '上方', '下方',
        # 常见名词
        '东西', '事情', '问题', '方法', '原因', '结果', '情况',
        '时间', '地方', '世界', '国家', '城市', '公司', '学校',
        '关系', '习惯', '经历', '印象', '计划', '安排', '方式',
        '单位', '大学', '房间', '游戏', '支持', '满足',
        '项目', '任务', '工作', '经验', '能力',
        '关注', '关心', '关于',
        # 网络用语
        '哈哈', '呵呵', '嘿嘿', '嘻嘻', '哈哈哈', '哈哈哈哈',
        # 其他常见误检
        '表情', '图片', '视频', '语音', '文件', '链接',
        '消息', '内容', '信息', '数据', '系统', '功能',
        '文字', '文章', '文件', '文本', '文化', '文明',
        '舒服', '舒适', '舒展', '舒缓',
        '容易', '容量', '容器', '容纳',
        '辛苦', '辛勤', '辛酸',
        '方便', '方向', '方案', '方面', '方法',
        '解决', '解释', '解答', '解除',
        '白色', '黑色', '红色', '蓝色', '绿色', '黄色',
        '祝福', '祝贺', '祝愿',
        '厉害', '厉行',
        '焦虑', '焦急', '焦点',
        '平静', '平安', '平常', '平时', '平均',
        '大脑', '大便', '大晚', '大概', '大家',
        '公众号', '小红书',
        '明确', '明显', '明年', '明白',
        # 常见动词组合（容易被误提取）
        '说今', '说的', '说了', '说是', '说要', '说会',
        '和李', '和张', '和王', '和刘', '和陈', '和杨',
        '和我', '和你', '和他', '和她', '和朋友',
        '去找', '去看', '去买', '去吃', '去玩',
        '的电', '的话', '的事', '的人', '的时',
        '天见', '天气', '天天', '天上', '天下',
        '明天', '明白', '明年', '明显',
        '今天', '今年', '今日', '今后',
        '武功', '功夫', '功能', '功课',
        '干嘛', '干活', '干什么', '干吗',
        '谈恋爱', '谈话', '谈论',
        # 那X 系列（常见口语）
        '那你', '那我', '那他', '那她', '那种', '那边', '那确实', '那肯定',
        '那个', '那些', '那样', '那么', '那里', '那时', '那现', '那天',
        # 从X 系列
        '从头', '从前', '从来', '从此', '从中', '从繁华', '从头坐',
        # 高铁/交通
        '高铁', '高速', '高峰',
        # 其他常见词
        '事姐姐',  # 特殊误检
        '家餐厅',  # 特殊误检
        '段语音',  # 特殊误检
        '江景',    # 地名相关
        '老天奶',  # 特殊误检
        '班之',    # 特殊误检
        '常嘛', '常美',  # 特殊误检
        # 张X 系列（"一张X" 的误提取）
        '张照片', '张图片', '张截图', '张备用', '张婚礼', '张招行',
        '张浅色', '张桌子', '张床', '张绿色', '张户', '张沙发',
        # 周X 系列（"这周X"、"上周X" 的误提取）
        '周应该', '周只', '周日出', '周再议', '周你', '周六回',
        # 常X 系列（"非常X"、"经常X" 的误提取）
        '常先进', '常美丽', '常舒适', '常简单', '常高', '常满',
        '常人', '常小',
        # 安X 系列（"平安X"、"安全X" 的误提取）
        '安全感', '安详', '安逸', '安慰她', '安完', '安装', '安顺',
        # 方X 系列（"对方X"、"方便X" 的误提取）
        '方装饰', '方满意', '方付出', '方有', '方子呐',
        # 段X 系列（"一段X" 的误提取）
        '段时间', '段你你',
        # 其他常见误检
        '个大叔', '大姨夫', '小老费', '小领导', '小念', '小段', '小小',
        '刘德双',  # 可能是 "刘德华" 的误写
        '黄敏之', '黄敏心', '黄敏觉', '黄敏家', '黄明讲',  # "黄敏" 后面跟其他字
        '李子坝',  # 地名
        '彭厨',    # 餐厅名
        '鲁肉',    # 食物名
        '丁点',    # 常见词
    }
    
    def __init__(self, exclusion_list_path: str = "configs/anonymization.yaml"):
        """
        初始化提取器
        
        Args:
            exclusion_list_path: 排除列表配置路径
        """
        self.exclusion_list = self._load_exclusion_list(exclusion_list_path)
        self.text_fields = self.DEFAULT_TEXT_FIELDS.copy()
    
    def _load_exclusion_list(self, config_path: str) -> Set[str]:
        """加载排除列表"""
        exclusions = self.BUILTIN_EXCLUSIONS.copy()
        
        path = Path(config_path)
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f) or {}
                
                # 加载 exclude_patterns
                patterns = config.get('exclude_patterns', [])
                exclusions.update(patterns)
                
                # 加载历史人物、公众人物等（这些不应被匿名化）
                # 但仍然可以作为候选词提取，只是在验证时标记为"公众人物"
                
            except Exception as e:
                print(f"[WARN] 加载排除列表失败: {e}")
        
        return exclusions

    def extract_from_text(self, text: str) -> List[str]:
        """
        从单条文本提取候选词
        
        使用多种策略：
        1. 姓氏 + 名字模式（如"张三"、"王小明"）
        2. 昵称模式（如"小明"、"阿强"）
        3. X哥、X姐等称呼模式
        
        关键：只提取完整的人名，不提取带有后续动词/介词的组合
        
        Args:
            text: 输入文本
        
        Returns:
            候选词列表（已去重，已排除）
        """
        if not text or not isinstance(text, str):
            return []
        
        candidates = set()
        
        # 常见动词/介词/连词（人名后面如果跟这些字，说明人名已结束）
        # 这些字符用于判断人名的边界
        boundary_chars = {
            '的', '了', '在', '是', '和', '与', '跟', '给', '被', '把',
            '说', '问', '看', '去', '来', '到', '从', '向', '对', '让',
            '想', '要', '会', '能', '可', '得', '着', '过', '吗', '呢',
            '吧', '啊', '呀', '哦', '嗯', '哈', '嘿', '喂', '诶',
            '约', '找', '见', '叫', '请', '帮', '送', '接', '带',
            '上', '下', '里', '外', '前', '后', '左', '右', '中',
            '也', '都', '就', '才', '又', '还', '已', '正', '将',
            '很', '太', '真', '好', '最', '更', '非', '不', '没',
            '这', '那', '哪', '什', '怎', '为', '因', '所', '但',
            '发', '做', '打', '写', '读', '听', '吃', '喝', '睡',
            '一', '两',  # 数量词开头
        }
        
        # 策略 1: 姓氏 + 名字模式（最可能是人名）
        for surname in self.COMMON_SURNAMES:
            start = 0
            while True:
                pos = text.find(surname, start)
                if pos == -1:
                    break
                
                # 检查姓氏前面的字符
                # 如果前面是中文且不是边界字符，可能不是姓氏开头
                if pos > 0:
                    prev_char = text[pos-1]
                    if '\u4e00' <= prev_char <= '\u9fff' and prev_char not in boundary_chars:
                        start = pos + 1
                        continue
                
                # 提取姓氏后面的中文字符（最多2个）
                remaining = text[pos + len(surname):]
                name_chars = []
                for i, char in enumerate(remaining[:2]):
                    if '\u4e00' <= char <= '\u9fff':
                        # 如果这个字符是边界字符，停止提取（但不包含它）
                        if char in boundary_chars:
                            break
                        name_chars.append(char)
                    else:
                        break
                
                if name_chars:
                    # 检查名字后面的字符
                    next_pos = pos + len(surname) + len(name_chars)
                    next_char = text[next_pos] if next_pos < len(text) else ''
                    
                    # 如果下一个字符是边界字符、非中文、或字符串结束，认为是完整人名
                    if not next_char or next_char in boundary_chars or not ('\u4e00' <= next_char <= '\u9fff'):
                        full_name = surname + ''.join(name_chars)
                        if full_name not in self.exclusion_list:
                            candidates.add(full_name)
                
                start = pos + 1
        
        # 策略 2: 昵称模式（小X、阿X、老X、大X + 1-2字）
        for prefix in self.NICKNAME_PREFIXES:
            start = 0
            while True:
                pos = text.find(prefix, start)
                if pos == -1:
                    break
                
                # 检查前缀前面的字符
                if pos > 0:
                    prev_char = text[pos-1]
                    if '\u4e00' <= prev_char <= '\u9fff' and prev_char not in boundary_chars:
                        start = pos + 1
                        continue
                
                remaining = text[pos + len(prefix):]
                name_chars = []
                for char in remaining[:2]:
                    if '\u4e00' <= char <= '\u9fff':
                        # 如果这个字符是边界字符，停止提取
                        if char in boundary_chars:
                            break
                        name_chars.append(char)
                    else:
                        break
                
                if name_chars:
                    next_pos = pos + len(prefix) + len(name_chars)
                    next_char = text[next_pos] if next_pos < len(text) else ''
                    
                    if not next_char or next_char in boundary_chars or not ('\u4e00' <= next_char <= '\u9fff'):
                        full_name = prefix + ''.join(name_chars)
                        if full_name not in self.exclusion_list:
                            candidates.add(full_name)
                
                start = pos + 1
        
        # 策略 3: X哥、X姐等称呼模式（1-2字 + 后缀）
        for suffix in self.NICKNAME_SUFFIXES:
            start = 0
            while True:
                pos = text.find(suffix, start)
                if pos == -1:
                    break
                
                # 检查后缀后面的字符
                next_pos = pos + len(suffix)
                if next_pos < len(text):
                    next_char = text[next_pos]
                    # 如果后面是中文且不是边界字符，可能不是称呼结尾
                    if '\u4e00' <= next_char <= '\u9fff' and next_char not in boundary_chars:
                        start = pos + 1
                        continue
                
                # 提取后缀前面的中文字符（最多2个）
                if pos > 0:
                    prefix_chars = []
                    check_pos = pos - 1
                    while check_pos >= 0 and len(prefix_chars) < 2:
                        char = text[check_pos]
                        if '\u4e00' <= char <= '\u9fff':
                            if char in boundary_chars:
                                break
                            prefix_chars.insert(0, char)
                            check_pos -= 1
                        else:
                            break
                    
                    if prefix_chars:
                        full_name = ''.join(prefix_chars) + suffix
                        if full_name not in self.exclusion_list:
                            candidates.add(full_name)
                
                start = pos + 1
        
        return list(candidates)
    
    def extract_from_message(self, message: dict) -> List[tuple]:
        """
        从单条消息提取候选词
        
        Args:
            message: 消息字典
        
        Returns:
            List of (candidate_text, context, source_field)
        """
        # 跳过特定类型
        msg_type = message.get('type', '')
        if msg_type in self.SKIP_TYPES:
            return []
        
        results = []
        
        for field in self.text_fields:
            text = message.get(field)
            if not text or not isinstance(text, str):
                continue
            
            candidates = self.extract_from_text(text)
            for candidate in candidates:
                # 提取上下文（候选词前后各 20 字符）
                context = self._extract_context(text, candidate)
                results.append((candidate, context, field))
        
        return results
    
    def _extract_context(self, text: str, candidate: str, window: int = 20) -> str:
        """提取候选词的上下文"""
        pos = text.find(candidate)
        if pos == -1:
            return text[:50] if len(text) > 50 else text
        
        start = max(0, pos - window)
        end = min(len(text), pos + len(candidate) + window)
        
        context = text[start:end]
        if start > 0:
            context = "..." + context
        if end < len(text):
            context = context + "..."
        
        return context
    
    def extract_from_file(self, input_path: str, 
                          text_fields: List[str] = None,
                          show_progress: bool = True) -> CandidateList:
        """
        从 JSONL 文件流式提取候选词
        
        Args:
            input_path: 输入文件路径 (enriched_full.jsonl 或 agent_sft_l1.jsonl)
            text_fields: 要扫描的文本字段列表（默认使用 DEFAULT_TEXT_FIELDS）
            show_progress: 是否显示进度条
        
        Returns:
            CandidateList: 去重后的候选词列表
        """
        if text_fields:
            self.text_fields = text_fields
        
        result = CandidateList(
            source_file=input_path,
            extraction_time=datetime.now().isoformat(),
        )
        
        path = Path(input_path)
        if not path.exists():
            raise FileNotFoundError(f"输入文件不存在: {input_path}")
        
        # 计算总行数（用于进度条）
        total_lines = 0
        if show_progress:
            with open(path, 'r', encoding='utf-8') as f:
                total_lines = sum(1 for _ in f)
        
        # 流式处理
        with open(path, 'r', encoding='utf-8') as f:
            iterator = tqdm(f, total=total_lines, desc="提取候选词") if show_progress else f
            
            for line in iterator:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    message = json.loads(line)
                    result.total_messages_scanned += 1
                    
                    extractions = self.extract_from_message(message)
                    for candidate, context, source_field in extractions:
                        result.add_candidate(candidate, context, source_field)
                        result.total_texts_scanned += 1
                        
                except json.JSONDecodeError as e:
                    print(f"[WARN] JSON 解析失败: {e}")
                    continue
        
        return result
    
    def get_stats(self, candidate_list: CandidateList) -> dict:
        """获取提取统计信息"""
        candidates = candidate_list.to_list()
        
        # 按频次分布
        freq_dist = {
            '1次': 0,
            '2-5次': 0,
            '6-10次': 0,
            '10次以上': 0,
        }
        
        for c in candidates:
            if c.frequency == 1:
                freq_dist['1次'] += 1
            elif c.frequency <= 5:
                freq_dist['2-5次'] += 1
            elif c.frequency <= 10:
                freq_dist['6-10次'] += 1
            else:
                freq_dist['10次以上'] += 1
        
        return {
            'total_candidates': len(candidates),
            'total_messages_scanned': candidate_list.total_messages_scanned,
            'total_texts_scanned': candidate_list.total_texts_scanned,
            'frequency_distribution': freq_dist,
            'top_10': [(c.text, c.frequency) for c in candidates[:10]],
        }


def main():
    """测试候选词提取器"""
    import sys
    from pathlib import Path
    
    # 添加项目根目录到路径
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
    
    print("=" * 60)
    print("候选词提取器测试")
    print("=" * 60)
    
    from scripts.compression.two_stage_pii.candidate_extractor import CandidateExtractor
    
    extractor = CandidateExtractor()
    
    # 测试单文本提取
    test_texts = [
        "张三和李四约好明天见面",
        "我妈说朋友来了",
        "猫咪在沙发上睡觉",
        "王小明的电话是13812345678",
    ]
    
    print("\n--- 单文本提取测试 ---")
    for text in test_texts:
        candidates = extractor.extract_from_text(text)
        print(f"文本: {text}")
        print(f"  候选词: {candidates}")
    
    # 测试文件提取
    test_file = "timeline_out/agent_sft_l1.jsonl"
    if Path(test_file).exists():
        print(f"\n--- 文件提取测试: {test_file} ---")
        candidate_list = extractor.extract_from_file(test_file)
        stats = extractor.get_stats(candidate_list)
        
        print(f"总候选词: {stats['total_candidates']}")
        print(f"扫描消息数: {stats['total_messages_scanned']}")
        print(f"频次分布: {stats['frequency_distribution']}")
        print(f"Top 10: {stats['top_10']}")
    else:
        print(f"\n[WARN] 测试文件不存在: {test_file}")


if __name__ == '__main__':
    main()
