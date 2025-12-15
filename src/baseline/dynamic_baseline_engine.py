#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于真实数据的动态基线系统核心模块
支持53个指标的智能评估
"""

import pandas as pd
import numpy as np
import json
import sqlite3
import pickle
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any, Optional
import warnings
import re # Added for regex in real_time_diagnosis
import logging
warnings.filterwarnings('ignore')

logger = logging.getLogger(__name__)

class RealDataDynamicBaseline:
    """基于真实数据的动态基线系统"""
    
    def __init__(self, data_dir: str = "./数据存储"):
        """初始化系统"""
        self.data_dir = data_dir
        self.state_dir = os.path.join(data_dir, "系统状态_real_data")
        os.makedirs(self.state_dir, exist_ok=True)
        
        # 系统状态文件
        self.state_file = os.path.join(self.state_dir, "system_state.pkl")
        self.db_file = os.path.join(self.state_dir, "error_logs.db")
        
        # --- 新增: 列名映射字典，用于兼容不同的历史数据源格式 ---
        self.column_mapping = {
            '时间段': '小时',
            '整体GPM': 'GPM',
            '商品-曝光人数': '商品曝光人数',
            '商品-点击人数': '商品点击人数',
            '商品曝光-点击率': '商品点击率',
            '直播间曝光-进入率': '曝光进入率',
            '商品点击-转化率': '点击转化率',
            '退货订单金额': '退款金额',
            '大瓶GMV': '大瓶装订单数',
            '三瓶GMV': '三瓶装订单数',
            '平均在线人数': '平均在线',
            '直播间曝光量': '直播间曝光次数',
            '广告ROI': '实际ROI',
            '广告GMV': '整体GSV',
            '停留时长': '人均观看时长',
            '优惠券': '智能优惠劵金额',
            '观看-成交率': '整体uv价值',
            # 修复映射关系 - 移除错误的映射，保持数据完整性
            '内容互动人数': '直播间进入人数',
            '新增粉丝团人数': '成交人数_1',
            '直播间评论数': '在线峰值',
            '退货订单数': '成交件数',
            '成交订单成本': '引流成本'
            # 移除重复指标映射: '直播间曝光人数.1' 和 '成交人数.1'
        }
        
        # 指标分类配置 (已更新，包含所有56个指标)
        self.absolute_indicators = [
            '消耗', '整体GMV', '智能优惠劵金额', '退款金额', '整体GSV', '成交人数', 
            '成交件数', '直播间曝光次数', '直播间曝光人数', '直播间进入人数', 
            '直播间观看次数', '在线峰值', '平均在线', '引流成本', '转化成本', 
            '整体uv价值', 'GPM', '人均观看时长', '观看人数', '商品曝光人数', 
            '商品点击人数', '画面-消耗', '画面-gmv', '画面-曝光数', '画面-点击数', 
            '画面-转化数', '视频-消耗', '视频-gmv', '视频-曝光数', '视频-点击数', 
            '视频-转化数', '调控消耗', '调控GMV', '调控成交订单数'
        ]
        self.ratio_indicators = [
            '整体ROI', '实际ROI', '客单价', '曝光进入率', '商品-曝光率', 
            '商品点击率', '点击转化率', '画面-roi', '画面-消耗占比', 
            '画面-CTR', '画面-CVR', '视频-roi', '视频-消耗占比', 
            '视频-CTR', '视频-CVR', '调控ROI', '调控-消耗占比'
        ]
        
        # 系统状态
        self.data_pool = []
        self.baseline_table = {}
        self.standard_progress_table = {}
        self.is_initialized = False
        
        # 初始化数据库
        self._init_database()
        
        # 尝试加载现有状态
        self._load_state()
        
        print(f"🎯 动态基线系统已初始化")
        print(f"📊 支持指标: 绝对数值型{len(self.absolute_indicators)}个, 比率型{len(self.ratio_indicators)}个")
    
    def _init_database(self):
        """初始化数据库"""
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS error_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    level TEXT,
                    message TEXT,
                    details TEXT
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"⚠️ 数据库初始化失败: {e}")
    
    def _log_error(self, level: str, message: str, details: str = ""):
        """记录错误日志"""
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO error_logs (timestamp, level, message, details)
                VALUES (?, ?, ?, ?)
            """, (datetime.now().isoformat(), level, message, details))
            conn.commit()
            conn.close()
        except:
            pass
    
    def _save_state(self):
        """保存系统状态"""
        try:
            state = {
                'data_pool': self.data_pool,
                'baseline_table': self.baseline_table,
                'standard_progress_table': self.standard_progress_table,
                'is_initialized': self.is_initialized,
                'last_update': datetime.now().isoformat()
            }
            with open(self.state_file, 'wb') as f:
                pickle.dump(state, f)
        except Exception as e:
            self._log_error("ERROR", f"保存状态失败", str(e))
    
    def _load_state(self):
        """加载系统状态"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'rb') as f:
                    state = pickle.load(f)
                self.data_pool = state.get('data_pool', [])
                self.baseline_table = state.get('baseline_table', {})
                self.standard_progress_table = state.get('standard_progress_table', {})
                self.is_initialized = state.get('is_initialized', False)
                print(f"✅ 系统状态已加载，数据池包含{len(self.data_pool)}条记录")
        except Exception as e:
            self._log_error("WARNING", f"加载状态失败，使用默认设置", str(e))
    
    def initialize_system(self, historical_data_path: str) -> bool:
        """
        使用历史数据初始化系统
        
        Args:
            historical_data_path: 历史数据文件路径
            
        Returns:
            bool: 是否初始化成功
        """
        try:
            print(f"🚀 开始初始化系统...")
            
            # 读取历史数据，增加 on_bad_lines='skip' 来跳过格式错误的行
            if historical_data_path.endswith('.csv'):
                df = pd.read_csv(historical_data_path, on_bad_lines='skip')
            else:
                df = pd.read_excel(historical_data_path)
            
            print(f"📊 历史数据: {len(df)}行 {len(df.columns)}列 (已跳过错误行)")
            
            # 数据预处理
            df = self._preprocess_data(df)
            
            if len(df) == 0:
                print("❌ 有效数据为空，无法初始化")
                return False
            
            # 将历史数据添加到数据池
            self.data_pool = []
            for _, row in df.iterrows():
                self.data_pool.append(row.to_dict())
            
            # 计算基线和标准进度表
            self._calculate_baseline()
            self._calculate_standard_progress_table()
            
            self.is_initialized = True
            self._save_state()
            
            print(f"✅ 系统初始化完成！")
            print(f"📈 基线覆盖: {len(self.baseline_table)}个时段")
            print(f"📊 标准进度表: {len(self.standard_progress_table)}个时段")
            
            return True
            
        except Exception as e:
            error_msg = f"初始化失败: {e}"
            print(f"❌ {error_msg}")
            self._log_error("ERROR", error_msg, str(e))
            return False
    
    def _preprocess_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        数据预处理 - v3 (重构版，增加列名映射和更强的清洗能力)
        """
        try:
            print("🔧 开始执行新版数据预处理...")
            original_rows = len(df)
            
            # --- 步骤 1: 统一列名 ---
            df.rename(columns=self.column_mapping, inplace=True)
            renamed_cols = [k for k in self.column_mapping.keys() if k in df.columns]
            if renamed_cols:
                print(f"   - 列名重命名: {', '.join(renamed_cols)}")

            # --- 步骤 2: 清洗无效字符和格式化 ---
            # 替换 `-` 为 NaN
            df.replace('-', np.nan, inplace=True)

            # 确保必要字段存在
            required_fields = ["日期", "小时", "主播"]
            for field in required_fields:
                if field not in df.columns:
                    print(f"⚠️ 预处理失败: 缺少关键列 '{field}'")
                    return pd.DataFrame()

            # --- 步骤 3: 处理时间字段 ---
            df["小时"] = df["小时"].astype(str).str.extract(r'(\d+)', expand=False)
            df["小时"] = pd.to_numeric(df["小时"], errors='coerce')
            df["日期"] = pd.to_datetime(df["日期"], errors='coerce')
            
            # 丢弃没有有效时间的行
            df.dropna(subset=["日期", "小时"], inplace=True)
            df["星期几"] = df["日期"].dt.dayofweek
            
            # --- 步骤 4: 强制转换所有指标为数值，并移除脏数据 ---
            all_indicators = self.absolute_indicators + self.ratio_indicators
            for indicator in all_indicators:
                if indicator in df.columns:
                    df[indicator] = pd.to_numeric(df[indicator], errors='coerce')
            
            # 移除关键财务指标为空或0的行
            key_financial_metrics = ['消耗', '整体GMV']
            df.dropna(subset=key_financial_metrics, inplace=True)
            
            # 使用向量化操作移除0值行
            if not df.empty:
                conditions = [df[metric] != 0 for metric in key_financial_metrics if metric in df.columns]
                if conditions:
                    final_mask = np.logical_and.reduce(conditions)
                    df = df[final_mask]  # type: ignore

            cleaned_rows = len(df)
            print(f"🧹 数据清洗完成: 共处理{original_rows}行, 移除{original_rows - cleaned_rows}行无效数据。")
            print(f"📊 预处理后有效数据: {cleaned_rows}行")
            
            return df
            
        except Exception as e:
            self._log_error("ERROR", f"数据预处理失败", str(e))
            return pd.DataFrame()
    
    def _calculate_baseline(self):
        """计算传统基线表"""
        try:
            print(f"📊 计算传统基线表...")
            
            df = pd.DataFrame(self.data_pool)
            self.baseline_table = {}
            
            # 为每个星期几-小时组合计算基线
            for day in range(7):  # 0-6 对应周一到周日
                for hour in range(24):  # 0-23 小时
                    key = f"{day}_{hour}"
                    
                    # 筛选该时段的数据
                    mask = (df["星期几"] == day) & (df["小时"] == hour)
                    subset = df[mask]
                    
                    if len(subset) > 0:
                        baseline_values = {}
                        
                        # 计算所有指标的平均值
                        all_indicators = self.absolute_indicators + self.ratio_indicators
                        for indicator in all_indicators:
                            if indicator in subset.columns:
                                # Linter-friendly way to calculate mean, avoiding chain calls
                                numeric_series = pd.to_numeric(subset[indicator], errors='coerce')
                                valid_series = numeric_series.dropna() # type: ignore
                                if not valid_series.empty: # type: ignore
                                    baseline_values[indicator] = valid_series.mean() # type: ignore
                        
                        if baseline_values:
                            self.baseline_table[key] = baseline_values
            
            print(f"✅ 基线表计算完成，覆盖{len(self.baseline_table)}个时段")
            
        except Exception as e:
            error_msg = f"基线计算失败: {e}"
            print(f"❌ {error_msg}")
            self._log_error("ERROR", error_msg, str(e))
    
    def _calculate_standard_progress_table(self):
        """计算标准进度表（仅针对绝对数值型指标）"""
        try:
            print(f"📈 计算标准进度表...")
            
            df = pd.DataFrame(self.data_pool)
            self.standard_progress_table = {}
            
            # 按日期分组，计算每天的累积进度
            daily_progress = {}
            
            for date, day_df in df.groupby("日期"):
                day_df = day_df.sort_values("小时")
                daily_totals = {}
                
                # 计算每天各指标的总值
                for indicator in self.absolute_indicators:
                    if indicator in day_df.columns:
                        values = pd.to_numeric(day_df[indicator], errors='coerce')
                        daily_totals[indicator] = values.sum() # type: ignore
                
                # 计算累积进度
                for _, row in day_df.iterrows():
                    hour = int(row["小时"])
                    day_of_week = int(row["星期几"])
                    
                    key = f"{day_of_week}_{hour}"
                    
                    if key not in daily_progress:
                        daily_progress[key] = {indicator: [] for indicator in self.absolute_indicators}
                    
                    # 计算到当前小时的累积值
                    for indicator in self.absolute_indicators:
                        if indicator in day_df.columns:
                            mask = day_df["小时"] <= hour
                            cumulative = pd.to_numeric(day_df[mask][indicator], errors='coerce').sum() # type: ignore
                            if daily_totals.get(indicator, 0) > 0:
                                progress = cumulative / daily_totals[indicator]
                                daily_progress[key][indicator].append(progress)
            
            # 计算平均进度
            for key, progress_data in daily_progress.items():
                self.standard_progress_table[key] = {}
                for indicator, progress_list in progress_data.items():
                    if progress_list:
                        self.standard_progress_table[key][indicator] = np.mean(progress_list)
            
            print(f"✅ 标准进度表计算完成，覆盖{len(self.standard_progress_table)}个时段")
            
        except Exception as e:
            error_msg = f"标准进度表计算失败: {e}"
            print(f"❌ {error_msg}")
            self._log_error("ERROR", error_msg, str(e))
    
    def real_time_diagnosis(self, query: Dict[str, Any]) -> Dict[str, Any]:
        """
        实时诊断接口 - v5.1 修复版 (增加实时数据预处理)
        
        Args:
            query: 查询数据，包含星期几、小时和各项指标值
            
        Returns:
            Dict: 详细诊断结果
        """
        # raise ValueError(">>> 如果您看到这条信息，证明我们找对路了！<<<")
        try:
            if not self.is_initialized:
                return {"error": "系统未初始化"}

            # logger.info("--- [数据终点探针] 收到数据，开始逐个检查指标名 ---")
            # for k in query.keys():
            #     logger.info(f"    - 终点Key: '{k}'")
            # logger.info("--- [数据终点探针] 检查完成 ---")


            # --- 关键修复：对实时查询数据进行预处理，使其与历史数据格式一致 ---
            try:
                if '日期' in query and isinstance(query['日期'], str):
                    dt_object = pd.to_datetime(query['日期'])
                    # 修正：使用dayofweek而不是自定义计算，确保与历史数据一致
                    query['星期几'] = dt_object.dayofweek # 0=周一, 6=周日
                    print(f"实时数据日期: {query['日期']}, 转换为星期几: {query['星期几']}")
                
                if '小时' in query and isinstance(query['小时'], str):
                    # 从 '09:00-10:00' 这种格式中提取开始的小时
                    match = re.match(r'(\d{2}):\d{2}-\d{2}:\d{2}', query['小时'])
                    if match:
                        query['小时'] = int(match.group(1))
                        print(f"实时数据小时: {query['小时']} (从 {query.get('小时', '未知')} 提取)")
            except Exception as e:
                self._log_error("WARNING", "实时查询数据预处理失败", str(e))
                print(f"⚠️ 实时数据预处理失败: {e}")
                # 即使失败，也继续使用 .get 的默认值，而不是中断
            
            # 获取时段键
            day = query.get("星期几", 0)
            hour = query.get("小时", 0)
            key = f"{day}_{hour}"
            print(f"生成的键: {key} (星期几={day}, 小时={hour})")
            
            # 检查基线表中是否存在该键
            if key in self.baseline_table:
                print(f"基线表中存在键 {key}，包含 {len(self.baseline_table[key])} 个指标")
            else:
                print(f"⚠️ 基线表中不存在键 {key}，这可能导致评估失败")
                # 尝试查找最接近的键
                for test_key in self.baseline_table.keys():
                    test_day, test_hour = test_key.split('_')
                    if int(test_day) == day:
                        print(f"  - 找到同一天的键: {test_key}")
            
            results = {}
            dynamic_details = {}
            
            # 分别处理绝对数值型和比率型指标
            dynamic_indicators = []
            traditional_indicators = []
            skipped_indicators = []
            
            # 统计输入指标
            input_indicators = []
            for indicator, value in query.items():
                if indicator in ["星期几", "小时", "主播", "场控", "日期", "场次"]:
                    continue
                input_indicators.append(indicator)
            
            print(f"📊 输入指标总数: {len(input_indicators)}个")
            print(f"📋 输入指标列表: {input_indicators}")
            
            # 处理每个指标
            for indicator, value in query.items():
                if indicator in ["星期几", "小时", "主播", "场控", "日期", "场次"]:
                    continue
                
                if value is None or value == "":
                    skipped_indicators.append(f"{indicator} (数值为空)")
                    continue
                
                try:
                    value = float(value)
                except:
                    skipped_indicators.append(f"{indicator} (数值格式错误)")
                    continue
                
                # 应用列名映射
                mapped_indicator = self.column_mapping.get(indicator, indicator)
                
                if mapped_indicator in self.absolute_indicators:
                    # 绝对数值型指标使用动态评估
                    result = self._dynamic_evaluation(mapped_indicator, value, day, hour, query)
                    if result:
                        results[indicator] = result  # 使用原始指标名作为键
                        dynamic_indicators.append(indicator)
                        if "动态详情" in result:
                            dynamic_details[indicator] = result["动态详情"]
                    else:
                        skipped_indicators.append(f"{indicator} (动态评估失败)")
                        
                elif mapped_indicator in self.ratio_indicators:
                    # 比率型指标使用传统评估
                    result = self._traditional_evaluation(mapped_indicator, value, key)
                    if result:
                        results[indicator] = result  # 使用原始指标名作为键
                        traditional_indicators.append(indicator)
                    else:
                        skipped_indicators.append(f"{indicator} (传统评估失败)")
                else:
                    # 未分类的指标
                    skipped_indicators.append(f"{indicator} (未在配置中分类)")
            
            # 统计评估结果
            total_evaluated = len(dynamic_indicators) + len(traditional_indicators)
            print(f"✅ 成功评估指标: {total_evaluated}个")
            print(f"🎯 动态评估: {len(dynamic_indicators)}个")
            print(f"📊 传统评估: {len(traditional_indicators)}个")
            
            if skipped_indicators:
                print(f"⚠️ 跳过指标: {len(skipped_indicators)}个")
                for skip_info in skipped_indicators:
                    print(f"   - {skip_info}")
            
            # 构建最终结果
            diagnosis_result = {
                "诊断时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "查询时段": f"星期{day+1} {hour}:00",
                "输入统计": {
                    "总输入指标": len(input_indicators),
                    "成功评估": total_evaluated,
                    "跳过数量": len(skipped_indicators),
                    "评估成功率": f"{(total_evaluated/len(input_indicators)*100):.1f}%" if input_indicators else "0%"
                },
                "指标分类": {
                    "动态评估指标": dynamic_indicators,
                    "传统评估指标": traditional_indicators,
                    "跳过指标": skipped_indicators
                },
                "评估结果": results
            }
            
            if dynamic_details:
                diagnosis_result["动态评估详情"] = dynamic_details
            
            return diagnosis_result
            
        except Exception as e:
            error_msg = f"诊断失败: {e}"
            self._log_error("ERROR", error_msg, str(e))
            return {"error": error_msg}
    def _dynamic_evaluation(self, indicator: str, value: float, day: int, hour: int, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """动态评估算法（考虑大盘趋势）- 增强版，支持回退机制"""
        try:
            # 简化版动态评估：基于当前值和标准进度
            progress_key = f"{day}_{hour}"
            baseline_value = None
            standard_progress = None
            fallback_method = ""
            
            # 1. 尝试获取精确匹配的基线值
            if progress_key in self.baseline_table and indicator in self.baseline_table[progress_key]:
                baseline_value = self.baseline_table[progress_key][indicator]
                if progress_key in self.standard_progress_table and indicator in self.standard_progress_table[progress_key]:
                    standard_progress = self.standard_progress_table[progress_key][indicator]
                fallback_method = "精确匹配"
            
            # 2. 如果没有精确匹配，尝试同一小时的其他天
            if baseline_value is None:
                for test_day in range(7):
                    test_key = f"{test_day}_{hour}"
                    if test_key in self.baseline_table and indicator in self.baseline_table[test_key]:
                        baseline_value = self.baseline_table[test_key][indicator]
                        if test_key in self.standard_progress_table and indicator in self.standard_progress_table[test_key]:
                            standard_progress = self.standard_progress_table[test_key][indicator]
                        fallback_method = f"同时段回退(星期{test_day+1})"
                        break
            
            # 3. 如果还没有，尝试同一天的其他小时
            if baseline_value is None:
                for test_hour in range(24):
                    test_key = f"{day}_{test_hour}"
                    if test_key in self.baseline_table and indicator in self.baseline_table[test_key]:
                        baseline_value = self.baseline_table[test_key][indicator]
                        if test_key in self.standard_progress_table and indicator in self.standard_progress_table[test_key]:
                            standard_progress = self.standard_progress_table[test_key][indicator]
                        fallback_method = f"同日回退({test_hour}:00)"
                        break
            
            # 4. 最后尝试全局平均值
            if baseline_value is None:
                all_values = []
                for key, indicators in self.baseline_table.items():
                    if indicator in indicators and indicators[indicator] > 0:
                        all_values.append(indicators[indicator])
                if all_values:
                    baseline_value = sum(all_values) / len(all_values)
                    standard_progress = 0.5  # 默认进度
                    fallback_method = f"全局平均({len(all_values)}个样本)"
            
            # 调试信息：输出基线值提取过程
            print(f"🔍 动态评估调试 - 指标: {indicator}, 基线值: {baseline_value}, 回退方法: {fallback_method}")
            
            # 如果找到了基线值，进行评估
            if baseline_value is not None and baseline_value > 0:
                # 动态系数计算
                dynamic_coefficient = value / baseline_value
                
                # 评估结果
                if dynamic_coefficient >= 1.5:
                    level = "优秀"
                elif dynamic_coefficient >= 1.2:
                    level = "良好"
                elif dynamic_coefficient >= 0.8:
                    level = "正常"
                else:
                    level = "需改进"
                
                return {
                    "系数": round(dynamic_coefficient, 2),
                    "评估": level,
                    "评估方法": f"动态评估({fallback_method})",
                    "动态详情": {
                        "标准进度": f"{(standard_progress or 0.5)*100:.1f}%",
                        "基线值": f"{baseline_value:.0f}",
                        "实际值": f"{value:.0f}",
                        "回退方法": fallback_method
                    }
                }
            
            # 如果没有找到任何基线值，但指标值有效，提供基础评估
            if value > 0:
                return {
                    "系数": 1.0,
                    "评估": "数据不足",
                    "评估方法": "基础评估(无基线数据)",
                    "动态详情": {
                        "标准进度": "50.0%",
                        "基线值": "无",
                        "实际值": f"{value:.0f}",
                        "回退方法": "无基线数据"
                    }
                }
            
            return None
            
        except Exception as e:
            self._log_error("ERROR", f"动态评估失败 - {indicator}", str(e))
            return None
    
    def _traditional_evaluation(self, indicator: str, value: float, key: str) -> Optional[Dict[str, Any]]:
        """传统评估算法 - 增强版，支持回退机制"""
        try:
            baseline_value = None
            fallback_method = ""
            day, hour = key.split('_')
            day, hour = int(day), int(hour)
            
            # 1. 尝试获取精确匹配的基线值
            if key in self.baseline_table and indicator in self.baseline_table[key]:
                baseline_value = self.baseline_table[key][indicator]
                fallback_method = "精确匹配"
            
            # 2. 如果没有精确匹配，尝试同一小时的其他天
            if baseline_value is None or baseline_value <= 0:
                for test_day in range(7):
                    test_key = f"{test_day}_{hour}"
                    if test_key in self.baseline_table and indicator in self.baseline_table[test_key]:
                        test_value = self.baseline_table[test_key][indicator]
                        if test_value > 0:
                            baseline_value = test_value
                            fallback_method = f"同时段回退(星期{test_day+1})"
                            break
            
            # 3. 如果还没有，尝试同一天的其他小时
            if baseline_value is None or baseline_value <= 0:
                for test_hour in range(24):
                    test_key = f"{day}_{test_hour}"
                    if test_key in self.baseline_table and indicator in self.baseline_table[test_key]:
                        test_value = self.baseline_table[test_key][indicator]
                        if test_value > 0:
                            baseline_value = test_value
                            fallback_method = f"同日回退({test_hour}:00)"
                            break
            
            # 4. 最后尝试全局平均值
            if baseline_value is None or baseline_value <= 0:
                all_values = []
                for test_key, indicators in self.baseline_table.items():
                    if indicator in indicators and indicators[indicator] > 0:
                        all_values.append(indicators[indicator])
                if all_values:
                    baseline_value = sum(all_values) / len(all_values)
                    fallback_method = f"全局平均({len(all_values)}个样本)"
                elif indicator in self.ratio_indicators:
                    # 对于比率型指标，使用默认值1.0
                    baseline_value = 1.0
                    fallback_method = "默认基线值"
            
            # 调试信息：输出传统评估的基线值提取结果
            print(f"🔍 传统评估调试 - 指标: {indicator}, 基线值: {baseline_value}, 回退方法: {fallback_method}")
            
            # 如果找到了有效的基线值，进行评估
            if baseline_value is not None and baseline_value > 0:
                try:
                    value = float(value)
                    baseline_value = float(baseline_value)
                    coefficient = value / baseline_value
                    
                    # 评估结果
                    if coefficient >= 1.2:
                        level = "优秀"
                    elif coefficient >= 1.1:
                        level = "良好"
                    elif coefficient >= 0.9:
                        level = "正常"
                    else:
                        level = "需改进"
                    
                    return {
                        "系数": round(coefficient, 2),
                        "评估": level,
                        "评估方法": f"传统评估({fallback_method})",
                        "基线值": round(baseline_value, 2)
                    }
                except Exception as e:
                    print(f"  - 计算{indicator}系数时出错: {e}")
                    return None
            
            # 如果没有找到任何基线值，但指标值有效，提供基础评估
            if value > 0:
                return {
                    "系数": 1.0,
                    "评估": "数据不足",
                    "评估方法": "基础评估(无基线数据)",
                    "基线值": "无"
                }
            
            return None
            
        except Exception as e:
            self._log_error("ERROR", f"传统评估失败 - {indicator}", str(e))
            return None
    
    def export_baseline_snapshot(self) -> str:
        """导出基线快照"""
        try:
            if not self.is_initialized:
                return "系统未初始化"
            
            # 创建导出目录
            export_dir = os.path.join(self.data_dir, "基线快照")
            os.makedirs(export_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # 导出基线数据为CSV
            baseline_data = []
            for key, values in self.baseline_table.items():
                day, hour = key.split('_')
                for indicator, baseline_value in values.items():
                    eval_method = "动态评估" if indicator in self.absolute_indicators else "传统评估"
                    baseline_data.append({
                        "星期几": int(day),
                        "小时": int(hour),
                        "指标": indicator,
                        "基线值": baseline_value,
                        "评估方法": eval_method
                    })
            
            baseline_df = pd.DataFrame(baseline_data)
            baseline_csv = os.path.join(export_dir, f"baseline_data_real_{timestamp}.csv")
            baseline_df.to_csv(baseline_csv, index=False, encoding='utf-8')
            
            # 导出完整配置为JSON
            export_data = {
                "导出时间": datetime.now().isoformat(),
                "数据池大小": len(self.data_pool),
                "基线覆盖时段": len(self.baseline_table),
                "标准进度表时段": len(self.standard_progress_table),
                "绝对数值型指标": list(self.absolute_indicators),
                "比率型指标": list(self.ratio_indicators),
                "基线表": self.baseline_table,
                "标准进度表": self.standard_progress_table
            }
            
            json_file = os.path.join(export_dir, f"baseline_snapshot_real_{timestamp}.json")
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            print(f"✅ 基线快照导出完成:")
            print(f"📄 CSV文件: {baseline_csv}")
            print(f"📄 JSON文件: {json_file}")
            
            return json_file
            
        except Exception as e:
            error_msg = f"导出失败: {e}"
            self._log_error("ERROR", error_msg, str(e))
            return error_msg
    
    def get_system_status(self) -> Dict[str, Any]:
        """获取系统状态"""
        try:
            return {
                "系统状态": "已初始化" if self.is_initialized else "未初始化",
                "数据池大小": len(self.data_pool),
                "基线覆盖时段": len(self.baseline_table),
                "标准进度表时段": len(self.standard_progress_table),
                "支持指标": {
                    "绝对数值型": len(self.absolute_indicators),
                    "比率型": len(self.ratio_indicators),
                    "总计": len(self.absolute_indicators) + len(self.ratio_indicators)
                },
                "最后更新": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            return {"error": f"获取状态失败: {e}"}

# 示例使用
if __name__ == "__main__":
    # 创建系统实例
    system = RealDataDynamicBaseline()
    
    # 使用真实历史数据初始化
    historical_data = "/workspace/data/old_table_real.csv"
    if system.initialize_system(historical_data):
        print("✅ 系统初始化成功")
        
        # 显示系统状态
        status = system.get_system_status()
        print(f"📊 系统状态: {status}")
    else:
        print("❌ 系统初始化失败")
    