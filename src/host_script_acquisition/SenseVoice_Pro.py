# -*- encoding: utf-8 -*-
import sys
import os
import sqlite3
import numpy as np
import sounddevice as sd
import time
import threading
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QTabWidget, QLabel, QLineEdit, QPushButton, QComboBox,
                             QCheckBox, QGroupBox, QTextEdit, QFileDialog)
from PyQt6.QtCore import Qt, QObject, pyqtSignal
import json

def load_config(config_path="config.json"):
    """
    加载配置文件
    :param config_path: 配置文件路径
    :return: 配置字典
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"加载配置文件失败: {e}")
        # 返回默认配置
        return {
            "data_storage": {
                "realtime_output_dir": "d:\\Text\\conclusion\\text"
            }
        }

# === NLP清洗相关代码开始 ===
import re
from aip import AipNlp
import datetime as dt2

APP_ID = '119362232'
API_KEY = '8PRLv5GcZnuckruktdaOADU1'
SECRET_KEY = '32GyMDQ7yWw0ctc8mVkN6CZWFDC1yKS'
client = AipNlp(APP_ID, API_KEY, SECRET_KEY)
custom_words = ["六一八返场福利", "香奈儿", "Prada", "欧莱雅", "洗发水", "护发", "滋养修复", "柔顺洗发露", "润养秀发", "发质洗发乳"]

def protect_custom_words(text, custom_words):
    for idx, word in enumerate(custom_words):
        text = text.replace(word, f"__CUSTOM{idx}__")
    return text

def restore_custom_words(text, custom_words):
    for idx, word in enumerate(custom_words):
        text = text.replace(f"__CUSTOM{idx}__", word)
    return text

def remove_emoji(text):
    # 保留中文、英文、数字和基本标点，过滤其他特殊字符
    text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9。，,；;！!？?：: ]', '', text)
    # 过滤单字符重复序列（如"s g s"或"sgs"）
    text = re.sub(r'\b(\w)\s*\1\s*\1\b', '', text)  # 匹配带空格的三重复字符
    text = re.sub(r'\b(\w)\1{2,}\b', '', text)        # 匹配不带空格的三重复字符
    # 过滤孤立的单字符
    text = re.sub(r'\b\w\b', '', text)
    # 清理多余空格
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def remove_modal_words(text):
    # 只移除句末的语气词
    modal_pattern = re.compile(r'([啊呢吧呀呃哎哦嘛啦呗哈哇欸咦唉嘿哟哩哼嗯嘞哒])$')
    sentences = text.split('。')
    cleaned_sentences = []
    for sent in sentences:
        if sent.strip():
            cleaned = modal_pattern.sub('', sent)
            cleaned_sentences.append(cleaned)
    return '。'.join(cleaned_sentences) + '。' if cleaned_sentences else ''

def split_sentences(text):
    sentences = re.split(r'[。！？；]', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    return '。'.join(sentences) + '。' if sentences else ''

def get_lexer_words(text):
    try:
        result = client.lexer(text)
        if isinstance(result, dict) and 'items' in result:
            return [item['item'] for item in result['items'] if isinstance(item, dict) and 'item' in item]
        else:
            return []
    except Exception as e:
        return []

def get_keywords_baidu(text, top_k=20):
    try:
        result = client.keyword('', text)
        if isinstance(result, dict) and 'items' in result:
            return [item['tag'] for item in result['items'][:top_k] if isinstance(item, dict) and 'tag' in item]
        else:
            return []
    except Exception as e:
        return []

def get_text_correction(text):
    try:
        protected_text = protect_custom_words(text, custom_words)
        result = client.ecnet(protected_text)
        if isinstance(result, dict) and 'item' in result and isinstance(result['item'], dict) and 'correct_query' in result['item']:
            corrected = result['item']['correct_query']
            corrected = restore_custom_words(corrected, custom_words)
            return corrected
        else:
            return restore_custom_words(protected_text, custom_words)
    except Exception as e:
        return restore_custom_words(text, custom_words)

def extract_items(data):
    all_texts = []
    if isinstance(data, dict):
        text = data.get('text', '').strip()
        if text:
            all_texts.append(text)
    elif isinstance(data, list):
        for item in data:
            all_texts.extend(extract_items(item))
    return all_texts

def extract_time_info(filename):
    date = ""
    time_range = ""
    match_date = re.search(r'20\d{2}-\d{2}-\d{2}', filename)
    if match_date:
        date = match_date.group(0)
    # 匹配新的文件名格式（例如: transcripts_JSON_实时_2025-07-07_10.json）
    match_time = re.search(r'_实时_(\d{4}-\d{2}-\d{2}_\d{2})\.json$', filename)
    if match_time:
        hour_str = match_time.group(1).split('_')[1]
        hour = int(hour_str)
        # 生成07:00-08:00格式的时间段
        time_range = f"{hour:02d}:00-{(hour + 1) % 24:02d}:00"
    else:
        # 兼容旧的文件名格式
        match_time_old = re.search(r'_(\d{2})\.json$', filename)
        if match_time_old:
            hour = int(match_time_old.group(1))
            time_range = f"{hour:02d}:00-{(hour + 1) % 24:02d}:00"
    return date, time_range

def clean_text_nlp(input_json_path, output_dir):
    fname = os.path.basename(input_json_path)
    with open(input_json_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except Exception:
            return None
    all_texts = extract_items(data)
    all_text = '。'.join(all_texts)
    all_text = remove_emoji(all_text)
    all_text = remove_modal_words(all_text)
    all_text = split_sentences(all_text)
    date, time_range = extract_time_info(fname)
    if not time_range:
        print(f"错误: 无法从文件名 '{fname}' 中提取时间段信息，跳过处理。")
        return None

    result = {
        "文件名": fname,
        "日期": date,
        "小时": time_range,
        "text": all_text
    }
    # 固定输出文件名，实现数据追加并保留最新两条
    output_json_path = os.path.join(output_dir, "latest_two_cleaned.json")
    try:
        # 读取现有数据
        with open(output_json_path, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing_data = []
    # 添加新数据并保留最新两条
    # 检查是否已有相同日期和时间段的条目
    found = False
    for i, item in enumerate(existing_data):
        if item["日期"] == result["日期"] and item["小时"] == result["小时"]:
            # 追加文本内容
            existing_data[i]["text"] += result["text"]
            found = True
            break
    if not found:
        existing_data.append(result)

    # 按日期和时间段排序，保留最新的数据
    def get_datetime_key(item):
        try:
            # 解析日期
            date_str = item["日期"]
            hour_str = item["小时"]
            if not hour_str:
                return datetime.min
            
            # 提取小时
            hour = int(hour_str.split(":")[0])
            
            # 创建datetime对象进行比较
            year, month, day = map(int, date_str.split("-"))
            return datetime(year, month, day, hour)
        except:
            return datetime.min

    existing_data.sort(key=get_datetime_key, reverse=True)
    # 去重，每个时间段只保留一个条目
    seen_time_ranges = set()
    unique_data = []
    for item in existing_data:
        key = (item["日期"], item["小时"])
        if key not in seen_time_ranges:
            seen_time_ranges.add(key)
            unique_data.append(item)
    # 保留最新的两个时间段
    # 保留所有时间段数据而非仅最新两条
    existing_data = unique_data[:3]  # 仅保留最新的3条数据
    # 写入更新后的数据
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=2)
    output_db_path = os.path.join(output_dir, f"all_cleaned_{dt2.datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    conn = sqlite3.connect(output_db_path)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cleaned_texts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT,
        date TEXT,
        time_range TEXT,
        text TEXT
    )
    """)
    cursor.execute("INSERT INTO cleaned_texts (filename, date, time_range, text) VALUES (?, ?, ?, ?)",
                   (result["文件名"], result["日期"], result["小时"], result["text"]))
    conn.commit()
    conn.close()
    print(f'清洗完成，输出: {output_json_path} 和 {output_db_path}')
    return output_json_path, output_db_path
# === NLP清洗相关代码结束 ===

try:
    # 添加numpy兼容性补丁，解决funasr导入时的numpy.complex错误
    import numpy as np
    if not hasattr(np, 'complex'):
        np.complex = complex
    
    from funasr import AutoModel
    from funasr.utils.postprocess_utils import rich_transcription_postprocess
    FUNASR_AVAILABLE = True
except ImportError:
    FUNASR_AVAILABLE = False

class SenseVoicePro(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SenseVoice语音文字识别V3 | UI&整合包: AI画师大阳")
        self.setGeometry(100, 100, 650, 600)

        # 创建主选项卡
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # 创建两个标签页
        self.file_tab = QWidget()
        self.realtime_tab = QWidget()

        self.tabs.addTab(self.file_tab, "音视频文件识别")
        self.tabs.addTab(self.realtime_tab, "实时语音识别")

        # 初始化每个标签页的UI
        self.init_file_tab_ui()
        self.init_realtime_tab_ui()

    def init_file_tab_ui(self):
        layout = QVBoxLayout(self.file_tab)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- 待识别音视频 ---
        file_layout = QHBoxLayout()
        file_layout.addWidget(QLabel("待识别音视频:"))
        self.file_input_path = QLineEdit()
        file_layout.addWidget(self.file_input_path)
        self.select_file_btn = QPushButton("选择文件")
        file_layout.addWidget(self.select_file_btn)
        layout.addLayout(file_layout)

        # --- 选择保存位置 ---
        save_loc_layout = QHBoxLayout()
        save_loc_layout.addWidget(QLabel("选择保存位置:"))
        self.file_output_path = QLineEdit()
        save_loc_layout.addWidget(self.file_output_path)
        self.select_save_loc_btn = QPushButton("保存位置")
        save_loc_layout.addWidget(self.select_save_loc_btn)
        layout.addLayout(save_loc_layout)
        
        # --- 参数行1 ---
        param1_layout = QHBoxLayout()
        param1_layout.addWidget(QLabel("batch size:"))
        self.batch_size_input = QLineEdit("60")
        self.batch_size_input.setFixedWidth(50)
        param1_layout.addWidget(self.batch_size_input)
        param1_layout.addStretch()
        layout.addLayout(param1_layout)
        
        # --- 参数行2 ---
        param2_layout = QHBoxLayout()
        param2_layout.addWidget(QLabel("翻译工具:"))
        self.file_trans_tool_combo = QComboBox()
        self.file_trans_tool_combo.addItems(["", "百度", "google"])
        param2_layout.addWidget(self.file_trans_tool_combo)

        param2_layout.addWidget(QLabel("目标语言:"))
        self.file_target_lang_combo = QComboBox()
        self.file_target_lang_combo.addItems(["", "中文", "英语", "日语", "韩语", "法语", "德语"])
        param2_layout.addWidget(self.file_target_lang_combo)
        param2_layout.addStretch()
        layout.addLayout(param2_layout)

        # --- 开始处理按钮 ---
        self.file_start_btn = QPushButton("开始处理")
        layout.addWidget(self.file_start_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # --- 说明 ---
        desc_box = QGroupBox("说明")
        desc_layout = QVBoxLayout()
        desc_text = (
            "1、保存类型为txt文本格式和srt字幕格式\n"
            "2、batch size值越大，识别速度越快，如果出现显存或内存错误，可降低该值\n"
            "3、翻译工具国内用户请用百度，国外用户请用google\n"
            "4、待处理目标可设置为文件夹"
        )
        desc_label = QLabel(desc_text)
        desc_label.setWordWrap(True)
        desc_layout.addWidget(desc_label)
        desc_box.setLayout(desc_layout)
        layout.addWidget(desc_box)
        layout.addStretch()

    def init_realtime_tab_ui(self):
        layout = QVBoxLayout(self.realtime_tab)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    
        # --- 保存位置 --- 
        save_loc_layout = QHBoxLayout()
        save_loc_layout.addWidget(QLabel("识别文本保存目录:"))
        
        # 从配置文件读取默认路径
        config = load_config(os.path.join(os.path.dirname(__file__), "config.json"))
        default_output_dir = config.get("data_storage", {}).get("realtime_output_dir", "d:\\Text\\conclusion\\text")
        
        self.realtime_output_path = QLineEdit(default_output_dir)
        save_loc_layout.addWidget(self.realtime_output_path)
        self.realtime_select_dir_btn = QPushButton("选择目录")
        save_loc_layout.addWidget(self.realtime_select_dir_btn)
        layout.addLayout(save_loc_layout)
        self.realtime_select_dir_btn.clicked.connect(self.select_realtime_output_dir)

        # --- 导出间隔设置 ---
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("导出间隔(分钟):"))
        self.export_interval_input = QLineEdit("60")
        self.export_interval_input.setFixedWidth(60)
        interval_layout.addWidget(self.export_interval_input)
        interval_layout.addStretch()
        layout.addLayout(interval_layout)

        # --- 参数网格布局 ---
        grid_layout = QHBoxLayout()
        
        # 左侧
        left_v_layout = QVBoxLayout()
        params = [
            ("块长度:", ["8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18"]),
            ("上下文长度:", ["7"]),
            ("音量阈值:", "0.001")
        ]
        for name, val in params:
            h_layout = QHBoxLayout()
            h_layout.addWidget(QLabel(name))
            if isinstance(val, list):
                combo = QComboBox()
                combo.addItems(val)
                h_layout.addWidget(combo)
            else:
                line_edit = QLineEdit(val)
                h_layout.addWidget(line_edit)
            left_v_layout.addLayout(h_layout)
        grid_layout.addLayout(left_v_layout)

        # 右侧
        right_v_layout = QVBoxLayout()
        params_right = [
            ("翻译工具:", ["", "百度", "google"]),
            ("目标语言:", ["", "中文", "英语", "日语", "韩语", "法语", "德语"]),
            ("待翻译文本长度:", "25"),
            ("音源:", ["麦克风", "系统内录"])
        ]
        for name, val in params_right:
            h_layout = QHBoxLayout()
            h_layout.addWidget(QLabel(name))
            if isinstance(val, list):
                combo = QComboBox()
                combo.addItems(val)
                h_layout.addWidget(combo)
            else:
                line_edit = QLineEdit(val)
                h_layout.addWidget(line_edit)
            right_v_layout.addLayout(h_layout)
        grid_layout.addLayout(right_v_layout)
        layout.addLayout(grid_layout)

        # --- 实时翻译复选框 ---
        self.show_trans_checkbox = QCheckBox("实时显示翻译结果")
        layout.addWidget(self.show_trans_checkbox)

        # --- 开始/停止处理按钮 ---
        btn_layout = QHBoxLayout()
        self.realtime_start_btn = QPushButton("开始识别")
        self.realtime_stop_btn = QPushButton("停止识别")
        btn_layout.addWidget(self.realtime_start_btn)
        btn_layout.addWidget(self.realtime_stop_btn)
        layout.addLayout(btn_layout)
        self.realtime_start_btn.clicked.connect(self.start_realtime_recognition)
        self.realtime_stop_btn.clicked.connect(self.stop_realtime_recognition)

        # --- 日志显示框 ---
        self.realtime_log_box = QTextEdit()
        self.realtime_log_box.setReadOnly(True)
        layout.addWidget(self.realtime_log_box)

        # --- 新增：实时识别文本显示框 ---
        self.realtime_recognized_text_display = QTextEdit()
        self.realtime_recognized_text_display.setReadOnly(True)
        self.realtime_recognized_text_display.setPlaceholderText("实时识别的文字将显示在这里...")
        layout.addWidget(self.realtime_recognized_text_display)

        # --- 说明 ---
        desc_box = QGroupBox("说明")
        desc_layout = QVBoxLayout()
        desc_text = """1、块和上下文长度影响识别速度与准确度，可自行调整参数测试识别效果
2、如果环境比较嘈杂，接收到了许多无效音频片段，可增大音量阈值
3、翻译工具国内用户请用百度，国外用户请用google
4、如果是英文章节类型，待翻译文本长度可调大，类中文语言类型该值可调小"""
        desc_label = QLabel(desc_text)
        desc_label.setWordWrap(True)
        desc_layout.addWidget(desc_label)
        desc_box.setLayout(desc_layout)
        layout.addWidget(desc_box)
        layout.addStretch()

    def select_realtime_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择识别文本保存目录")
        if dir_path:
            self.realtime_output_path.setText(dir_path)

    def start_realtime_recognition(self):
        export_dir = self.realtime_output_path.text() or os.getcwd()
        try:
            export_interval = int(float(self.export_interval_input.text()) * 60)
        except Exception:
            export_interval = 3600

        self.recognizer = RealtimeRecognizer(export_dir, export_interval)
        self.recognizer.log_signal.connect(self.realtime_log_box.append)
        self.recognizer.recognized_text_signal.connect(self.update_recognized_text_display)
        self.recognizer.start()
        self.realtime_log_box.append("实时识别已启动...")
        self.realtime_start_btn.setEnabled(False)
        self.realtime_stop_btn.setEnabled(True)

    def stop_realtime_recognition(self):
        if hasattr(self, 'recognizer') and self.recognizer:
            self.recognizer.stop()
            self.realtime_log_box.append("实时识别已停止。")
            # 强制清洗
            try:
                output_dir = self.realtime_output_path.text() or os.getcwd()
                current_json_path = self.recognizer.current_json_path
                if current_json_path and os.path.exists(current_json_path):
                    self.realtime_log_box.append(f"开始清洗当前实时JSON文件: {current_json_path}")
                    clean_text_nlp(current_json_path, output_dir)
                    self.realtime_log_box.append(f"NLP清洗已完成，输出已保存到: {output_dir}")
                else:
                    self.realtime_log_box.append("未找到当前实时JSON文件进行清洗。")
            except Exception as e:
                self.realtime_log_box.append(f"NLP清洗失败: {e}")
        self.realtime_start_btn.setEnabled(True)
        self.realtime_stop_btn.setEnabled(False)

    def update_recognized_text_display(self, text):
        """更新实时识别文本显示框"""
        current_text = self.realtime_recognized_text_display.toPlainText()
        if current_text:
            self.realtime_recognized_text_display.setPlainText(current_text + " " + text)
        else:
            self.realtime_recognized_text_display.setPlainText(text)
        
        # 修正 linter 错误：确保滚动条存在再操作
        scrollbar = self.realtime_recognized_text_display.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum()) # 自动滚动到底部

class RealtimeRecognizer(QObject):
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    recognized_text_signal = pyqtSignal(str)

    def __init__(self, export_dir, export_interval, sample_rate=16000, record_seconds=3, device="cpu"):
        super().__init__()
        self.export_dir = export_dir
        self.export_interval = export_interval # This is now the duration of each hourly file
        self.sample_rate = sample_rate
        self.record_seconds = record_seconds
        self.device = device
        self._stop_event = threading.Event()
        self._stream = None
        self._rollover_thread = None 
        self._record_thread = None
        self.model = None
        self.running = False

        self.current_db_path = None
        self.current_json_path = None
        # Initial creation of hourly files
        self._create_new_hourly_files()


    def _create_new_hourly_files(self):
        # 获取当前时间的小时级时间戳
        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d_%H")

        # 构建文件路径
        self.current_json_path = os.path.join(self.export_dir, f"transcripts_JSON_实时_{timestamp_str}.json")
        self.current_db_path = os.path.join(self.export_dir, f"transcripts_DB_实时_{timestamp_str}.db")

        # 检查JSON文件是否已存在
        if os.path.exists(self.current_json_path):
            self.log_signal.emit(f"已存在该小时的JSON文件，将继续追加数据: {self.current_json_path}")
        else:
            # 创建新的JSON文件
            try:
                with open(self.current_json_path, 'w', encoding='utf-8') as f:
                    json.dump([], f, ensure_ascii=False, indent=2)
                self.log_signal.emit(f"新的JSON文件创建成功: {self.current_json_path}")
            except Exception as e:
                self.log_signal.emit(f"创建新的JSON文件失败: {e}")
                raise # Critical error, cannot proceed

        # 检查DB文件是否已存在
        if os.path.exists(self.current_db_path):
            self.log_signal.emit(f"已存在该小时的数据库文件，将继续追加数据: {self.current_db_path}")
        else:
            # 创建新DB文件
            try:
                conn = sqlite3.connect(self.current_db_path)
                cursor = conn.cursor()
                cursor.execute("""
                CREATE TABLE transcripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    text TEXT NOT NULL
                )
                """)
                conn.commit()
                conn.close()
                self.log_signal.emit(f"新的数据库文件创建成功: {self.current_db_path}")
            except Exception as e:
                self.log_signal.emit(f"创建新的数据库文件失败: {e}")
                raise # Critical error, cannot proceed


    def start(self):
        if not FUNASR_AVAILABLE:
            self.log_signal.emit("未安装 funasr，无法启动识别！")
            return
        if self.running:
            self.log_signal.emit("识别已在运行中！")
            return
        self.running = True
        self._stop_event.clear()
        self.log_signal.emit("正在初始化模型...")
        try:
            self.model = AutoModel(
                model="iic/SenseVoiceSmall",
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 30000},
                device=self.device,
            )
            self.log_signal.emit("模型初始化完毕！")
        except Exception as e:
            self.log_signal.emit(f"模型初始化失败: {e}")
            self.running = False
            return

        # Start rollover thread
        self._rollover_thread = threading.Thread(target=self._hourly_file_rollover_worker, daemon=True)
        self._rollover_thread.start()

        # Start record thread
        self._record_thread = threading.Thread(target=self.record_loop, daemon=True)
        self._record_thread.start()
        self.log_signal.emit("实时识别已启动...")

    def stop(self):
        self._stop_event.set()
        self.running = False
        self.log_signal.emit("正在停止识别...")
        if self._stream:
            try:
                self._stream.close()
            except Exception:
                pass
        self.log_signal.emit("识别已停止。")

    def save_to_realtime_json(self, text):
        try:
            data = []
            # Ensure current_json_path is not None before using it
            if self.current_json_path is None:
                self.log_signal.emit("错误: 实时JSON文件路径未初始化。")
                return

            if os.path.exists(self.current_json_path) and os.path.getsize(self.current_json_path) > 0:
                with open(self.current_json_path, 'r', encoding='utf-8') as f:
                    try:
                        data = json.load(f)
                    except json.JSONDecodeError:
                        self.log_signal.emit(f"警告: 实时JSON文件 '{self.current_json_path}' 内容损坏或为空，将从新开始写入。")
                        data = []

            timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data.append({"timestamp": timestamp_str, "text": text})

            with open(self.current_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # self.log_signal.emit(f"已实时写入JSON文件: {text}") # 如果这个日志太频繁，可以注释掉

        except Exception as e:
            self.log_signal.emit(f"实时JSON保存失败: {e}")

    def get_db_connection(self):
        # Ensure current_db_path is not None before using it
        if self.current_db_path is None:
            self.log_signal.emit("错误: 数据库文件路径未初始化。")
            return None # Return None if path is not set

        conn = sqlite3.connect(self.current_db_path) # Connect to current DB path
        return conn

    def save_to_db(self, text):
        if not text or text.strip() == "UNK":
            return
        try:
            conn = self.get_db_connection()
            if conn is None: # Check if connection was successful
                return
            cursor = conn.cursor()
            cursor.execute("INSERT INTO transcripts (text, timestamp) VALUES (?, DATETIME('now'))", (text,))
            conn.commit()
            conn.close()
            # self.log_signal.emit(f"已存入数据库: {text}") # Keep logs concise
        except Exception as e:
            self.log_signal.emit(f"数据库保存失败: {e}")

    # Renamed and repurposed: This worker is now responsible for rolling over files hourly
    def _hourly_file_rollover_worker(self):
        current_hour = datetime.now().hour
        while not self._stop_event.is_set():
            time.sleep(60)  # 每分钟检查一次小时变化
            now = datetime.now()
            if now.hour != current_hour:
                previous_hour_json_path = self.current_json_path
                current_hour = now.hour
                self.log_signal.emit(f"--- [小时已切换至 {current_hour} 点，正在创建新的文件] ---")
                try:
                    self._create_new_hourly_files()
                    self.log_signal.emit("新的实时文件已创建，将继续识别到新文件。")
                    
                    if previous_hour_json_path and os.path.exists(previous_hour_json_path):
                        self.log_signal.emit(f"开始清洗上一个小时的文本文件: {previous_hour_json_path}")
                        # 自动调用NLP清洗
                        clean_text_nlp(previous_hour_json_path, self.export_dir)
                        self.log_signal.emit(f"NLP清洗已完成，输出已保存到: {self.export_dir}")

                except Exception as e:
                    self.log_signal.emit(f"文件轮换或清洗失败: {e}")

    def record_loop(self):
        try:
            with sd.InputStream(callback=self.audio_callback, channels=1, samplerate=self.sample_rate, blocksize=int(self.sample_rate * self.record_seconds)) as stream:
                self._stream = stream
                while not self._stop_event.is_set():
                    time.sleep(1)
        except Exception as e:
            self.log_signal.emit(f"录音流出错: {e}")

    def audio_callback(self, indata, frames, time_info, status):
        if status:
            self.log_signal.emit(str(status))
        audio_data = indata.flatten().astype(np.float32)
        try:
            if self.model is None:
                self.log_signal.emit("模型未初始化，无法识别。")
                return
            res = self.model.generate(
                input=audio_data,
                samplerate=self.sample_rate,
                language="auto",
                use_itn=False,
            )
            if res and res[0].get("text"):
                processed_text = rich_transcription_postprocess(res[0]["text"])
                self.save_to_db(processed_text)
                self.save_to_realtime_json(processed_text)
                # self.hourly_texts.append(processed_text) # 将文本追加到list - DELETED
                self.recognized_text_signal.emit(processed_text)
        except Exception as e:
            self.log_signal.emit(f"识别出错: {e}")

if __name__ == '__main__':
    # 检查是否有命令行参数来决定运行模式
    if len(sys.argv) > 1 and sys.argv[1] == '--clean':
        # 命令行模式下自动执行清洗并退出
        input_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../text')
        output_dir = input_dir
        
        # 获取所有JSON文件
        json_files = [f for f in os.listdir(input_dir) if f.startswith('transcripts_JSON_实时_') and f.endswith('.json')]
        json_files.sort(reverse=True)
        
        # 处理最新的两个文件
        for file in json_files[:2]:
            input_path = os.path.join(input_dir, file)
            clean_text_nlp(input_path, output_dir)
            print(f'已处理: {file}')
        
        print('数据清洗完成，已生成latest_two_cleaned.json')
    else:
        # GUI模式
        app = QApplication(sys.argv)
        window = SenseVoicePro()
        window.show()
        sys.exit(app.exec())