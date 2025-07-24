#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import logging
import pandas as pd
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import seaborn as sns
from collections import defaultdict

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('effectiveness_analyzer')

# 定义常量
RESULTS_FILE = 'data/results/analysis_results.json'
FEEDBACK_LOG_FILE = 'data/results/feedback_log.json'
STRATEGY_LIBRARY_FILE = 'src/ai_analysis/strategy_library.json'
OUTPUT_REPORT_FILE = 'strategy_reports/strategy_effectiveness_report.md'

# 确保目录存在
os.makedirs(os.path.dirname(FEEDBACK_LOG_FILE), exist_ok=True)
os.makedirs('strategy_reports', exist_ok=True)  # 直接确保strategy_reports文件夹存在

def load_json_file(file_path, default_type='list'):
    """通用JSON加载器"""
    if not os.path.exists(file_path):
        return [] if default_type == 'list' else {}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return [] if default_type == 'list' else {}

def save_json_file(file_path, data):
    """通用JSON保存器"""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, ensure_ascii=False, fp=f, indent=2)

def get_strategy_details(strategy_id):
    """获取战术详情"""
    strategy_library = load_json_file(STRATEGY_LIBRARY_FILE, 'dict')
    
    # 确保strategy_library是字典类型
    if not isinstance(strategy_library, dict):
        return None
        
    # 从字典中获取strategies列表
    strategies = strategy_library.get('strategies', [])
    
    for strategy in strategies:
        # 确保strategy是字典类型
        if isinstance(strategy, dict) and strategy.get('id') == strategy_id:
            return strategy
    
    return None

def get_metrics_before_after(timestamp, metric_names, hours_before=1, hours_after=1):
    """获取指定时间点前后的指标数据"""
    # 加载分析结果
    analysis_results = load_json_file(RESULTS_FILE)
    if not isinstance(analysis_results, list):
        analysis_results = []
    
    # 解析时间戳
    try:
        target_time = datetime.fromisoformat(timestamp)
    except ValueError:
        try:
            # 尝试另一种格式
            target_time = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            logger.error(f"无法解析时间戳: {timestamp}")
            return {}
    
    # 定义时间范围
    time_before = target_time - timedelta(hours=hours_before)
    time_after = target_time + timedelta(hours=hours_after)
    
    # 查找前后的数据点
    data_before = None
    data_after = None
    
    for result in analysis_results:
        if not isinstance(result, dict):
            continue
            
        # 检查是否有必要的字段
        if 'timestamp' not in result:
            continue
            
        try:
            # 解析时间戳
            result_time = None
            try:
                result_time = datetime.fromisoformat(result['timestamp'])
            except ValueError:
                try:
                    result_time = datetime.strptime(result['timestamp'], '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    continue
            
            if not result_time:
                continue
                
            # 查找之前的数据点
            if time_before <= result_time < target_time:
                if data_before is None or (isinstance(data_before, dict) and 'timestamp' in data_before and result_time > datetime.fromisoformat(data_before['timestamp'])):
                    data_before = result
                
            # 查找之后的数据点
            if target_time < result_time <= time_after:
                if data_after is None or (isinstance(data_after, dict) and 'timestamp' in data_after and result_time < datetime.fromisoformat(data_after['timestamp'])):
                    data_after = result
        except Exception as e:
            logger.error(f"处理数据点时出错: {e}")
            continue
    
    # 从分析结果中提取指标数据
    metrics_data = {}
    
    for metric_name in metric_names:
        metrics_data[metric_name] = {
            'before': extract_metric_value(data_before, metric_name) if data_before else None,
            'after': extract_metric_value(data_after, metric_name) if data_after else None
        }
    
    return metrics_data

def extract_metric_value(data_point, metric_name):
    """从分析结果中提取指标值"""
    if not data_point or not isinstance(data_point, dict):
        return None
    
    # 尝试从analysis_result字段获取分析文本
    analysis_text = ""
    if 'analysis_result' in data_point and data_point['analysis_result']:
        analysis_text = data_point['analysis_result']
    # 如果没有analysis_result字段，尝试从diagnoses字段获取
    elif 'diagnoses' in data_point and isinstance(data_point['diagnoses'], list):
        analysis_text = "\n".join(data_point['diagnoses'])
    # 如果还没有，尝试直接使用整个data_point的字符串表示
    else:
        try:
            analysis_text = str(data_point)
        except:
            return None
    
    # 更新正则表达式以处理货币符号、逗号和百分比
    import re
    pattern = rf"\|\s*{re.escape(metric_name)}\s*\|\s*([^|]+?)\s*\|"
    match = re.search(pattern, analysis_text)
    
    if match:
        value_str = match.group(1).strip()
        # 清理字符串中的非数字字符（保留小数点和负号）
        cleaned_str = re.sub(r'[^\d.-]', '', value_str)
        try:
            # 如果原始字符串包含百分比，则转换为小数
            if '%' in value_str:
                return float(cleaned_str) / 100.0
            else:
                return float(cleaned_str)
        except (ValueError, TypeError):
            logger.warning(f"无法将提取的值 '{value_str}' 转换为浮点数。")
            return None
    
    return None

def calculate_effectiveness(metrics_data):
    """计算战术效果"""
    effectiveness = {}
    
    for metric_name, values in metrics_data.items():
        # 确保values是字典类型
        if not isinstance(values, dict):
            continue
            
        before_value = values.get('before')
        after_value = values.get('after')
        
        if before_value is not None and after_value is not None and before_value != 0:
            change_pct = (after_value - before_value) / before_value * 100
            effectiveness[metric_name] = {
                'before': before_value,
                'after': after_value,
                'change_pct': change_pct,
                'improved': change_pct > 0
            }
    
    return effectiveness

def analyze_strategy_effectiveness():
    """分析战术效果并生成报告"""
    # 加载用户反馈日志
    feedback_log = load_json_file(FEEDBACK_LOG_FILE)
    if not isinstance(feedback_log, list):
        feedback_log = []
    
    if not feedback_log:
        # 如果没有反馈日志，创建一个示例日志用于演示
        feedback_log = generate_demo_feedback()
        save_json_file(FEEDBACK_LOG_FILE, feedback_log)
    
    # 按战术ID分组
    strategies_feedback = defaultdict(list)
    for entry in feedback_log:
        if not isinstance(entry, dict):
            continue
            
        # 直接从字典中获取strategy_id
        strategy_id = None
        if 'strategy_id' in entry:
            strategy_id = entry['strategy_id']
            
        if strategy_id:
            strategies_feedback[strategy_id].append(entry)
    
    # 分析每个战术的效果
    strategies_effectiveness = {}
    
    for strategy_id, feedbacks in strategies_feedback.items():
        strategy_details = get_strategy_details(strategy_id)
        if not strategy_details:
            continue
        
        # 根据战术目标确定关键指标
        target_metrics = determine_target_metrics(strategy_details)
        
        # 分析每次采纳的效果
        adoptions_effectiveness = []
        
        for feedback in feedbacks:
            if not isinstance(feedback, dict):
                continue
                
            # 直接从字典中获取timestamp
            timestamp = None
            if 'report_timestamp' in feedback:
                timestamp = feedback['report_timestamp']
                
            if not timestamp:
                continue
                
            metrics_data = get_metrics_before_after(timestamp, target_metrics)
            effectiveness = calculate_effectiveness(metrics_data)
            
            if effectiveness:
                adoptions_effectiveness.append({
                    'timestamp': timestamp,
                    'effectiveness': effectiveness
                })
        
        # 汇总战术效果
        if adoptions_effectiveness:
            strategies_effectiveness[strategy_id] = {
                'details': strategy_details,
                'adoptions': adoptions_effectiveness,
                'summary': summarize_effectiveness(adoptions_effectiveness)
            }
    
    # 生成报告
    generate_report(strategies_effectiveness)
    
    return strategies_effectiveness

def determine_target_metrics(strategy_details):
    """根据战术目标确定关键指标"""
    # 确保strategy_details是字典类型
    if not isinstance(strategy_details, dict):
        return ['销售额', '转化率', '客单价', '互动率']  # 返回默认指标
    
    goal = strategy_details.get('goal', '').lower()
    
    if '转化' in goal or '紧迫感' in goal:
        return ['转化率', '销售额', '成交人数', '商品点击-转化率']
    elif '客单价' in goal:
        return ['客单价', '销售额', '大瓶GMV', '三瓶GMV']
    elif '互动' in goal:
        return ['互动率', '直播间评论数', '内容互动人数']
    else:
        # 默认指标
        return ['销售额', '转化率', '客单价', '互动率']

def summarize_effectiveness(adoptions_effectiveness):
    """汇总多次采纳的效果"""
    all_metrics = set()
    for adoption in adoptions_effectiveness:
        for metric in adoption['effectiveness'].keys():
            all_metrics.add(metric)
    
    summary = {}
    for metric in all_metrics:
        values = []
        for adoption in adoptions_effectiveness:
            if metric in adoption['effectiveness']:
                values.append(adoption['effectiveness'][metric]['change_pct'])
        
        if values:
            avg_change = sum(values) / len(values)
            success_rate = sum(1 for v in values if v > 0) / len(values) * 100
            
            summary[metric] = {
                'avg_change_pct': avg_change,
                'success_rate': success_rate,
                'sample_size': len(values)
            }
    
    return summary

def generate_report(strategies_effectiveness):
    """生成战术效果分析报告"""
    now = datetime.now()
    
    report = f"""# 🏆 AI战术效果分析报告

**生成时间**: {now.strftime('%Y-%m-%d %H:%M:%S')}

## 📊 战术效果总览

"""
    
    # 如果没有数据，添加提示信息
    if not strategies_effectiveness:
        report += """
> **暂无战术效果数据**
>
> 目前还没有足够的数据来分析战术效果。请在直播过程中采纳AI推荐的战术指令，并点击"我已采纳"按钮，系统将记录您的反馈并在后续分析中评估战术效果。
"""
    else:
        # 添加战术效果总览表格
        report += """
| 战术ID | 战术名称 | 目标 | 平均效果 | 成功率 | 采纳次数 |
|--------|----------|------|----------|--------|----------|
"""
        
        for strategy_id, data in strategies_effectiveness.items():
            details = data['details']
            summary = data['summary']
            adoptions = data['adoptions']
            
            # 计算平均效果（取第一个关键指标）
            key_metric = None
            if summary and len(summary) > 0:
                key_metric = list(summary.keys())[0]
                
            avg_effect = "N/A"
            success_rate = "N/A"
            if key_metric and isinstance(summary, dict) and key_metric in summary:
                avg_effect = f"{summary[key_metric]['avg_change_pct']:.2f}%"
                success_rate = f"{summary[key_metric]['success_rate']:.0f}%"
            
            report += f"| {strategy_id} | {details['name']} | {details['goal']} | {avg_effect} | {success_rate} | {len(adoptions)} |\n"
        
        # 添加每个战术的详细分析
        report += "\n\n## 🔍 战术详细分析\n\n"
        
        for strategy_id, data in strategies_effectiveness.items():
            details = data['details']
            summary = data['summary']
            adoptions = data['adoptions']
            
            report += f"""### {details['name']} (ID: {strategy_id})

**目标**: {details['goal']}

**指令详情**: {details['instruction']}

**采纳次数**: {len(adoptions)}

#### 效果数据:

"""
            
            # 添加关键指标效果表格
            report += """
| 指标名称 | 平均变化 | 成功率 | 样本数 |
|----------|----------|--------|--------|
"""
            
            for metric, data in summary.items():
                avg_change = f"{data['avg_change_pct']:.2f}%"
                success_rate = f"{data['success_rate']:.0f}%"
                sample_size = data['sample_size']
                
                report += f"| {metric} | {avg_change} | {success_rate} | {sample_size} |\n"
            
            report += "\n\n"
    
    # 保存报告
    with open(OUTPUT_REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write(report)
    
    logger.info(f"战术效果分析报告已生成: {OUTPUT_REPORT_FILE}")
    
    return report

def generate_demo_feedback():
    """生成演示用的反馈数据"""
    # 获取分析结果中的时间戳
    analysis_results = load_json_file(RESULTS_FILE)
    timestamps = []
    
    for result in analysis_results:
        if 'timestamp' in result:
            timestamps.append(result['timestamp'])
    
    # 如果没有时间戳，使用当前时间
    if not timestamps:
        timestamps = [datetime.now().isoformat()]
    
    # 生成示例反馈
    demo_feedback = [
        {
            "feedback_time": datetime.now().isoformat(),
            "report_timestamp": timestamps[0],
            "strategy_id": "A-3",
            "strategy_name": "限时限量",
            "action": "adopted"
        },
        {
            "feedback_time": datetime.now().isoformat(),
            "report_timestamp": timestamps[0] if len(timestamps) == 1 else timestamps[1],
            "strategy_id": "B-1",
            "strategy_name": "算账对比法",
            "action": "adopted"
        }
    ]
    
    if len(timestamps) > 2:
        demo_feedback.append({
            "feedback_time": datetime.now().isoformat(),
            "report_timestamp": timestamps[2],
            "strategy_id": "C-2",
            "strategy_name": "评论区扣1",
            "action": "adopted"
        })
    
    return demo_feedback

if __name__ == '__main__':
    try:
        logger.info("开始分析战术效果...")
        analyze_strategy_effectiveness()
        logger.info("战术效果分析完成")
    except Exception as e:
        logger.error(f"战术效果分析失败: {e}", exc_info=True) 