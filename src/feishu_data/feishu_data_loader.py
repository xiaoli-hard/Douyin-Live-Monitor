import json
import os
import logging
import csv
from datetime import datetime
from typing import Optional

# 配置日志
logger = logging.getLogger(__name__)

# 加载配置文件
def load_config():
    # 计算项目根目录的绝对路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.normpath(os.path.join(current_dir, '..', '..'))
    config_path = os.path.join(project_root, 'src', 'host_script_acquisition', 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError("配置文件config.json不存在，请创建该文件")
    except json.JSONDecodeError:
        raise ValueError("配置文件config.json格式错误，请检查JSON语法")

# 初始化配置
CONFIG = load_config()

def load_feishu_data(file_path='data/raw/feishu_sheet_data.json', target_date: Optional[str] = None):
    """加载飞书表格数据"""
    try:
        # 检查文件是否存在
        if not os.path.exists(file_path):
            logger.error(f"飞书数据文件不存在: {os.path.abspath(file_path)}")
            return None, None
        
        with open(file_path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                # 处理可能的数组结构，取最后一条记录
                # 保留所有记录用于对比分析
                if not isinstance(data, list):
                    logger.warning("飞书数据格式应为数组，已转换为单元素数组")
                    data = [data]
                # 按时间排序数据
                try:
                    for entry in data:
                        # 解析日期和时间（增强容错性）
                        date_str = entry.get("日期", "")
                        time_str = entry.get("小时", "").split("-")[0].strip() if entry.get("小时") else ""
                        if date_str and time_str:
                            try:
                                datetime_str = f"{date_str} {time_str}"
                                entry["datetime"] = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                            except ValueError:
                                # 添加更灵活的日期格式支持
                                for fmt in ["%Y/%m/%d %H:%M", "%Y年%m月%d日 %H:%M"]:
                                    try:
                                        entry["datetime"] = datetime.strptime(datetime_str, fmt)
                                        break
                                    except ValueError:
                                        continue
                                else:
                                    logger.warning(f"无法解析时间格式: {date_str} {time_str}")
                                    entry["datetime"] = datetime.min  # 赋予最小时间值以便排序
                        else:
                            logger.warning(f"缺少日期或小时: {entry}")
                            entry["datetime"] = datetime.min
                    # 按时间排序
                    data.sort(key=lambda x: x["datetime"])
                except (KeyError, ValueError) as e:
                    logger.warning(f"无法排序数据，使用原始顺序: {str(e)}")
                # 调试日志：打印数据结构
                logger.debug(f"飞书数据结构: {list(data[0].keys())[:5]}...")  # 只打印前5个键避免过长
            except json.JSONDecodeError as e:
                logger.error(f"JSON解析失败: {str(e)}，文件路径: {os.path.abspath(file_path)}")
                return None, None
        
        # 验证必要字段并处理每个条目
        required_fields = ['整体GMV', '消耗', '点击转化率', '客单价', '小时']
        valid_entries = []
        
        for entry in data:
            # 检查单个条目的必要字段
            missing_fields = [field for field in required_fields if field not in entry]
            if missing_fields:
                logger.error(f"飞书数据条目缺少必要字段: {missing_fields}, 条目: {entry}")
                continue
            
            # 映射并转换数据类型
            try:
                # 辅助函数：安全转换为float
                def safe_float(value):
                    if value == '' or value is None:
                        return 0
                    try:
                        return float(value)
                    except (ValueError, TypeError):
                        return 0
                
                # 辅助函数：安全转换为int
                def safe_int(value):
                    if value == '' or value is None:
                        return 0
                    try:
                        return int(float(value))
                    except (ValueError, TypeError):
                        return 0
                
                mapped_entry = {
                    "整体GMV": safe_float(entry['整体GMV']),
                    "消耗": safe_float(entry['消耗']),
                    "转化率": round(safe_float(entry['点击转化率'].strip('%')) / 100, 4) if isinstance(entry['点击转化率'], str) and entry['点击转化率'].endswith('%') and entry['点击转化率'].strip('%') != '' else round(safe_float(entry['点击转化率']), 4),
                    "客单价": safe_float(entry['客单价'])
                }
                
                # 添加所有其他字段
                for key, value in entry.items():
                    # 跳过已处理的核心字段和datetime
                    if key in ['整体GMV', '消耗', '转化率', '客单价', '主播优化建议', 'datetime']:
                        continue
                    
                    # 处理数值型字段
                    if isinstance(value, (int, float)):
                        mapped_entry[key] = value
                    elif isinstance(value, str):
                        # 处理空字符串
                        if value == '':
                            mapped_entry[key] = 0
                        # 处理百分比
                        elif value.endswith('%'):
                            try:
                                percent_value = value.strip('%')
                                if percent_value == '':
                                    mapped_entry[key] = 0
                                else:
                                    mapped_entry[key] = round(float(percent_value) / 100, 4)
                            except ValueError:
                                mapped_entry[key] = value  # 保留原始值以防转换失败
                        # 处理数值字符串
                        else:
                            try:
                                if '.' in value:
                                    mapped_entry[key] = float(value)
                                else:
                                    mapped_entry[key] = int(value)
                            except ValueError:
                                mapped_entry[key] = value  # 保留原始字符串
                    else:
                        mapped_entry[key] = value  # 其他类型直接保留
                
                valid_entries.append( (mapped_entry, None) )
                # 记录时间段原始值用于调试
                time_period = entry.get('小时', '未知')
                logger.debug(f"成功处理飞书数据条目，记录时间: {entry.get('日期', '未知')} {time_period} (原始小时值: '{time_period}')")
                
                # 追加到CSV (根据配置决定是否启用)
                data_append_enabled = CONFIG.get('data_storage', {}).get('data_append_enabled', False)
                if data_append_enabled:
                    append_to_csv(mapped_entry, data_append_enabled)
                else:
                    logger.debug(f"CSV写入已禁用，跳过数据追加: {entry.get('日期', '未知')} {entry.get('小时', '未知')}")
            
            except (ValueError, TypeError) as e:
                logger.error(f"数据类型转换失败: {str(e)}, 数据值: {entry}")
                continue
        
        # 检查有效条目数量
        if len(valid_entries) < 2:
            logger.warning(f"可用飞书数据条目不足，需要至少2条进行对比分析，当前有{len(valid_entries)}条")
        
        # 返回最新的两条数据（如果有）
        if len(valid_entries) >= 2:
            return (valid_entries[-2], valid_entries[-1])  # (上一小时, 当前小时)
        elif len(valid_entries) == 1:
            return (valid_entries[0], None)  # 只有一条数据
        else:
            return (None, None)  # 无有效数据
    
    except Exception as e:
        logger.error(f"加载飞书数据时发生意外错误: {str(e)}", exc_info=True)
        return None, None

# 字段映射：JSON键 -> CSV列名
FIELD_MAPPING = {
    "直播间曝光人数_1": "直播间曝光人数",
    "成交人数_1": "成交人数",
    # 可根据实际需要添加更多字段映射
}

def append_to_csv(data_entry, data_append_enabled, csv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'data', 'baseline_data', '欧莱雅数据登记 - 自动化数据 (4).csv')):
    """将处理后的数据追加到CSV文件"""
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        # 检查CSV文件是否存在
        file_exists = os.path.exists(csv_path)
        
        # 映射字段名
        mapped_data = {}
        for json_key, value in data_entry.items():
            # 应用字段映射
            csv_key = FIELD_MAPPING.get(json_key, json_key)
            mapped_data[csv_key] = value
        
        # 读取CSV表头以确定字段顺序
        fieldnames = []
        duplicate_found = False
        if file_exists:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                
                # 仅在启用数据追加时检查重复记录
                if data_append_enabled:
                    # 检查是否已存在相同记录（基于日期和小时）
                    for row in reader:
                        if (row.get('日期') == mapped_data.get('日期') and 
                            row.get('小时') == mapped_data.get('小时')):
                            logger.debug(f"记录已存在，跳过写入: {mapped_data['日期']} {mapped_data['小时']}")
                            duplicate_found = True
                            break
            
            # 如果发现重复记录，直接返回
            if duplicate_found:
                return True
        # 如果文件不存在，初始化字段名
        if not file_exists:
            # 使用数据中的键作为初始字段名
            fieldnames = list(mapped_data.keys())
            logger.info(f"创建新CSV文件: {csv_path}")
        
        # 确保所有字段都在表头中，并保持正确的字段顺序
        # 定义期望的字段顺序，日期字段应该在最前面
        expected_order = ['日期', '小时', '主播', '场控', '场次']
        
        # 将新字段按照期望顺序插入，避免重复
        for key in mapped_data:
            if key not in fieldnames:
                logger.warning(f"CSV表头缺少字段: {key}，已添加")
                if key in expected_order:
                    # 按照期望顺序插入
                    insert_index = expected_order.index(key)
                    # 找到合适的插入位置
                    actual_insert_index = 0
                    for i, expected_field in enumerate(expected_order[:insert_index]):
                        if expected_field in fieldnames:
                            actual_insert_index = fieldnames.index(expected_field) + 1
                    fieldnames.insert(actual_insert_index, key)
                else:
                    # 其他字段添加到末尾，但要避免重复
                    fieldnames.append(key)
        
        # 写入数据 - 确保正确的换行处理
        with open(csv_path, 'a', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            # 如果是新文件，写入表头
            if not file_exists:
                writer.writeheader()
            
            writer.writerow(mapped_data)
            logger.info(f"成功追加数据到CSV: {mapped_data['日期']} {mapped_data['小时']}")
            return True
    except Exception as e:
        logger.error(f"追加数据到CSV失败: {str(e)}", exc_info=True)
        return False