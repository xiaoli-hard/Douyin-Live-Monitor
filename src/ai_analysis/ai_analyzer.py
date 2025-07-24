import json
import os
import sys
import time
from datetime import datetime, timedelta
import logging
import re
import argparse
from typing import Optional

# --- 路径管理：计算项目根目录 (conclusion/) 的绝对路径 ---
# __file__ -> ai_analyzer.py
# os.path.dirname(__file__) -> .../conclusion/src/ai_analysis
# os.path.join(..., '..', '..') -> .../conclusion
CONCLUSION_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(CONCLUSION_DIR)

from textblob import TextBlob
from openai import OpenAI
from src.ai_analysis.ai_analysis_core import DataAnalyzer, save_analysis_result

# 配置日志 - 避免重复配置
logger = logging.getLogger(__name__)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(CONCLUSION_DIR, 'analyzer.log'), encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

# 加载配置文件
def load_config():
    # 使用 CONCLUSION_DIR 构建健壮的配置文件路径
    config_path = os.path.join(CONCLUSION_DIR, 'src', 'host_script_acquisition', 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    except json.JSONDecodeError:
        raise ValueError("配置文件config.json格式错误，请检查JSON语法")

# --- 新增：标准化时间段格式的辅助函数 ---
def normalize_date(date_str: str) -> str:
    """将各种格式的日期字符串标准化为 'YYYY-MM-DD' 格式"""
    if not isinstance(date_str, str):
        return ""
    # 移除所有空格
    date_str = date_str.replace(" ", "")
    # 匹配 YYYY年MM月DD日 格式
    match_cn = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_str)
    if match_cn:
        year, month, day = match_cn.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    # 匹配 YYYY/MM/DD 格式
    match_slash = re.match(r'(\d{4})/(\d{1,2})/(\d{1,2})', date_str)
    if match_slash:
        year, month, day = match_slash.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    # 匹配 YYYY-MM-DD 格式（已标准化）
    match_dash = re.match(r'(\d{4})-(\d{1,2})-(\d{1,2})', date_str)
    if match_dash:
        return date_str
    logger.warning(f"无法标准化日期格式: {date_str}")
    return date_str

def normalize_time_range(time_str: str) -> str:
    """将各种格式的时间段字符串标准化为 'HH:00-HH:00' 格式"""
    if not isinstance(time_str, str) or time_str.strip() in ['未知', '']:
        return "unknown"
    # 移除所有空格
    # 移除所有空格
    time_str = time_str.replace(" ", "")
    # 增强版正则表达式，支持更多时间格式
    # 匹配范围格式: 10-11, 10:00-11:00, 10点-11点, 10:00-11点等
    match_range = re.match(r'(\d{1,2})(?::\d{2})?[:：点]?[-—~～](\d{1,2})(?::\d{2})?[:：点]?', time_str)
    if match_range:
        start_hour, end_hour = int(match_range.group(1)), int(match_range.group(2))
        return f"{start_hour:02d}:00-{end_hour:02d}:00"
    
    # 匹配单个小时格式: 10, 10:00, 10点, 10时等
    match_single = re.match(r'(\d{1,2})(?::\d{2})?[:：点时]?', time_str)
    if match_single:
        start_hour = int(match_single.group(1))
        return f"{start_hour:02d}:00-{start_hour+1:02d}:00"
    
    # 匹配完整时间格式: 2025-07-17 10:00
    match_full = re.match(r'^\d{4}-\d{2}-\d{2} (\d{2}):\d{2}$', time_str)
    if match_full:
        start_hour = int(match_full.group(1))
        return f"{start_hour:02d}:00-{start_hour+1:02d}:00"
        
    logger.warning(f"无法标准化小时格式: {time_str}")
    return time_str # 返回原始处理过的字符串

# 初始化配置
CONFIG = load_config()
DOUBAO_API_KEY = os.environ.get("ARK_API_KEY", CONFIG['douban_api']['api_key'])

# 初始化豆包API客户端
client = OpenAI(
    base_url=CONFIG['douban_api']['endpoint'],
    api_key=DOUBAO_API_KEY
)


def run_single_analysis(special_variables: Optional[str] = None):
    """
    执行一次性的AI分析。
    从CSV文件读取最新数据，从JSON文件匹配话术内容。
    """
    logger.info("开始执行分析。")
    # --- 初始化 DataAnalyzer 时传入 CONCLUSION_DIR ---
    analyzer = DataAnalyzer(client, CONFIG, CONCLUSION_DIR)
    
    # 调用核心AI分析（新版本不需要传入数据和话术，内部自动读取）
    logger.info("开始AI分析流程...")
    result = analyzer.process_hourly_analysis(special_variables)
    logger.info("AI分析流程已完成")

    # 保存结果
    if CONFIG['data_storage'].get('save_analysis_results', True):
        save_analysis_result(result, CONCLUSION_DIR)
        logger.info("分析已完成并保存。")
    else:
        logger.info("分析已完成，未保存结果。")


def start_monitoring(interval: int = 60):
    """
    监控CSV数据文件的变化，并在检测到新数据时触发分析。

    Args:
        interval (int): 检查数据变化的间隔时间（秒）。
    """
    logger.info(f"监控模式已启动，每 {interval} 秒检查一次数据更新。")
    csv_path = os.path.join(CONCLUSION_DIR, 'data', 'baseline_data', 'new_format_data.csv')
    
    # 初始化时获取当前最新数据作为已处理的数据，避免重复分析
    last_processed_data_key = None
    try:
        if os.path.exists(csv_path):
            import pandas as pd
            df = pd.read_csv(csv_path, on_bad_lines='skip')
            if len(df) > 0:
                current_data = df.iloc[-1].to_dict()
                last_processed_data_key = f"{current_data.get('日期', '')}-{current_data.get('小时', '')}"
                logger.info(f"监控模式初始化：当前最新数据为 {last_processed_data_key}，将作为已处理数据")
    except Exception as e:
        logger.warning(f"监控模式初始化时读取CSV失败: {e}")

    while True:
        try:
            logger.debug("监控循环：正在检查CSV数据文件...")
            
            if os.path.exists(csv_path):
                import pandas as pd
                try:
                    # 添加错误处理，忽略字段数不匹配的行
                    df = pd.read_csv(csv_path, on_bad_lines='skip')
                except Exception as e:
                    logger.error(f"读取CSV文件失败: {e}")
                    time.sleep(interval)
                    continue
                
                if len(df) > 0:
                    # 获取最后一行数据作为当前数据
                    current_data = df.iloc[-1].to_dict()
                    current_data_key = f"{current_data.get('日期', '')}-{current_data.get('小时', '')}"
                    
                    if current_data_key != last_processed_data_key:
                        logger.info(f"检测到新的数据（{current_data_key}），准备执行分析。")
                        
                        # 执行分析
                        run_single_analysis()
                        
                        # 更新最后处理的数据标识
                        last_processed_data_key = current_data_key
                    else:
                        logger.debug(f"数据未发生变化（当前key: {current_data_key}）。")
                else:
                    logger.debug("CSV文件为空。")
            else:
                logger.debug(f"CSV文件不存在: {csv_path}")

        except Exception as e:
            logger.error(f"监控循环中发生错误: {e}", exc_info=True)
        
        # 等待指定的时间间隔
        time.sleep(interval)


def analyze_product_mentions(speech_content):
    """分析话术中的产品提及"""
    # 预定义PWU相关产品类别
    product_patterns = {
        # PWU系列产品 - 只保留相关产品
        r"(PWU洗衣留香珠|留香珠|洗衣珠|PWU|衣物护理)": "PWU洗衣留香珠",
        r"(持久留香|香味持久|留香时长|长效留香)": "持久留香功能",
        r"(除菌除螨|抑菌|抗菌|除螨|杀菌)": "除菌除螨功能",
        r"(衣物香水|衣物护理|衣物清洁|衣物除味)": "衣物护理系列",
        r"(居家好物|家居好物|家庭必备|日用好物)": "居家好物系列"
    }
    
    # 提取所有产品提及
    product_mentions = {}
    for pattern, product_name in product_patterns.items():
        matches = re.findall(pattern, speech_content, re.IGNORECASE)  # 使用忽略大小写的匹配
        if matches:
            count = len(matches)
            if product_name in product_mentions:
                product_mentions[product_name] += count
            else:
                product_mentions[product_name] = count
    
    # 特别检查PWU产品，如果没有匹配到，尝试使用更宽松的匹配
    if "PWU洗衣留香珠" not in product_mentions and "持久留香功能" not in product_mentions:
        # 尝试更宽松的匹配
        loose_patterns = [
            r"洗衣",
            r"留香",
            r"PWU",
            r"珠",
            r"清香",
            r"香味"
        ]
        
        for pattern in loose_patterns:
            matches = re.findall(pattern, speech_content, re.IGNORECASE)
            if matches:
                product_mentions["PWU洗衣留香珠"] = len(matches)  # 改为直接使用PWU洗衣留香珠作为产品名
                break
    
    # 按提及次数排序
    sorted_mentions = {k: v for k, v in sorted(product_mentions.items(), key=lambda item: item[1], reverse=True)}
    return sorted_mentions


def main():
    """
    主函数，根据命令行参数执行不同模式。
    """
    parser = argparse.ArgumentParser(description="直播话术AI分析服务")
    parser.add_argument(
        '--variables',
        type=str,
        default=None,
        help='影响分析的特殊变量 (例如: "618大促期间, 更换了主播")'
    )
    parser.add_argument(
        '--monitor-interval',
        type=int,
        default=60,
        help='监控模式下检查数据变化的间隔时间（秒），默认60秒'
    )
    
    args = parser.parse_args()

    # 立即执行一次分析
    logger.info("脚本启动，立即执行一次分析...")
    run_single_analysis(args.variables)
    
    # 进入监控模式
    logger.info("初始分析完成，现在进入监控模式...")
    start_monitoring(args.monitor_interval)

if __name__ == "__main__":
    main()