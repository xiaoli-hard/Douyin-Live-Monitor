# -*- coding: utf-8 -*-
import os
import re
import json
import sys
import streamlit as st
import logging

# 配置调试日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
import subprocess
from datetime import datetime, date
import pandas as pd
import plotly.express as px  # 添加Plotly支持
from typing import Dict, Any, Optional

# --- 新增: 导入智能动态基线系统 ---
from src.baseline.dynamic_baseline_engine import RealDataDynamicBaseline

# --- 新增: 路径管理 ---
# 获取脚本所在的目录，确保所有路径都是相对于此目录的
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 设置页面配置
st.set_page_config(
    page_title='直播话术分析仪表盘',
    page_icon='📊',
    layout='wide',
    initial_sidebar_state='expanded')

# 定义常量 (已修改为绝对路径)
RESULTS_FILE = os.path.join(SCRIPT_DIR, 'data', 'results', 'analysis_results.json')
REPORTS_DIR = os.path.join(SCRIPT_DIR, 'analysis_reports')
FEEDBACK_LOG_FILE = os.path.join(SCRIPT_DIR, 'data', 'results', 'feedback_log.json')
STRATEGY_LIBRARY_FILE = os.path.join(SCRIPT_DIR, 'src', 'ai_analysis', 'strategy_library.json')

# --- 辅助函数 ---

def load_json_file(file_path, default_type='list'):
    """通用JSON加载器"""
    if not os.path.exists(file_path):
        return [] if default_type == 'list' else {}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return [] if default_type == 'list' else {}

def update_feedback(report_timestamp: str, strategy: Dict[str, Any], action: str):
    """记录或取消用户采纳的指令"""
    log_data = load_json_file(FEEDBACK_LOG_FILE, 'list')
    if not isinstance(log_data, list):
        log_data = []

    strategy_id = strategy.get('id')

    if action == "adopt":
        # 确保不会重复添加
        if not any(e.get('report_timestamp') == report_timestamp and e.get('strategy_id') == strategy_id for e in log_data):
            feedback_entry = {
                "feedback_time": datetime.now().isoformat(),
                "report_timestamp": report_timestamp,
                "strategy_id": strategy_id,
                "strategy_name": strategy.get('name'),
                "action": "adopted"
            }
            log_data.append(feedback_entry)
            st.toast(f"✅ 已记录采纳: **{strategy.get('name')}**", icon="👍")
        
    elif action == "cancel":
        # 查找并移除已采纳的记录
        initial_len = len(log_data)
        log_data = [
            e for e in log_data 
            if not (e.get('report_timestamp') == report_timestamp and e.get('strategy_id') == strategy_id)
        ]
        if len(log_data) < initial_len:
            st.toast(f"🗑️ 已取消采纳: **{strategy.get('name')}**", icon="↩️")

    with open(FEEDBACK_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)

def get_reports_by_date(target_date):
    """获取特定日期的所有MD报告文件"""
    if not os.path.exists(REPORTS_DIR):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        return []
    date_str_pattern = target_date.strftime('%Y-%m-%d')
    report_files = [f for f in os.listdir(REPORTS_DIR) if f.endswith('.md') and date_str_pattern in f]
    report_files.sort(reverse=True)
    return [os.path.join(REPORTS_DIR, f) for f in report_files]

def load_report(report_path):
    """加载指定的Markdown报告"""
    if not report_path or not os.path.exists(report_path): return None
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        st.error(f'加载报告失败: {str(e)}')
        return None

# --- 新增: 基线系统初始化函数 ---
@st.cache_resource
def get_baseline_system():
    """使用Streamlit缓存来初始化并返回基线系统实例。UI元素已被移除以修复缓存错误。"""
    try:
        storage_path = os.path.join(SCRIPT_DIR, 'data', 'baseline_storage')
        history_path = os.path.join(SCRIPT_DIR, 'data', 'baseline_data', 'historical_data.csv')
        
        if not os.path.exists(history_path):
            print(f"❌ 错误：找不到历史数据文件于 '{history_path}'。基线系统无法启动。")
            return None

        print("🚀 正在初始化智能动态基线系统...")
        
        baseline_system = RealDataDynamicBaseline(data_dir=storage_path)
        initialized = baseline_system.initialize_system(history_path)
        
        if initialized:
            print("✅ 智能动态基线系统初始化成功。")
            return baseline_system
        else:
            print("❌ 基线系统初始化失败。")
            return None
            
    except Exception as e:
        print(f"❌ 基线系统初始化时发生异常: {e}")
        return None

# --- 简化：直接使用新指标名称 ---
def get_metric_data(metrics_data, metric_name):
    """直接获取指标数据，如果不存在返回None"""
    return metrics_data.get(metric_name)

def extract_baseline_comparison_from_report(report_content):
    """从报告的Markdown中提取动态基线对比分析表格数据。"""
    if not report_content:
        return {}
    
    baseline_data = {}
    
    # 匹配"## 📊 动态基线对比分析"后面的表格
    baseline_pattern = r'## 📊 动态基线对比分析\s*\n.*?\n### 指标评估结果\s*\n\|\s*指标名称.*?\n\|[-\s|]*\n((?:\|.*?\n)+)'
    baseline_match = re.search(baseline_pattern, report_content, re.DOTALL)
    
    if baseline_match:
        table_content = baseline_match.group(1)
        lines = table_content.strip().split('\n')
        
        for line in lines:
            if line.strip().startswith('|') and line.strip().endswith('|'):
                # 分割表格行，去除首尾的 |
                cells = [cell.strip() for cell in line.strip()[1:-1].split('|')]
                
                if len(cells) >= 5:  # 确保有足够的列：指标名称|评估结果|系数|基线值|评估方法
                    metric_name = cells[0].strip()
                    evaluation = cells[1].strip()
                    coefficient = cells[2].strip()
                    baseline_value = cells[3].strip()
                    eval_method = cells[4].strip()
                    
                    # 跳过表头行
                    if metric_name not in ['指标名称', '---', '']:
                        baseline_data[metric_name] = {
                            '评估': evaluation,
                            '系数': coefficient,
                            '基线值': baseline_value,
                            '评估方法': eval_method
                        }
    
    return baseline_data

def extract_metrics_from_report(report_content):
    """从报告内容中提取指标数据"""
    import re
    if not report_content:
        return {}
    
    metrics_data = {}
    
    # 直接匹配表格，不依赖特定的标题
    table_pattern = r'\|\s*指标名称.*?\n\|[-\s|]*\n((?:\|.*?\n)+)'
    table_match = re.search(table_pattern, report_content, re.DOTALL)
    
    if table_match:
        # 提取表头行
        header_match = re.search(r'\|\s*指标名称.*?\n', report_content)
        if header_match:
            header_line = header_match.group(0).strip()
            headers = [h.strip() for h in header_line.split('|') if h.strip()]
            logging.info(f"成功提取表头: {headers}")
        else:
            logging.info("Header match failed. Report content around expected header:\n%s", report_content[:500])
            logging.info("Header pattern used: \\|\\s*指标名称.*?\\n")
            return {} # 如果表头匹配失败，则返回空字典
        
        # 提取数据行
        data_section = table_match.group(1)
        data_lines = data_section.strip().split('\n')
        
        # 解析每一行数据
        for line in data_lines:
            if '|' not in line:  # 跳过非表格行
                continue
                
            cells = [cell.strip() for cell in line.split('|') if cell.strip()]
            if len(cells) >= len(headers):  # 确保有足够的单元格
                row_data = {}
                for i, header in enumerate(headers):
                    if i < len(cells):
                        # 清理并标准化数据
                        value = cells[i]
                        # 去除可能的千位分隔符和异常字符
                        value = value.replace(',', '').replace('weep', '').strip()
                        
                        # 处理状态列的特殊格式（如'🟢正常'）
                        if '状态' in header and ('🟢' in value or '🔴' in value):
                            # 提取emoji部分
                            if '🟢' in value:
                                value = '🟢'
                            elif '🔴' in value:
                                value = '🔴'
                        
                        # 对于数值列，进行更深度的清理
                        if header in ['当前值', '上小时值'] and value:
                            # 使用正则表达式清理数值
                            import re
                            # 移除所有非数字、小数点、负号、百分号的字符
                            cleaned_value = re.sub(r'[^0-9.\-\%]', '', value)
                            if cleaned_value:
                                value = cleaned_value
                        
                        row_data[header] = value
                    
                # 使用"指标名称"作为键
                metric_name = row_data.get('指标名称')
                if metric_name:
                    # 预处理数据，确保正确识别数值类型
                    if '当前值' in row_data:
                        # 保留原始格式，让display_metric函数处理格式化
                        pass
                        
                    # 预处理变化百分比
                    if '变化百分比' in row_data:
                        change_val = row_data['变化百分比']
                        # 确保变化百分比包含正负号
                        if change_val and not (change_val.startswith('+') or change_val.startswith('-')) and change_val != '0%':
                            if not change_val.startswith('0'):  # 避免将"0%"变为"+0%"
                                row_data['变化百分比'] = f"+{change_val}"
                                
                    metrics_data[metric_name] = row_data
    
    # 如果上面的方法失败，尝试更宽松的匹配
    if not metrics_data:
        # 尝试找到任何表格结构
        all_tables = re.findall(r'(\|.*?\|.*?\n\|[-\s|]*\n(?:\|.*?\n)+)', report_content, re.DOTALL)
        for table in all_tables:
            lines = table.strip().split('\n')
            if len(lines) >= 2:  # 至少有表头和一行数据
                # 提取表头
                headers = [h.strip() for h in lines[0].split('|') if h.strip()]
                
                # 检查是否包含"指标名称"列
                if '指标名称' in headers or '指标' in headers:
                    name_index = headers.index('指标名称' if '指标名称' in headers else '指标')
                    
                    # 从第三行开始解析数据（跳过表头和分隔行）
                    for line in lines[2:]:
                        cells = [cell.strip() for cell in line.split('|') if cell.strip()]
                        if len(cells) >= len(headers):
                            row_data = {}
                            for i, header in enumerate(headers):
                                if i < len(cells):
                                    # 清理并标准化数据
                                    value = cells[i]
                                    # 去除可能的千位分隔符和异常字符
                                    value = value.replace(',', '').replace('weep', '').strip()
                                    # 处理状态列的特殊格式（如'🟢正常'）
                                    if '状态' in header and ('🟢' in value or '🔴' in value):
                                        # 提取emoji部分
                                        if '🟢' in value:
                                            value = '🟢'
                                        elif '🔴' in value:
                                            value = '🔴'
                                    row_data[header] = value
                            
                            metric_name = cells[name_index]
                            if metric_name:
                                # 同样进行预处理
                                if '当前值' in row_data:
                                    pass
                                    
                                if '变化百分比' in row_data:
                                    change_val = row_data['变化百分比']
                                    if change_val and not (change_val.startswith('+') or change_val.startswith('-')) and change_val != '0%':
                                        if not change_val.startswith('0'):
                                            row_data['变化百分比'] = f"+{change_val}"
                                
                                metrics_data[metric_name] = row_data
    
    # 打印调试信息
    if not metrics_data:
        logging.info("无法从报告中提取指标数据")
        logging.info("报告内容前500个字符:\n%s", report_content[:500] if report_content else "空")
        logging.info("Table pattern used: %s", table_pattern)
    else:
        logging.info("成功提取了 %d 个指标", len(metrics_data))
    
    return metrics_data

def extract_product_mentions(report_content):
    """从报告中提取产品提及分析表格"""
    if not report_content:
        return None
    
    # 匹配产品提及分析部分（包括标题和整个表格）
    product_section_match = re.search(r'## 🔍 产品提及分析\s*\n(\|.*?\n\|[-\s|]*\n(?:\|.*?\n)+)', report_content, re.DOTALL)
    if not product_section_match:
        return None
    
    # 提取表格内容（不包括标题）
    table_content = product_section_match.group(1)
    
    # 定义PWU相关产品关键词
    pwu_related_keywords = [
        'PWU', '洗衣留香珠', '留香珠', '洗衣珠', '衣物护理', 
        '持久留香', '除菌除螨', '居家好物', '衣物香水'
    ]
    
    # 过滤表格内容，只保留PWU相关产品
    lines = table_content.split('\n')
    header_lines = lines[:2]  # 保留表头和分隔行
    data_lines = []
    
    for line in lines[2:]:  # 从第3行开始是数据行
        if '|' in line:
            # 检查是否包含PWU相关关键词
            is_pwu_related = False
            for keyword in pwu_related_keywords:
                if keyword in line:
                    is_pwu_related = True
                    break
            
            # 如果是PWU相关产品，添加到结果中
            if is_pwu_related:
                data_lines.append(line)
    
    # 如果没有找到PWU相关产品，返回一个提示信息
    if not data_lines:
        return "未找到与PWU相关的产品提及分析。"
    
    # 组合表格
    filtered_table = '\n'.join(header_lines + data_lines)
    
    # 返回完整的表格，包括标题
    return f"## 🔍 产品提及分析\n{filtered_table}"

def filter_report_for_display(report_content):
    """从报告内容中移除指定的部分，以便在UI中更简洁地显示。"""
    if not report_content:
        return ""
    
    # 移除"产品提及分析"部分
    # 使用 re.DOTALL 使 '.' 匹配包括换行符在内的任何字符
    # 非贪婪匹配 .*? 来确保只匹配到下一个二级标题或文件结尾
    filtered_content = re.sub(r'## 🔍 产品提及分析.*?(?=\n## |\Z)', '', report_content, flags=re.DOTALL)
    
    # 移除"动态基线对比分析"部分
    filtered_content = re.sub(r'## 📊 动态基线对比分析.*?(?=\n## |\Z)', '', filtered_content, flags=re.DOTALL)
    
    # 移除"AI战术指令"部分
    filtered_content = re.sub(r'## 🤖 AI战术指令.*?(?=\n## |\Z)', '', filtered_content, flags=re.DOTALL)
    
    # 移除"指标变化分析"部分
    filtered_content = re.sub(r'## 📊 指标变化分析.*?(?=\n## |\Z)', '', filtered_content, flags=re.DOTALL)
    
    # 移除多余的空行
    filtered_content = re.sub(r'\n{3,}', '\n\n', filtered_content)
    
    return filtered_content.strip()

def format_warning_section(section_md):
    """
    通过直接修改Markdown文本，为“异常指标预警”部分强制添加图标和缩进。
    这是一个比纯CSS更可靠的方法，因为它不依赖于AI输出的精确结构。
    """
    # 为子项添加图标和缩进
    section_md = re.sub(r'(\s*-\s*)(\*\*原因分析\*\*)', r'\1&nbsp;&nbsp;&nbsp;&nbsp;💡 \2', section_md)
    section_md = re.sub(r'(\s*-\s*)(\*\*数据证据\*\*)', r'\1&nbsp;&nbsp;&nbsp;&nbsp;📊 \2', section_md)
    section_md = re.sub(r'(\s*-\s*)(\*\*话术证据\*\*)', r'\1&nbsp;&nbsp;&nbsp;&nbsp;🗣️ \2', section_md)
    return section_md

@st.cache_data
def load_historical_data():
    """扫描所有报告，提取数据并返回一个缓存的DataFrame。"""
    if not os.path.exists(REPORTS_DIR) or not os.listdir(REPORTS_DIR):
        return pd.DataFrame()  # 返回空的DataFrame
        
    report_files = [os.path.join(REPORTS_DIR, f) for f in os.listdir(REPORTS_DIR) if f.endswith('.md')]
    
    all_metrics_data = []
    for report_path in report_files:
        filename = os.path.basename(report_path)
        match = re.search(r'(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}(?:-\d{2})?)', filename)
        if not match: continue
        
        report_ts_raw = match.group(1)
        try:
            if report_ts_raw.count('-') == 4:
                report_dt = datetime.strptime(report_ts_raw, '%Y-%m-%d_%H-%M-%S')
            else:
                report_dt = datetime.strptime(report_ts_raw, '%Y-%m-%d_%H-%M')
        except ValueError:
            continue
            
        report_content = load_report(report_path)
        metrics = extract_metrics_from_report(report_content)
        if not metrics: continue
            
        processed_metrics: Dict[str, Any] = {'时间': report_dt, '报告名称': filename}
        for name, data in metrics.items():
            val_str = data.get('当前值', '0').replace(',', '').replace('¥', '')
            try:
                if '%' in val_str:
                    processed_metrics[name] = float(val_str.replace('%', '')) / 100
                else:
                    processed_metrics[name] = float(val_str)
            except (ValueError, TypeError):
                continue
        all_metrics_data.append(processed_metrics)

    if not all_metrics_data:
        return pd.DataFrame()

    df = pd.DataFrame(all_metrics_data)
    df = df.sort_values(by='时间')
    return df

def create_historical_trend_chart(baseline_system):
    """(已修复Linter错误并增加基线显示) 美化和优化后的历史趋势图表生成函数。"""
    
    # --- 1. 数据加载 (使用缓存) ---
    df = load_historical_data()

    if df.empty or len(df) < 2:
        st.info("至少需要两份包含有效数据的报告才能生成趋势图。")
        return

    # --- 2. 筛选器UI布局与逻辑 ---
    st.markdown('<div class="trend-filter-container">', unsafe_allow_html=True)
    st.subheader("⚙️ 图表筛选与自定义")
    
    filter_col, display_col = st.columns([1, 1])
    
    start_dt: Optional[datetime] = None
    end_dt: Optional[datetime] = None

    with filter_col:
        st.markdown("##### 范围选择")
        min_date_df, max_date_df = df['时间'].min(), df['时间'].max()
        min_date = min_date_df.date() if isinstance(min_date_df, datetime) else date.today()
        max_date = max_date_df.date() if isinstance(max_date_df, datetime) else date.today()

        date_col1, date_col2 = st.columns(2)
        start_date_val = date_col1.date_input("开始日期", min_date, min_value=min_date, max_value=max_date)
        
        end_date_min = start_date_val if isinstance(start_date_val, date) else min_date
        end_date_val = date_col2.date_input("结束日期", max_date, min_value=end_date_min, max_value=max_date)

        if isinstance(start_date_val, date) and isinstance(end_date_val, date):
            start_dt = datetime.combine(start_date_val, datetime.min.time())
            end_dt = datetime.combine(end_date_val, datetime.max.time())
            
            reports_in_range_df = df[df['时间'].between(start_dt, end_dt)]
            report_options = reports_in_range_df['报告名称'].tolist()

            if len(report_options) > 1 and st.checkbox("启用精确报告筛选", help="可进一步选择开始和结束报告。"):
                rep_col1, rep_col2 = st.columns(2)
                start_report = rep_col1.selectbox("选择开始报告:", options=report_options)
                
                if start_report:
                    start_idx = report_options.index(start_report)
                    end_rep_opts = report_options[start_idx:]
                    end_report = rep_col2.selectbox("选择结束报告:", options=end_rep_opts, index=len(end_rep_opts) - 1)

                    if end_report:
                        start_series = df.loc[df['报告名称'] == start_report, '时间']
                        end_series = df.loc[df['报告名称'] == end_report, '时间']
                        
                        if len(start_series) == 1:
                            val = start_series.item()
                            if isinstance(val, datetime):
                                start_dt = val
                        if len(end_series) == 1:
                            val = end_series.item()
                            if isinstance(val, datetime):
                                end_dt = val

    if start_dt is None or end_dt is None:
        val_min, val_max = df['时间'].min(), df['时间'].max()
        if isinstance(val_min, datetime): start_dt = val_min
        if isinstance(val_max, datetime): end_dt = val_max

    if start_dt is None or end_dt is None:
        st.error("无法确定有效的日期范围。")
        return
        
    final_filtered_df = df[df['时间'].between(start_dt, end_dt)].copy()

    with display_col:
        st.markdown("##### 指标选择")
        all_metrics = [c for c in df.columns if c not in ['时间', '报告名称']]
        
        # 处理重复指标名称，清理标点符号并去重
        import re
        unique_metrics = []
        seen_clean_names = set()
        
        for name in sorted(all_metrics):
            # 清理指标名称：移除所有标点符号，只保留中文、英文和数字
            clean_name = re.sub(r'[^\u4e00-\u9fff\w]', '', name)
            
            # 如果清理后的名称已经存在，跳过重复的指标
            if clean_name in seen_clean_names:
                continue
                
            # 如果是新的清理后名称，添加到列表中
            if clean_name and clean_name not in seen_clean_names:
                seen_clean_names.add(clean_name)
                unique_metrics.append(name)
        
        # 使用固定的指标列表
        fixed_metrics = [
            '消耗', '整体GMV', '整体ROI', '智能优惠劵金额', '退款金额', '整体GSV', '实际ROI', 
            '大瓶装订单数', '三瓶装订单数', '成交人数', '成交件数', '客单价', '直播间曝光次数', 
            '直播间曝光人数', '直播间进入人数', '直播间观看次数', '在线峰值', '平均在线', 
            '引流成本', '转化成本', '整体uv价值', 'GPM', '人均观看时长', '观看人数', '曝光进入率', 
            '商品曝光人数', '商品曝光率', '商品点击人数', '商品点击率', '点击转化率', '画面消耗', 
            '画面gmv', '画面roi', '画面消耗占比', '画面CTR', '画面CVR', '画面曝光数', '画面点击数', 
            '画面转化数', '视频消耗', '视频gmv', '视频roi', '视频消耗占比', '视频CTR', '视频CVR', 
            '视频曝光数', '视频点击数', '视频转化数', '调控消耗', '调控GMV', '调控ROI', 
            '调控成交订单数', '调控消耗占比'
        ]
        
        # 筛选出在数据中实际存在的指标
        selectable_metrics = [metric for metric in fixed_metrics if metric in final_filtered_df.columns]
        
        # 设置默认选择
        default = [m for m in ['整体GMV', '观看人数'] if m in selectable_metrics]
        selected_metrics = st.multiselect("选择指标:", options=selectable_metrics, default=default)

        # --- 新增: 基线显示选项 ---
        st.markdown('<div class="baseline-option">', unsafe_allow_html=True)
        show_baseline = st.checkbox("📈 在图表上叠加显示基线", value=False, 
                                  help="如果启用，图表将为每个选定指标绘制其对应的历史平均基线。仅适用于基线系统已覆盖的指标。")
        st.markdown('</div>', unsafe_allow_html=True)

    # 关闭筛选器容器
    st.markdown('</div>', unsafe_allow_html=True)

    # --- 3. 图表渲染 ---
    st.markdown('<div class="trend-chart-container">', unsafe_allow_html=True)
    if final_filtered_df.empty:
        st.markdown('''
        <div class="trend-no-data">
            <div class="trend-no-data-icon">📊</div>
            <h4>暂无数据</h4>
            <p>在所选范围内没有数据可供显示，请调整筛选条件后重试。</p>
        </div>
        ''', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # 关闭图表容器
        return
        
    if not selected_metrics:
        st.markdown('''
        <div class="trend-select-metrics">
            <div class="trend-select-metrics-icon">📈</div>
            <h4>请选择指标</h4>
            <p>请在筛选器中选择至少一个指标以显示图表</p>
        </div>
        ''', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # 关闭图表容器
        return
    else:
        time_series = final_filtered_df['时间']
        if isinstance(time_series, pd.Series) and pd.api.types.is_datetime64_any_dtype(time_series.dtype):
             final_filtered_df.loc[:, '显示时间'] = time_series.dt.strftime('%Y-%m-%d %H:%M')
        else:
             final_filtered_df.loc[:, '显示时间'] = ''

        fig = px.line(final_filtered_df, x='时间', y=selected_metrics, title='关键指标历史趋势', markers=True,
                      hover_data={'时间': False, '显示时间': True, '报告名称': True})
        
        # --- 新增: 叠加基线逻辑 ---
        if show_baseline and baseline_system:
            for metric in selected_metrics:
                # 为每个数据点计算其对应的基线
                baseline_values = []
                for dt in final_filtered_df['时间']:
                    weekday = dt.weekday()
                    hour = dt.hour
                    key = f"{weekday}_{hour}"
                    # 从基线表中获取该指标的基线值
                    baseline_val = baseline_system.baseline_table.get(key, {}).get(metric)
                    baseline_values.append(baseline_val)
                
                # 添加基线轨迹
                fig.add_scatter(x=final_filtered_df['时间'], y=baseline_values, 
                                mode='lines', name=f'{metric} (基线)',
                                line=dict(dash='dash'))

        fig.update_layout(xaxis_title="日期", yaxis_title="数值", legend_title="指标", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
    
    # 关闭图表容器
    st.markdown('</div>', unsafe_allow_html=True)


def load_and_inject_css(css_file_path):
    """加载本地CSS文件并注入到Streamlit应用中"""
    # 使用 SCRIPT_DIR 构建绝对路径
    abs_css_path = os.path.join(SCRIPT_DIR, css_file_path)
    try:
        with open(abs_css_path, 'r', encoding='utf-8') as f:
            css = f.read()
        st.markdown(f'<style>{css}</style>', unsafe_allow_html=True)
    except FileNotFoundError:
        st.warning(f"自定义样式文件未找到: {abs_css_path}")

# --- 主函数 ---

def main():
    print("=== main()函数开始执行 ===")
    st.title('📊 直播话术分析仪表盘')

    # --- 加载并注入自定义CSS ---
    load_and_inject_css('assets/style.css')

    # --- 初始化基线系统 ---
    baseline_system = get_baseline_system()
    
    # --- 侧边栏 ---
    st.sidebar.title('导航栏')

    # --- 在主UI线程中处理UI反馈 ---
    if baseline_system is None:
        st.sidebar.warning("警告：智能诊断系统初始化失败，相关功能将不可用。请检查控制台日志获取详情。", icon="⚠️")
    
    # --- 新增：报告生成控制面板 ---
    st.sidebar.divider()
    st.sidebar.header('⚙️ 生成新报告')
    
    # 日期选择器
    start_date = st.sidebar.date_input('开始日期', datetime.now().date())
    end_date = st.sidebar.date_input('结束日期', datetime.now().date())
    
    # 特殊变量输入框
    special_variables = st.sidebar.text_input('特殊变量 (可选)', placeholder='例如：更换了主播, 618大促')
    
    # 生成报告按钮
    if st.sidebar.button('🚀 开始生成分析报告'):
        # 增加类型检查以修复linter错误并提高代码健壮性
        if not isinstance(start_date, date) or not isinstance(end_date, date):
            st.sidebar.error("错误：无效的日期输入。请确保选择了有效的开始和结束日期。")
        elif start_date > end_date:
            st.sidebar.error('错误：开始日期不能晚于结束日期。')
        else:
            # 格式化日期
            start_date_str = start_date.strftime('%Y-%m-%d')
            end_date_str = end_date.strftime('%Y-%m-%d')
            
            # 构建命令 (已修改为绝对路径)
            analyzer_script_path = os.path.join(SCRIPT_DIR, 'src', 'ai_analysis', 'ai_analyzer.py')
            cmd = [
                sys.executable, analyzer_script_path,
                '--start_date', start_date_str,
                '--end_date', end_date_str
            ]
            if special_variables:
                cmd.extend(['--variables', special_variables])

            # 使用spinner显示加载状态
            with st.spinner('正在调用AI分析引擎生成报告...这个过程可能需要1-3分钟，请耐心等待。'):
                try:
                    # 执行命令
                    process = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        check=True
                    )
                    st.sidebar.success('✅ 报告生成成功！')
                    st.sidebar.info('页面即将刷新以加载新数据...')
                    import time
                    time.sleep(2)
                    st.rerun()
                except subprocess.CalledProcessError as e:
                    st.sidebar.error('❌ 报告生成失败。')
                    error_details = (
                        f"后台脚本执行出错 (返回码: {e.returncode}):\n\n"
                        f"**错误日志 (STDERR):**\n"
                        f"```\n{e.stderr.strip()}\n```\n\n"
                        f"**脚本输出 (STDOUT):**\n"
                        f"```\n{e.stdout.strip()}\n```"
                    )
                    st.sidebar.text_area("错误详情:", error_details, height=300)
                except Exception as e:
                    st.sidebar.error('❌ 发生未知错误。')
                    st.sidebar.exception(e)

    st.sidebar.divider()
    # --- 结束：报告生成控制面板 ---

    # 选择日期以查看报告
    selected_date = st.sidebar.date_input("选择日期查看历史报告", date.today())
    
    # 获取并显示报告列表
    report_files = get_reports_by_date(selected_date)
    
    # 先完成报告选择流程
    selected_report_path = None
    if report_files:
        report_options = {os.path.basename(f): f for f in report_files}
        selected_report_name = st.sidebar.selectbox("选择一份报告查看详情:", list(report_options.keys()))
        selected_report_path = report_options[selected_report_name]
    else:
        st.sidebar.info(f"未找到 {selected_date} 的分析报告。")
        
    # 然后在选择流程下方放置刷新按钮
    st.sidebar.markdown("---")
    refresh_clicked = st.sidebar.button("🔄 刷新报告列表", 
                                      help="点击此按钮重新扫描报告目录，获取最新生成的报告文件",
                                      use_container_width=True,
                                      type="primary")
        
    # 处理刷新按钮点击事件
    if refresh_clicked:
        # 使用实验性API清除缓存，确保真正刷新
        try:
            st.cache_data.clear()
        except:
            pass
        # 强制重新加载报告文件列表
        report_files = get_reports_by_date(selected_date)
        # 使用更优雅的成功消息
        st.sidebar.success("✅ 报告列表已更新！", icon="✨")
        # 移除不需要的提示
        # st.sidebar.info("请重新选择一份报告查看详情")

    if not selected_report_path:
        st.info("请在左侧选择一份报告进行查看。")
        return

    # --- 加载核心数据 ---
    report_content = load_report(selected_report_path)
    if not report_content:
        st.error("无法加载报告内容，请检查文件是否存在或是否为空。")
        return

    metrics_data = extract_metrics_from_report(report_content)
    logging.info(f"📊 提取到的指标数据: {len(metrics_data) if metrics_data else 0} 个指标")
    if metrics_data:
        logging.info(f"📋 指标名称列表: {list(metrics_data.keys())}")
    else:
        logging.warning("⚠️ metrics_data 为空，无法显示指标数据")

    # --- 新增: 调用一次基线系统 ---
    diagnosis_result = None
    baseline_comparison_data = extract_baseline_comparison_from_report(report_content)
    
    if baseline_system and metrics_data:
        query_data = {}
        # 指标名称映射：将报告中的指标名称映射到基线系统的标准名称（基于new_format_data.csv的列名）
        indicator_mapping = {
            # 核心业务指标
            '销售额': '整体GMV',
            '广告GMV': '整体GMV',
            '整体GMV': '整体GMV',
            '观看人数': '直播间观看次数',
            '直播间观看次数': '直播间观看次数',
            '成交人数': '成交人数',
            '成交人数_1': '成交人数',  # 处理带下划线的变体
            '消耗': '消耗',
            '整体ROI': '整体ROI',
            '广告ROI': '整体ROI',
            '客单价': '客单价',
            '平均在线人数': '平均在线',
            '平均在线': '平均在线',
            '整体GPM': 'GPM',
            'GPM': 'GPM',
            
            # 直播间相关指标
            '直播间曝光次数': '直播间曝光次数',
            '直播间曝光人数': '直播间曝光人数',
            '直播间曝光人数_1': '直播间曝光人数',  # 处理带下划线的变体
            '直播间进入人数': '直播间进入人数',
            '在线峰值': '在线峰值',
            '人均观看时长': '人均观看时长',
            
            # 转化相关指标
            '引流成本': '引流成本',
            '转化成本': '转化成本',
            '整体uv价值': '整体uv价值',
            '曝光进入率': '曝光进入率',
            
            # 商品相关指标
            '商品曝光人数': '商品曝光人数',
            '商品-曝光率': '商品-曝光率',
            '商品点击人数': '商品点击人数',
            '商品点击率': '商品点击率',
            '点击转化率': '点击转化率',
            
            # 画面广告指标
            '画面-消耗': '画面-消耗',
            '画面-gmv': '画面-gmv',
            '画面-roi': '画面-roi',
            '画面-消耗占比': '画面-消耗占比',
            '画面-CTR': '画面-CTR',
            '画面-CVR': '画面-CVR',
            '画面-曝光数': '画面-曝光数',
            '画面-点击数': '画面-点击数',
            '画面-转化数': '画面-转化数',
            
            # 视频广告指标
            '视频-消耗': '视频-消耗',
            '视频-gmv': '视频-gmv',
            '视频-roi': '视频-roi',
            '视频-消耗占比': '视频-消耗占比',
            '视频-CTR': '视频-CTR',
            '视频-CVR': '视频-CVR',
            '视频-曝光数': '视频-曝光数',
            '视频-点击数': '视频-点击数',
            '视频-转化数': '视频-转化数',
            
            # 调控相关指标
            '调控消耗': '调控消耗',
            '调控GMV': '调控GMV',
            '调控ROI': '调控ROI',
            '调控成交订单数': '调控成交订单数',
            '调控-消耗占比': '调控-消耗占比',
            
            # 其他财务指标
            '智能优惠劵金额': '智能优惠劵金额',
            '退款金额': '退款金额',
            '整体GSV': '整体GSV',
            '实际ROI': '实际ROI',
            '大瓶装订单数': '大瓶装订单数',
            '三瓶装订单数': '三瓶装订单数',
            '成交件数': '成交件数'
        }
        
        # 从报告中提取的指标数据准备为查询格式
        for name, values in metrics_data.items():
            try:
                # 清理数值字符串
                current_val_str = values.get('当前值', '0').replace(',', '').replace('¥', '').replace('%', '')
                # 处理特殊值
                if current_val_str in ['N/A', 'None', '', '∞', '+∞', '-∞']:
                    continue
                value = float(current_val_str)
                
                # 使用映射后的指标名称
                mapped_name = indicator_mapping.get(name, name)
                query_data[mapped_name] = value
                print(f"📊 指标映射: {name} -> {mapped_name} = {value}")
            except (ValueError, TypeError) as e:
                print(f"⚠️ 跳过无效指标值: {name} = {values.get('当前值', 'N/A')} (错误: {e})")
                continue
        
        try:
            # 尝试从报告文件名中提取日期和小时
            report_basename = os.path.basename(selected_report_path)
            # 修复正则表达式以匹配两种文件名格式：
            # 格式1: 2025-07-19_12-25_analysis_result.md
            # 格式2: 2025-07-11_10-15-39_analysis_result.md
            match = re.search(r'(\d{4}-\d{2}-\d{2})_(\d{2})-\d{2}(?:-\d{2})?', report_basename)
            if match:
                query_data['日期'] = datetime.strptime(match.group(1), '%Y-%m-%d')
                query_data['小时'] = int(match.group(2))
                print(f"📅 从文件名提取: 日期={query_data['日期']}, 小时={query_data['小时']}")
            else:
                print(f"⚠️ 无法从文件名 {report_basename} 中提取日期和小时信息")
            
            # 仅在有小时信息时执行诊断
            if '小时' in query_data:
                print(f"🔍 开始执行智能诊断，查询数据: {query_data}")
                diagnosis_result = baseline_system.real_time_diagnosis(query_data)
                
                # 将从报告中解析的基线值数据合并到诊断结果中
                if diagnosis_result and baseline_comparison_data:
                    print(f"🔄 合并报告中的基线值数据，共 {len(baseline_comparison_data)} 个指标")
                    for indicator, baseline_info in baseline_comparison_data.items():
                        if indicator in diagnosis_result.get('评估结果', {}):
                            # 将报告中的基线值添加到诊断结果中
                            diagnosis_result['评估结果'][indicator]['基线值'] = baseline_info.get('基线值', 'N/A')
                            print(f"✅ 更新指标 {indicator} 的基线值: {baseline_info.get('基线值', 'N/A')}")
                
                print(f"✅ 诊断完成，结果: {diagnosis_result is not None}")
            else:
                print("❌ 缺少小时信息，跳过智能诊断")
        except Exception as e:
            st.error(f"调用基线诊断时出错: {e}")


    # 查找与报告匹配的结构化数据 (用于AI指令)
    all_structured_results = load_json_file(RESULTS_FILE)
    target_result = None
    if all_structured_results:
        filename = os.path.basename(selected_report_path)
        # 修复：支持两种文件名格式
        # 格式1: 2025-07-23_14-23_analysis_result.md
        # 格式2: 2025-07-23_14-23-48_analysis_result.md
        match = re.search(r'(\d{4}-\d{2}-\d{2}_\d{2}-\d{2})(?:-\d{2})?', filename)
        if match:
            report_ts_str = match.group(1)  # 提取 2025-07-23_14-23 部分
            # 直接通过report_file字段匹配，而不是时间戳匹配
            for res in all_structured_results:
                try:
                    # 优先使用report_file字段进行精确匹配
                    if 'report_file' in res and res['report_file'] == filename:
                        target_result = res
                        break
                    # 如果没有report_file字段，则使用时间戳匹配（兼容旧数据）
                    elif 'report_file' not in res:
                        res_ts = datetime.fromisoformat(res['timestamp'])
                        # 从时间戳构造文件名格式进行匹配
                        expected_filename = res_ts.strftime('%Y-%m-%d_%H-%M') + '_analysis_result.md'
                        if expected_filename == filename:
                            target_result = res
                            break
                except (ValueError, KeyError): 
                    continue
        else:
            st.warning(f"无法从文件名 {filename} 中解析出有效的时间戳格式。")

    # --- 主界面选项卡 (已修改) ---
    tabs = st.tabs(["📈 业绩指标", "🤖 智能诊断", "🔬 基线洞察", "💡 AI指令与反馈", "📊 详细报告原文", "📅 历史趋势", "🏆 战术效果分析"]) 

    # --- Tab 1: 业绩指标 ---
    with tabs[0]:
        st.header("业绩关键指标总览")
        if metrics_data:
            st.markdown('<div class="info-box">以下数据提取自报告原文中的"指标变化分析"表。</div>', unsafe_allow_html=True)

            def display_metric(metric_name: str):
                metric_info = get_metric_data(metrics_data, metric_name)
                if metric_info:
                    val_str = metric_info.get('当前值', '0')
                    delta_str = metric_info.get('变化百分比', 'N/A')

                    # 尝试将val_str转换为浮点数，如果失败则保持原样
                    try:
                        # 更彻底的数据清理
                        clean_val = val_str.replace(',', '').replace('weep', '').replace('¥', '').replace('$', '').strip()
                        
                        # 处理百分号
                        if clean_val.endswith('%'):
                            clean_val = clean_val[:-1].strip()
                        
                        # 去除其他可能的特殊字符，只保留数字、小数点、负号
                        import re
                        clean_val = re.sub(r'[^0-9.\-]', '', clean_val)
                        
                        # 确保不是空字符串
                        if clean_val and clean_val.replace('.', '').replace('-', '').isdigit():
                            display_value = float(clean_val)
                        else:
                            display_value = val_str
                    except (ValueError, ImportError):
                        display_value = val_str

                    # 处理delta_str，确保其格式正确
                    display_delta = None
                    if delta_str and delta_str != 'N/A':
                        # 移除百分号并尝试转换为浮点数
                        clean_delta_str = delta_str.replace('%', '').replace('+', '').replace('-', '')
                        try:
                            # 如果是百分比，st.metric会自动添加百分号
                            display_delta = float(clean_delta_str)
                            # 确保正负号正确传递给st.metric
                            if '+' in delta_str: display_delta = abs(display_delta)
                            elif '-' in delta_str: display_delta = -abs(display_delta)
                        except ValueError:
                            display_delta = delta_str # 如果不是有效数字，则保持原样

                    help_text = f"指标: {metric_name}\n当前值: {val_str}\n变化: {delta_str}"
                    st.metric(label=metric_name, value=display_value, delta=display_delta, help=help_text)
                else:
                    st.metric(label=metric_name, value="N/A", delta=None, help=f"未找到指标: {metric_name}")

            # 修正指标名称，使其与报告中的实际指标名称一致
            key_metrics_row1 = ['视频-消耗占比', 'GPM', '点击转化率']
            key_metrics_row2 = ['商品点击率', '整体GMV', '整体ROI']
            
            # 调试信息：检查关键指标是否存在
            all_key_metrics = key_metrics_row1 + key_metrics_row2
            logging.info(f"🔍 检查关键指标存在性:")
            for metric in all_key_metrics:
                exists = metric in metrics_data
                logging.info(f"  - {metric}: {'✅ 存在' if exists else '❌ 不存在'}")
                if not exists:
                    # 查找相似的指标名称
                    similar = [k for k in metrics_data.keys() if metric.lower() in k.lower() or k.lower() in metric.lower()]
                    if similar:
                        logging.info(f"    相似指标: {similar}")

            cols1 = st.columns(len(key_metrics_row1))
            for i, metric_name in enumerate(key_metrics_row1):
                with cols1[i]:
                    display_metric(metric_name)
            
            cols2 = st.columns(len(key_metrics_row2))
            for i, metric_name in enumerate(key_metrics_row2):
                with cols2[i]:
                    display_metric(metric_name)
            
            st.markdown("<hr>", unsafe_allow_html=True)
            
            # 美化的业绩指标展示区域
            st.markdown('<div class="performance-section">', unsafe_allow_html=True)
            
            # 顶部概览卡片区域
            st.markdown('<div class="overview-cards">', unsafe_allow_html=True)
            st.markdown("### 📊 核心业务指标概览")
            
            # 选择三个重要的业务指标
            core_metrics = {}
            core_metric_keys = ["观看人数", "商品曝光人数", "商品点击人数"]
            
            # 提取指标数据，并尝试转换为数值类型
            for key in core_metric_keys:
                if key in metrics_data and '当前值' in metrics_data[key]:
                    val_str = metrics_data[key]['当前值']
                    try:
                        # 尝试转换为浮点数，去除逗号和百分号
                        if '%' in val_str:
                            core_metrics[key] = float(val_str.replace(',', '').replace('%', '')) / 100.0
                        elif '万' in val_str:
                            core_metrics[key] = float(val_str.replace(',', '').replace('万', '')) * 10000
                        else:
                            core_metrics[key] = float(val_str.replace(',', ''))
                    except ValueError:
                        core_metrics[key] = val_str # 如果无法转换，则保留原始字符串
            
            if core_metrics:
                # 美化的指标卡片展示
                metric_icons = {"观看人数": "👥", "商品曝光人数": "👁️", "商品点击人数": "🖱️"}
                metric_colors = {"观看人数": "#FF6B6B", "商品曝光人数": "#4ECDC4", "商品点击人数": "#45B7D1"}
                
                metric_cols = st.columns(len(core_metrics))
                for i, (metric_name, original_value) in enumerate(core_metrics.items()):
                    with metric_cols[i]:
                        metric_info = get_metric_data(metrics_data, metric_name)
                        delta_str = metric_info.get('变化百分比') if metric_info else None
                        
                        # 格式化显示值
                        display_value_for_metric = original_value
                        if isinstance(original_value, (int, float)):
                            if original_value >= 10000:
                                display_value_for_metric = f"{original_value/10000:.1f}万"
                            elif original_value >= 1000:
                                display_value_for_metric = f"{original_value/1000:.1f}K"
                            else:
                                display_value_for_metric = f"{original_value:.0f}"
                        
                        # 处理变化百分比
                        display_delta_for_metric = None
                        if delta_str and delta_str != 'N/A':
                            clean_delta_str = delta_str.replace('%', '').replace('+', '').replace('-', '')
                            try:
                                delta_float = float(clean_delta_str)
                                if '+' in delta_str: display_delta_for_metric = abs(delta_float)
                                elif '-' in delta_str: display_delta_for_metric = -abs(delta_float)
                                else: display_delta_for_metric = delta_float
                            except ValueError:
                                display_delta_for_metric = delta_str
                        
                        # 创建美化的指标卡片
                        icon = metric_icons.get(metric_name, "📊")
                        color = metric_colors.get(metric_name, "#6C7B7F")
                        
                        st.markdown(f"""
                        <div style="
                            background: linear-gradient(135deg, {color}15 0%, {color}25 100%);
                            border: 2px solid {color}40;
                            border-radius: 15px;
                            padding: 20px;
                            text-align: center;
                            margin: 10px 0;
                            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                            transition: transform 0.3s ease;
                        ">
                            <div style="font-size: 2.5em; margin-bottom: 10px;">{icon}</div>
                            <div style="color: {color}; font-weight: bold; font-size: 0.9em; margin-bottom: 5px;">{metric_name}</div>
                            <div style="font-size: 2em; font-weight: bold; color: #2E3440; margin-bottom: 5px;">{display_value_for_metric}</div>
                            <div style="color: {'#27AE60' if display_delta_for_metric and display_delta_for_metric > 0 else '#E74C3C' if display_delta_for_metric and display_delta_for_metric < 0 else '#6C7B7F'}; font-size: 0.9em;">
                                {f"{'↗️' if display_delta_for_metric and display_delta_for_metric > 0 else '↘️' if display_delta_for_metric and display_delta_for_metric < 0 else '➡️'} {delta_str}" if delta_str and delta_str != 'N/A' else '无变化数据'}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                
                st.markdown('</div>', unsafe_allow_html=True)
                
                # 分隔线
                st.markdown('<hr style="margin: 30px 0; border: none; height: 2px; background: linear-gradient(90deg, transparent, #ddd, transparent);">', unsafe_allow_html=True)
                
                # 下方内容区域
                left_col, right_col = st.columns([1, 1])
                
                with left_col:
                    # 产品提及分析
                    st.markdown("""
                    <div style="
                        background: linear-gradient(135deg, #667eea15 0%, #764ba225 100%);
                        border: 2px solid #667eea40;
                        border-radius: 15px;
                        padding: 25px;
                        margin: 10px 0;
                        box-shadow: 0 6px 20px rgba(102, 126, 234, 0.15);
                    ">
                        <h4 style="color: #667eea; margin-bottom: 20px; display: flex; align-items: center;">
                            <span style="font-size: 1.5em; margin-right: 10px;">🔍</span>
                            产品提及分析
                        </h4>
                    """, unsafe_allow_html=True)
                    
                    product_mentions = extract_product_mentions(report_content)
                    if product_mentions:
                        st.markdown(product_mentions, unsafe_allow_html=True)
                    else:
                        st.markdown('<div style="color: #6C7B7F; font-style: italic; text-align: center; padding: 20px;">📝 未在报告中找到产品提及分析</div>', unsafe_allow_html=True)
                    
                    st.markdown('</div>', unsafe_allow_html=True)
                
                with right_col:
                    # 雷达图区域
                    st.markdown("""
                    <div style="
                        background: linear-gradient(135deg, #4ECDC415 0%, #45B7D125 100%);
                        border: 2px solid #4ECDC440;
                        border-radius: 15px;
                        padding: 25px;
                        margin: 10px 0;
                        box-shadow: 0 6px 20px rgba(78, 205, 196, 0.15);
                    ">
                        <h4 style="color: #4ECDC4; margin-bottom: 20px; display: flex; align-items: center;">
                            <span style="font-size: 1.5em; margin-right: 10px;">🎯</span>
                            业务指标雷达图
                        </h4>
                    """, unsafe_allow_html=True)
                    
                    if core_metrics:
                        # 创建雷达图数据 - 使用原始数值
                        radar_data = pd.DataFrame({
                            'metric': list(core_metrics.keys()),
                            'value': [float(v) if isinstance(v, (int, float)) else 0 for v in core_metrics.values()]
                        })
                        
                        # 计算合适的范围
                        max_value = max(radar_data['value']) if len(radar_data['value']) > 0 else 1000
                        range_max = max_value * 1.2  # 留出20%的空间
                        
                        # 使用极坐标图创建雷达图效果
                        fig = px.line_polar(
                            radar_data, 
                            r='value', 
                            theta='metric',
                            line_close=True,
                            title="",
                            range_r=[0, range_max]
                        )
                        fig.update_traces(
                            fill='toself',
                            fillcolor='rgba(78, 205, 196, 0.3)',
                            line_color='rgba(78, 205, 196, 0.8)',
                            line_width=4,
                            marker=dict(size=8, color='rgba(78, 205, 196, 1)')
                        )
                        fig.update_layout(
                            height=350,
                            polar=dict(
                                radialaxis=dict(
                                    visible=True,
                                    range=[0, range_max],
                                    tickformat='.0f',
                                    gridcolor='rgba(78, 205, 196, 0.2)',
                                    linecolor='rgba(78, 205, 196, 0.3)'
                                ),
                                angularaxis=dict(
                                    gridcolor='rgba(78, 205, 196, 0.2)',
                                    linecolor='rgba(78, 205, 196, 0.3)'
                                ),
                                bgcolor='rgba(255, 255, 255, 0.8)'
                            ),
                            showlegend=False,
                            margin=dict(l=20, r=20, t=20, b=20),
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)'
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.markdown('<div style="color: #6C7B7F; font-style: italic; text-align: center; padding: 20px;">📊 无法创建雷达图：数据格式不支持</div>', unsafe_allow_html=True)
                    
                    st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.markdown("""
                <div style="
                    background: linear-gradient(135deg, #FFA50715 0%, #FF634725 100%);
                    border: 2px solid #FFA50740;
                    border-radius: 15px;
                    padding: 30px;
                    text-align: center;
                    margin: 20px 0;
                    box-shadow: 0 6px 20px rgba(255, 165, 7, 0.15);
                ">
                    <div style="font-size: 3em; margin-bottom: 15px;">📊</div>
                    <h4 style="color: #FFA507; margin-bottom: 10px;">暂无核心业务指标数据</h4>
                    <p style="color: #6C7B7F; margin: 0;">报告中未找到核心业务指标数据，请检查数据源</p>
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.warning('在当前报告中未找到或无法解析"指标变化分析"表。')

    # --- Tab 2: 基线洞察 ---
    with tabs[2]:
        st.markdown('''
        <div class="baseline-header">
            <div class="header-content">
                <div class="header-icon">🔬</div>
                <div class="header-text">
                    <h2>基线数据洞察中心</h2>
                    <p>探索系统用于智能评估的历史基线数据，深度解析业务表现的时间规律与趋势</p>
                </div>
            </div>
        </div>
        ''', unsafe_allow_html=True)
        
        if not baseline_system or not baseline_system.baseline_table:
            st.markdown('''
            <div class="baseline-error-card">
                <div class="error-icon">⚠️</div>
                <div class="error-content">
                    <h4>基线数据不可用</h4>
                    <p>系统基线数据未加载或计算失败，无法进行洞察分析</p>
                </div>
            </div>
            ''', unsafe_allow_html=True)
        else:
            
            # 美化的筛选器区域
            st.markdown('''
            <div class="baseline-filter-section">
                <div class="filter-header">
                    <div class="filter-icon">🎯</div>
                    <div class="filter-title">
                        <h4>智能时间筛选器</h4>
                        <p>选择特定时间段，查看对应的基线数据分析</p>
                    </div>
                </div>
            </div>
            ''', unsafe_allow_html=True)
            
            day_options = {0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五", 5: "周六", 6: "周日"}
            hour_options = [f"{h:02d}:00" for h in range(24)]
            
            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                selected_day = st.selectbox("📅 选择星期", options=list(day_options.keys()), format_func=lambda x: day_options[x])
            with col2:
                selected_hour_str = st.selectbox("⏰ 选择小时", options=hour_options)
                selected_hour = int(selected_hour_str.split(':')[0])
            with col3:
                st.markdown(f'''
                <div class="baseline-current-query">
                    <div class="query-icon">📍</div>
                    <div class="query-content">
                        <div class="query-label">当前查询</div>
                        <div class="query-value">{day_options[selected_day]} {selected_hour_str}</div>
                        <div class="query-desc">已选择的时间段</div>
                    </div>
                </div>
                ''', unsafe_allow_html=True)
            
            key = f"{selected_day}_{selected_hour}"
            
            # 美化分隔线
            st.markdown('<div class="baseline-separator"></div>', unsafe_allow_html=True)
            
            # 数据展示区域
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown('''
                <div class="baseline-data-section">
                    <div class="section-header">
                        <div class="section-icon">📈</div>
                        <div class="section-title">
                            <h4>传统基线值</h4>
                            <p>历史数据计算得出的基准参考值</p>
                        </div>
                    </div>
                </div>
                ''', unsafe_allow_html=True)
                
                if key in baseline_system.baseline_table:
                    baseline_df = pd.DataFrame.from_dict(baseline_system.baseline_table[key], orient='index', columns=['基线值'])
                    baseline_df.index.name = '指标'
                    
                    # 创建可视化图表
                    if not baseline_df.empty:
                        st.markdown('<div class="baseline-chart-container">', unsafe_allow_html=True)
                        fig = px.bar(
                            x=baseline_df.index, 
                            y=baseline_df['基线值'], 
                            title="基线值分布",
                            color=baseline_df['基线值'],
                            color_continuous_scale='viridis'
                        )
                        fig.update_layout(
                            height=300, 
                            showlegend=False,
                            plot_bgcolor='rgba(0,0,0,0)',
                            paper_bgcolor='rgba(0,0,0,0)',
                            font=dict(color='white')
                        )
                        st.plotly_chart(fig, use_container_width=True)
                        st.markdown('</div>', unsafe_allow_html=True)
                    
                    st.markdown('<div class="baseline-table-container">', unsafe_allow_html=True)
                    st.dataframe(
                        baseline_df.style.format({'基线值': '{:.2f}'}).background_gradient(subset=['基线值']),
                        use_container_width=True
                    )
                    st.markdown('</div>', unsafe_allow_html=True)
                else:
                    st.markdown('''
                    <div class="baseline-no-data">
                        <div class="no-data-icon">⚠️</div>
                        <div class="no-data-content">
                            <h4>暂无基线数据</h4>
                            <p>该时段未找到传统基线数据</p>
                        </div>
                    </div>
                    ''', unsafe_allow_html=True)
            
            with col2:
                st.markdown('''
                <div class="baseline-data-section">
                    <div class="section-header">
                        <div class="section-icon">📊</div>
                        <div class="section-title">
                            <h4>标准进度指标</h4>
                            <p>比率型指标的标准化进度分析</p>
                        </div>
                    </div>
                </div>
                ''', unsafe_allow_html=True)
                
                if key in baseline_system.standard_progress_table:
                    progress_df = pd.DataFrame.from_dict(baseline_system.standard_progress_table[key], orient='index', columns=['标准进度'])
                    progress_df.index.name = '指标'
                    
                    # 创建进度可视化
                    if not progress_df.empty:
                        st.markdown('<div class="baseline-chart-container">', unsafe_allow_html=True)
                        fig = px.bar(
                            x=progress_df.index, 
                            y=progress_df['标准进度'], 
                            title="标准进度分布",
                            color=progress_df['标准进度'],
                            color_continuous_scale='RdYlGn'
                        )
                        fig.update_layout(
                            height=300, 
                            showlegend=False,
                            plot_bgcolor='rgba(0,0,0,0)',
                            paper_bgcolor='rgba(0,0,0,0)',
                            font=dict(color='white')
                        )
                        fig.update_yaxes(tickformat='.2%')
                        st.plotly_chart(fig, use_container_width=True)
                        st.markdown('</div>', unsafe_allow_html=True)
                    
                    st.markdown('<div class="baseline-table-container">', unsafe_allow_html=True)
                    st.dataframe(
                        progress_df.style.format({'标准进度': '{:.2%}'}).background_gradient(subset=['标准进度']),
                        use_container_width=True
                    )
                    st.markdown('</div>', unsafe_allow_html=True)
                else:
                    st.markdown('''
                    <div class="baseline-no-progress">
                        <div class="no-progress-icon">ℹ️</div>
                        <div class="no-progress-content">
                            <h4>暂无进度数据</h4>
                            <p>该时段无比率型指标，或未计算标准进度</p>
                        </div>
                    </div>
                    ''', unsafe_allow_html=True)
    with tabs[1]:
        # 智能诊断选项卡美化版本
        st.markdown('''
        <div class="diagnosis-section">
            <div class="diagnosis-header">
                <div class="header-content">
                    <div class="header-icon">🤖</div>
                    <div class="header-text">
                        <h2>智能动态基线诊断中心</h2>
                        <p>基于AI算法的实时业务指标健康诊断，为您提供数据驱动的决策支持</p>
                    </div>
                </div>
            </div>
        </div>
        ''', unsafe_allow_html=True)

        if not baseline_system:
            st.markdown('''
            <div class="diagnosis-error-card">
                <div class="error-icon">⚠️</div>
                <div class="error-content">
                    <h4>系统未就绪</h4>
                    <p>基线系统未初始化或初始化失败，无法进行诊断</p>
                </div>
            </div>
            ''', unsafe_allow_html=True)
        elif not diagnosis_result:
            st.markdown('''
            <div class="diagnosis-error-card">
                <div class="error-icon">⚠️</div>
                <div class="error-content">
                    <h4>诊断结果缺失</h4>
                    <p>未能生成诊断结果。这可能是由于报告文件名格式不正确（缺少小时信息），或分析过程中出现内部错误</p>
                </div>
            </div>
            ''', unsafe_allow_html=True)
        elif diagnosis_result.get("error"):
            st.markdown(f'''
            <div class="diagnosis-error-card">
                <div class="error-icon">❌</div>
                <div class="error-content">
                    <h4>系统错误</h4>
                    <p>智能诊断系统出错: {diagnosis_result["error"]}</p>
                </div>
            </div>
            ''', unsafe_allow_html=True)
        elif not diagnosis_result.get("评估结果"):
            st.markdown('''
            <div class="diagnosis-error-card">
                <div class="error-icon">⚠️</div>
                <div class="error-content">
                    <h4>数据不足</h4>
                    <p>没有足够的指标进行诊断，请检查数据源</p>
                </div>
            </div>
            ''', unsafe_allow_html=True)
        else:
            
            # 诊断健康度总览 - 美化版本
            st.markdown('''
            <div class="diagnosis-dashboard">
                <div class="dashboard-title">
                    <h3>📊 诊断健康度仪表板</h3>
                    <p>实时监控AI诊断系统的运行状态和评估效果</p>
                </div>
            </div>
            ''', unsafe_allow_html=True)
            
            input_stats = diagnosis_result.get("输入统计", {})
            col1, col2, col3, col4 = st.columns(4)
            
            # 美化的指标卡片
            total_count = input_stats.get("总输入指标", 0)
            success_count = input_stats.get("成功评估", 0)
            skip_count = input_stats.get("跳过数量", 0)
            success_rate = input_stats.get("评估成功率", "0%")
            
            with col1:
                st.markdown(f'''
                <div class="diagnosis-metric-card total-indicators">
                    <div class="metric-icon">📈</div>
                    <div class="metric-content">
                        <div class="metric-value">{total_count}</div>
                        <div class="metric-label">总输入指标</div>
                        <div class="metric-desc">系统接收到的指标总数</div>
                    </div>
                </div>
                ''', unsafe_allow_html=True)
                
            with col2:
                success_percentage = f"{success_count/total_count:.1%}" if total_count > 0 else "0%"
                st.markdown(f'''
                <div class="diagnosis-metric-card success-indicators">
                    <div class="metric-icon">✅</div>
                    <div class="metric-content">
                        <div class="metric-value">{success_count}</div>
                        <div class="metric-label">成功评估</div>
                        <div class="metric-desc">成功率: {success_percentage}</div>
                    </div>
                </div>
                ''', unsafe_allow_html=True)
                
            with col3:
                st.markdown(f'''
                <div class="diagnosis-metric-card skip-indicators">
                    <div class="metric-icon">⏭️</div>
                    <div class="metric-content">
                        <div class="metric-value">{skip_count}</div>
                        <div class="metric-label">跳过数量</div>
                        <div class="metric-desc">数据质量问题导致</div>
                    </div>
                </div>
                ''', unsafe_allow_html=True)
                
            with col4:
                st.markdown(f'''
                <div class="diagnosis-metric-card success-rate">
                    <div class="metric-icon">🎯</div>
                    <div class="metric-content">
                        <div class="metric-value">{success_rate}</div>
                        <div class="metric-label">评估成功率</div>
                        <div class="metric-desc">AI诊断系统整体效率</div>
                    </div>
                </div>
                ''', unsafe_allow_html=True)
                
            # 评估详情展开器 - 美化版本
            with st.expander("🔍 查看详细评估统计", expanded=False):
                classification_data = diagnosis_result.get("指标分类", {})
                if classification_data:
                    st.markdown('''
                    <div class="diagnosis-details">
                        <h4>📋 指标分类详情</h4>
                        <p>以下是AI诊断系统对各类指标的详细分类统计</p>
                    </div>
                    ''', unsafe_allow_html=True)
                    st.json(classification_data)
                else:
                    st.markdown('''
                    <div class="diagnosis-no-data">
                        <div class="no-data-icon">📊</div>
                        <p>暂无详细分类数据</p>
                    </div>
                    ''', unsafe_allow_html=True)

            # 美化分隔线
            st.markdown('''
            <div class="diagnosis-separator">
                <div class="separator-line"></div>
            </div>
            ''', unsafe_allow_html=True)

            # 分类指标
            good_performance = {k: v for k, v in diagnosis_result["评估结果"].items() if v.get("评估") in ["优秀", "良好", "正常"]}
            need_attention = {k: v for k, v in diagnosis_result["评估结果"].items() if v.get("评估") in ["需改进", "数据不足"]}

            # 综合评估结论 - 美化版本
            total_indicators = len(diagnosis_result["评估结果"])
            good_count = len(good_performance)
            attention_count = len(need_attention)
            
            if good_count > attention_count:
                conclusion_type = "excellent"
                conclusion_icon = "🎉"
                conclusion_text = f"整体表现优秀！{good_count}/{total_indicators} 个指标表现良好，继续保持当前策略。"
            elif attention_count > good_count:
                conclusion_type = "warning"
                conclusion_icon = "⚠️"
                conclusion_text = f"需要关注！{attention_count}/{total_indicators} 个指标需要优化，建议调整相关策略。"
            else:
                conclusion_type = "balanced"
                conclusion_icon = "📊"
                conclusion_text = f"表现平衡，{good_count} 个优秀指标，{attention_count} 个需关注指标，建议持续监控。"
            
            st.markdown(f'''
            <div class="diagnosis-conclusion {conclusion_type}">
                <div class="conclusion-icon">{conclusion_icon}</div>
                <div class="conclusion-content">
                    <h4>AI综合诊断结论</h4>
                    <p>{conclusion_text}</p>
                </div>
            </div>
            ''', unsafe_allow_html=True)

            # 指标展示区域 - 美化版本
            st.markdown('''
            <div class="diagnosis-indicators-section">
                <h3>📊 指标详细分析</h3>
                <p>深入了解各项指标的具体表现和评估详情</p>
            </div>
            ''', unsafe_allow_html=True)
            
            col1, col2 = st.columns([1, 1])

            with col1:
                if need_attention:
                    st.markdown(f'''
                    <div class="diagnosis-indicator-group attention-group">
                        <div class="group-header">
                            <div class="group-icon">⚠️</div>
                            <div class="group-title">
                                <h4>需关注指标</h4>
                                <span class="indicator-count">{len(need_attention)} 项</span>
                            </div>
                        </div>
                    </div>
                    ''', unsafe_allow_html=True)
                    
                    for i, (indicator, details) in enumerate(need_attention.items()):
                        with st.expander(f"🔍 {indicator}", expanded=i==0):
                            # 修复当前值提取逻辑 - 优先从动态详情获取，否则从报告指标数据获取
                            actual_value = 'N/A'
                            if '动态详情' in details and '实际值' in details['动态详情']:
                                actual_value = details['动态详情']['实际值']
                            else:
                                # 对于传统评估的指标，从报告的指标变化分析表中获取当前值
                                if metrics_data and indicator in metrics_data:
                                    metric_info = metrics_data[indicator]
                                    if '当前值' in metric_info:
                                        actual_value = metric_info['当前值']
                            
                            # 修复基线值提取逻辑
                            baseline_value = 'N/A'
                            if '基线值' in details:
                                baseline_value = details['基线值']
                            elif '动态详情' in details and '基线值' in details['动态详情']:
                                baseline_value = details['动态详情']['基线值']
                            
                            eval_method = details.get('评估方法', '传统评估')
                            evaluation = details.get('评估', '未知')
                            
                            # 美化的指标详情卡片
                            st.markdown(f'''
                            <div class="indicator-detail-card attention">
                                <div class="indicator-metrics">
                                    <div class="metric-item">
                                        <div class="metric-label">当前值</div>
                                        <div class="metric-value">{actual_value}</div>
                                        <div class="metric-delta">vs基线: {baseline_value}</div>
                                    </div>
                                    <div class="metric-item">
                                        <div class="metric-label">评估等级</div>
                                        <div class="metric-value evaluation-{evaluation.lower()}">{evaluation}</div>
                                    </div>
                                </div>
                                <div class="indicator-method">
                                    <span class="method-label">🔬 评估方法:</span>
                                    <span class="method-value">{eval_method}</span>
                                </div>
                            </div>
                            ''', unsafe_allow_html=True)
                            
                            if '动态详情' in details and details['动态详情']:
                                st.markdown("**📋 动态评估详情:**")
                                st.json(details['动态详情'])
                else:
                    st.markdown('''
                    <div class="diagnosis-no-attention">
                        <div class="no-attention-icon">🎉</div>
                        <div class="no-attention-content">
                            <h4>暂无需关注指标</h4>
                            <p>所有指标表现良好！继续保持当前策略</p>
                        </div>
                    </div>
                    ''', unsafe_allow_html=True)

            with col2:
                if good_performance:
                    st.markdown(f'''
                    <div class="diagnosis-indicator-group excellent-group">
                        <div class="group-header">
                            <div class="group-icon">✅</div>
                            <div class="group-title">
                                <h4>表现优秀指标</h4>
                                <span class="indicator-count">{len(good_performance)} 项</span>
                            </div>
                        </div>
                    </div>
                    ''', unsafe_allow_html=True)
                    
                    for i, (indicator, details) in enumerate(good_performance.items()):
                        with st.expander(f"📈 {indicator}", expanded=i==0):
                            # 修复当前值提取逻辑 - 优先从动态详情获取，否则从报告指标数据获取
                            actual_value = 'N/A'
                            if '动态详情' in details and '实际值' in details['动态详情']:
                                actual_value = details['动态详情']['实际值']
                            else:
                                # 对于传统评估的指标，从报告的指标变化分析表中获取当前值
                                if metrics_data and indicator in metrics_data:
                                    metric_info = metrics_data[indicator]
                                    if '当前值' in metric_info:
                                        actual_value = metric_info['当前值']
                            
                            # 修复基线值提取逻辑
                            baseline_value = 'N/A'
                            if '基线值' in details:
                                baseline_value = details['基线值']
                            elif '动态详情' in details and '基线值' in details['动态详情']:
                                baseline_value = details['动态详情']['基线值']
                            
                            eval_method = details.get('评估方法', '传统评估')
                            evaluation = details.get('评估', '未知')
                            
                            # 美化的指标详情卡片
                            st.markdown(f'''
                            <div class="indicator-detail-card excellent">
                                <div class="indicator-metrics">
                                    <div class="metric-item">
                                        <div class="metric-label">当前值</div>
                                        <div class="metric-value">{actual_value}</div>
                                        <div class="metric-delta positive">vs基线: {baseline_value}</div>
                                    </div>
                                    <div class="metric-item">
                                        <div class="metric-label">评估等级</div>
                                        <div class="metric-value evaluation-{evaluation.lower()}">{evaluation}</div>
                                    </div>
                                </div>
                                <div class="indicator-method">
                                    <span class="method-label">🔬 评估方法:</span>
                                    <span class="method-value">{eval_method}</span>
                                </div>
                            </div>
                            ''', unsafe_allow_html=True)
                            
                            if '动态详情' in details and details['动态详情']:
                                st.markdown("**📋 动态评估详情:**")
                                st.json(details['动态详情'])
                else:
                    st.markdown('''
                    <div class="diagnosis-no-excellent">
                        <div class="no-excellent-icon">⚠️</div>
                        <div class="no-excellent-content">
                            <h4>暂无优秀指标</h4>
                            <p>建议优化当前策略，提升整体表现</p>
                        </div>
                    </div>
                    ''', unsafe_allow_html=True)



    # --- Tab 4: AI指令与反馈 ---
    with tabs[3]:
        st.markdown('''
        <div class="ai-feedback-header">
            <h1>💡 AI指令与反馈中心</h1>
            <p>智能战术指令生成与效果追踪系统</p>
        </div>
        ''', unsafe_allow_html=True)
        
        # 修正状态管理逻辑，使其更简洁
        if 'show_popup' not in st.session_state:
            st.session_state.show_popup = True
        
        # 将帮助按钮移到标题旁边
        _, help_col = st.columns([0.9, 0.1])
        if help_col.button("?", help="查看AI指令功能说明", use_container_width=True):
            st.session_state.show_popup = not st.session_state.show_popup
            st.rerun()

        if st.session_state.get('show_popup'):
            st.markdown('''
            <div class="ai-help-card">
                <div class="help-header">
                    <div class="help-icon">✨</div>
                    <div class="help-title">
                        <h3>AI战术指令与采纳功能说明</h3>
                        <p>了解如何使用智能战术指令系统</p>
                    </div>
                </div>
                <div class="help-content">
                    <div class="help-section">
                        <h4>🎯 功能作用</h4>
                        <ul>
                            <li><strong>数据驱动的话术策略</strong>: 基于销售数据分析，智能推荐针对性话术战术</li>
                            <li><strong>标准化销售话术</strong>: 提供专业、可复制的话术模板，应对各种销售场景</li>
                            <li><strong>效果追踪与反馈</strong>: 记录您使用的战术并评估其效果</li>
                            <li><strong>形成闭环优化</strong>: 随着数据积累，推荐越来越精准</li>
                        </ul>
                    </div>
                    <div class="help-section">
                        <h4>📝 使用方法</h4>
                        <ol>
                            <li>查看系统根据数据分析推荐的战术指令</li>
                            <li>在直播中应用这些话术策略</li>
                            <li>使用后点击"我已采纳"按钮记录您的反馈</li>
                            <li>在"战术效果分析"选项卡查看各战术的实际效果</li>
                        </ol>
                    </div>
                </div>
            </div>
            ''', unsafe_allow_html=True)
            if st.button("我知道了", use_container_width=True):
                st.session_state.show_popup = False
                st.rerun()
        
        st.markdown("---")

        if not target_result:
            st.markdown('''
            <div class="ai-no-report">
                <div class="no-report-icon">📋</div>
                <div class="no-report-content">
                    <h3>请选择分析报告</h3>
                    <p>请在左侧选择一份报告以查看AI指令（或当前报告无匹配的结构化分析结果）</p>
                </div>
            </div>
            ''', unsafe_allow_html=True)
        else:
            # 修复：从正确的字段读取AI战术指令
            recommended_strategies = target_result.get('ai_tactical_instructions', [])
            if not recommended_strategies:
                # 兼容旧版本字段名
                recommended_strategies = target_result.get('recommended_strategies', [])
            
            feedback_log = load_json_file(FEEDBACK_LOG_FILE, 'list')
            
            if not recommended_strategies:
                st.markdown('''
                <div class="ai-no-strategies">
                    <div class="no-strategies-icon">⚠️</div>
                    <div class="no-strategies-content">
                        <h3>暂无AI战术指令</h3>
                        <p>当前报告没有可供采纳的AI战术指令</p>
                        <div class="reasons-section">
                            <h4>💡 可能的原因：</h4>
                            <ul>
                                <li>该报告生成时AI分析系统认为数据表现平稳，无需特别调整</li>
                                <li>该报告是较早期生成的，当时AI战术指令功能尚未完善</li>
                                <li>系统在分析过程中遇到了数据问题，未能生成有效指令</li>
                            </ul>
                            <div class="suggestion">
                                <strong>建议：</strong> 选择最新的报告（如 2025-07-23_14-23）查看完整的AI战术指令功能
                            </div>
                        </div>
                    </div>
                </div>
                ''', unsafe_allow_html=True)
            else:
                st.markdown('''
                <div class="ai-strategies-intro">
                    <div class="intro-icon">🎯</div>
                    <div class="intro-content">
                        <h4>AI智能诊断完成</h4>
                        <p>根据AI诊断，建议执行以下战术指令。采纳后请点击按钮以供后续效果分析。</p>
                    </div>
                </div>
                ''', unsafe_allow_html=True)
                
                for i, strategy in enumerate(recommended_strategies, 1):
                    if not isinstance(strategy, dict): continue

                    strategy_id = strategy.get('id', f"auto_{datetime.now().strftime('%Y%m%d%H%M%S')}")
                    feedback_key = (target_result['timestamp'], strategy_id)
                    
                    is_adopted = any(
                        entry.get('report_timestamp') == feedback_key[0] and entry.get('strategy_id') == feedback_key[1]
                        for entry in feedback_log
                    )
                    
                    button_text = "✅ 已采纳" if is_adopted else "👉 我要采纳"
                    button_type = "primary" if is_adopted else "secondary"
                    status_class = "adopted" if is_adopted else "pending"

                    st.markdown(f'''
                    <div class="strategy-card {status_class}">
                        <div class="strategy-header">
                            <div class="strategy-number">{i}</div>
                            <div class="strategy-title">
                                <h4>{strategy.get('name', '未知策略')}</h4>
                                <p class="strategy-goal">🎯 目标: {strategy.get('goal', '无')}</p>
                            </div>
                            <div class="strategy-status">
                                <span class="status-badge {status_class}">
                                    {'✅ 已采纳' if is_adopted else '⏳ 待采纳'}
                                </span>
                            </div>
                        </div>
                        <div class="strategy-content">
                            <div class="instruction-label">📋 指令详情:</div>
                            <div class="instruction-text">{strategy.get('instruction', '无')}</div>
                        </div>
                    </div>
                    ''', unsafe_allow_html=True)
                    
                    # 采纳按钮
                    button_key = f"adopt_{feedback_key[0]}_{feedback_key[1]}"
                    if st.button(button_text, key=button_key, use_container_width=True, type=button_type):
                        action_to_take = "cancel" if is_adopted else "adopt"
                        update_feedback(feedback_key[0], strategy, action_to_take)
                        st.rerun()
        
    # --- Tab 5: 详细报告原文 ---
    with tabs[4]:
        # 美化的头部
        st.markdown('''
        <div class="report-original-header">
            <h1>📄 详细报告原文</h1>
        </div>
        ''', unsafe_allow_html=True)
        
        # 添加指标变化分析下拉框
        if metrics_data:
            with st.expander("📊 指标变化分析表", expanded=False):
                st.markdown('<div class="info-box">以下数据提取自报告原文中的"指标变化分析"表，展示各项指标的详细变化情况。</div>', unsafe_allow_html=True)
                
                # 显示完整的指标变化分析表
                table_data = []
                for metric_name, metric_info in metrics_data.items():
                    current_val = metric_info.get('当前值', 'N/A')
                    previous_val = metric_info.get('上小时值', 'N/A')
                    change_pct = metric_info.get('变化百分比', 'N/A')
                    trend = metric_info.get('趋势', 'N/A')
                    status = metric_info.get('状态', 'N/A')
                    
                    table_data.append({
                        '指标名称': metric_name,
                        '当前值': current_val,
                        '上小时值': previous_val,
                        '变化百分比': change_pct,
                        '趋势': trend,
                        '状态': status
                    })
                
                if table_data:
                    df = pd.DataFrame(table_data)
                    st.dataframe(df, use_container_width=True, hide_index=True)
                else:
                    st.info('暂无指标数据')
        
        # 美化的报告内容容器
        filtered_content = filter_report_for_display(report_content)
        st.markdown('<div class="report-content-container">', unsafe_allow_html=True)
        st.markdown(filtered_content, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # --- Tab 6: 历史趋势 ---
    with tabs[5]:
        # 添加美化的头部
        st.markdown('''
        <div class="historical-trend-header">
            <h1>📅 历史业绩趋势</h1>
        </div>
        ''', unsafe_allow_html=True)
        create_historical_trend_chart(baseline_system)

    # --- Tab 7: 战术效果分析 ---
    with tabs[6]:
        st.header("🏆 AI战术有效性分析")
        report_file = os.path.join(SCRIPT_DIR, 'analysis_reports', 'strategy_effectiveness_report.md')
        if st.button("🔄 立即重新生成分析报告"):
            with st.spinner("正在运行效果分析脚本..."):
                try:
                    # 构建命令 (已修改为绝对路径)
                    effectiveness_script_path = os.path.join(SCRIPT_DIR, 'src', 'ai_analysis', 'effectiveness_analyzer.py')
                    result = subprocess.run(
                        [sys.executable, effectiveness_script_path],
                        check=True,
                        capture_output=True,
                        text=True,
                        encoding='utf-8'
                    )
                    st.toast("✅ 效果分析报告已成功更新！", icon="🎉")
                    if result.stdout:
                        st.info(f"效果分析脚本输出:\n{result.stdout}")
                    st.rerun()

                except subprocess.CalledProcessError as e:
                    error_details = (
                        f"效果分析脚本运行失败 (退出码: {e.returncode}):\n\n"
                        f"**错误日志 (STDERR):**\n"
                        f"```\n{e.stderr.strip()}\n```\n\n"
                        f"**脚本输出 (STDOUT):**\n"
                        f"```\n{e.stdout.strip()}\n```"
                    )
                    st.error(error_details)
                except Exception as e:
                    st.error(f"调用脚本时发生意外错误: {e}")
                    
        if os.path.exists(report_file):
            st.markdown("---")
            st.markdown(load_report(report_file), unsafe_allow_html=True)
        else:
            st.info("暂未生成战术有效性分析报告。请点击上方按钮首次生成。")


if __name__ == '__main__':
    main()
    print("=== main()函数执行结束 ===")
