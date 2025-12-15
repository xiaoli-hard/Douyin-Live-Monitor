import json
import os
import sys
import time
from datetime import datetime, timedelta
import logging
import re
import argparse
from typing import Optional
import schedule

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


def start_scheduled_analysis(special_variables: Optional[str] = None):
    """
    启动定时分析任务，每小时的11分执行一次分析。
    """
    logger.info("定时分析模式已启动，每小时的11分执行一次分析。")
    
    # 定义分析任务函数
    def scheduled_analysis_task():
        try:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"[{current_time}] 开始执行定时分析任务...")
            run_single_analysis(special_variables)
            logger.info(f"[{current_time}] 定时分析任务完成。")
        except Exception as e:
            logger.error(f"定时分析任务执行失败: {e}", exc_info=True)
    
    # 安排每小时的11分执行任务
    schedule.every().hour.at(":11").do(scheduled_analysis_task)
    
    logger.info("定时任务已设置：每小时的11分执行分析（如9:11, 10:11, 11:11...）")
    
    # 主循环
    while True:
        try:
            schedule.run_pending()
            time.sleep(30)  # 每30秒检查一次是否有待执行的任务
        except Exception as e:
            logger.error(f"定时任务调度器发生错误: {e}", exc_info=True)
            time.sleep(60)  # 出错时等待1分钟再继续


def analyze_product_mentions(speech_content):
    """分析话术中的产品提及"""
    # 预定义欧莱雅洗发水相关产品类别
    product_patterns = {
        # 欧莱雅洗发水系列产品
        r"(欧莱雅洗发水|欧莱雅|洗发水|洗发露|护发|洗发乳)": "欧莱雅洗发水",
        r"(滋养修复|修复发质|滋养|修复|润养秀发)": "滋养修复功效",
        r"(柔顺|顺滑|丝滑|柔软|光泽)": "柔顺护发功效",
        r"(发质改善|发质护理|头发护理|护发素|发膜)": "发质护理系列",
        r"(专业护发|品牌洗护|洗护用品|个护用品)": "专业洗护系列"
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
    
    # 特别检查欧莱雅洗发水产品，如果没有匹配到，尝试使用更宽松的匹配
    if "欧莱雅洗发水" not in product_mentions and "滋养修复功效" not in product_mentions:
        # 尝试更宽松的匹配
        loose_patterns = [
            r"洗发",
            r"护发",
            r"欧莱雅",
            r"发质",
            r"滋养",
            r"修复"
        ]
        
        for pattern in loose_patterns:
            matches = re.findall(pattern, speech_content, re.IGNORECASE)
            if matches:
                product_mentions["欧莱雅洗发水"] = len(matches)  # 改为直接使用欧莱雅洗发水作为产品名
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
    
    args = parser.parse_args()

    # 立即执行一次分析
    logger.info("脚本启动，立即执行一次分析...")
    run_single_analysis(args.variables)
    
    # 进入定时分析模式
    logger.info("初始分析完成，现在进入定时分析模式...")
    start_scheduled_analysis(args.variables)

if __name__ == "__main__":
    main()