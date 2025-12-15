import json
import os
import time
import datetime
import json
import logging
from typing import Optional
from openai import OpenAI
from src.ai_analysis.script_matching_analyzer import ScriptMatchingAnalyzer

# 添加这部分代码
def clean_emojis_for_storage(text: str) -> str:
    """清理文本中的 emoji 字符，保留中文和正常标点"""
    if not text:
        return text
    import re
    # 使用更精确的emoji范围，避免误删中文字符
    emoji_pattern = re.compile(
        r'['
        r'\U0001F600-\U0001F64F'   # 表情符号
        r'\U0001F300-\U0001F5FF'   # 符号和图标
        r'\U0001F680-\U0001F6FF'   # 运输和地图符号
        r'\U0001F1E0-\U0001F1FF'   # 国旗
        r'\U0001F900-\U0001F9FF'   # 补充符号
        r'\U00002600-\U000026FF'   # 杂项符号
        r'\U00002700-\U000027BF'   # 装饰符号
        r']+',
        flags=re.UNICODE
    )
    return emoji_pattern.sub('', text)

# 配置日志 - 避免重复添加处理器
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)  # 改为INFO级别减少日志量
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

class DataAnalyzer:
    def __init__(self, client, config, root_dir: str):
        """初始化时接收项目根目录路径"""
        self.client = client
        self.config = config
        self.root_dir = root_dir
        
        # --- 所有路径都基于 root_dir 构建 ---
        self.data_storage_path = os.path.join(self.root_dir, config['data_storage']['file_path'])
        self.hourly_log_path = os.path.join(self.root_dir, 'data', 'storage', 'hourly_data_log.json')
        
        # 初始化话术匹配分析器
        self.script_analyzer = ScriptMatchingAnalyzer(self.root_dir)
        self.strategy_library_path = os.path.join(self.root_dir, 'src', 'ai_analysis', 'strategy_library.json')
        self.speech_data_path = os.path.join(self.root_dir, config.get('speech_data', {}).get('file_path', 'text/latest_two_cleaned.json'))
        
        self.ensure_data_file_exists()

    def ensure_data_file_exists(self):
        """确保数据存储文件存在并初始化"""
        try:
            if not os.path.exists(self.data_storage_path):
                # 创建目录（如果需要）
                os.makedirs(os.path.dirname(self.data_storage_path), exist_ok=True)
                with open(self.data_storage_path, 'w', encoding='utf-8') as f:
                    json.dump([], f, ensure_ascii=False, indent=2)
        except Exception as e:
            raise RuntimeError(f"初始化数据文件失败: {str(e)}")

    def _load_strategy_library(self):
        """新增方法：加载战术与话术库"""
        try:
            with open(self.strategy_library_path, 'r', encoding='utf-8') as f:
                return json.load(f).get('strategies', [])
        except FileNotFoundError:
            logger.error(f"策略库文件未找到: {self.strategy_library_path}")
            return []
        except Exception as e:
            logger.error(f"加载策略库失败: {str(e)}")
            return []

    def _get_diagnosis_from_ai(self, current_data, previous_data, speech_content, special_variables: Optional[str] = None):
        """修改方法：改为直接从AI获取诊断和战术指令，并强制其必须返回内容"""
        
        # 修复：确保传递给AI的是纯净的指标数据，而不是包含元数据的完整对象
        current_pure_data = current_data.get('data', current_data)  # 如果是完整对象，提取data字段
        previous_pure_data = previous_data.get('data', previous_data) if previous_data else {}
        
        # 强制记录传递给诊断AI的原始数据
        logger.info(f"🔍 传递给诊断AI的当前数据: {json.dumps(current_pure_data, ensure_ascii=False)}")
        logger.info(f"🔍 传递给诊断AI的历史数据: {json.dumps(previous_pure_data, ensure_ascii=False)}")
        
        # 构建变量信息部分
        variables_prompt_part = ""
        if special_variables:
            variables_prompt_part = f"""
        **今日特殊变量**:
        {special_variables}
        ---
        """

        # 构建完整的Prompt，要求AI同时提供诊断和具体战术指令
        prompt = f"""
        你是一位专业的欧莱雅洗发水直播销售分析师和护发产品营销专家。请对比以下当前小时和上一小时的数据，以及当前小时的主播话术。
        你的任务是找出核心问题并提供具体的欧莱雅洗发水营销战术指令来改善问题。

        **重要规则：必须提供至少一条针对欧莱雅洗发水产品的战术指令。如果数据表现平稳或优秀，请提供一条"维持优势"或"锦上添花"的鼓励性指令。**
        
        **产品背景：【滋养修复发质】欧莱雅洗发水护发柔顺洗发露润养秀发发质洗发乳**
        
        {variables_prompt_part}
        当前数据: {json.dumps(current_pure_data, ensure_ascii=False)}
        历史数据: {json.dumps(previous_pure_data, ensure_ascii=False)}
        话术内容: {speech_content}
        
        首先诊断问题，找出以下欧莱雅洗发水直播常见问题中存在的1-3个核心问题。如果一切正常，请诊断为"数据表现平稳"。
        - 产品功效说明不够专业/缺乏护发知识分享
        - 发质问题针对性不强/客群定位模糊
        - 产品体验感不足/缺乏使用效果展示
        - 品牌专业度体现不够/信任感建立不足
        - 价格敏感度高/价值塑造不充分
        - 互动引导缺乏针对性/发质测试环节缺失
        - 数据表现平稳
        
        然后，对每个问题生成一个具体的欧莱雅洗发水营销战术指令，包括:
        1. 战术名称：简短有力的标题（如：专业护发知识分享、发质测试互动、产品体验展示等）
        2. 目标：这个战术想要达成的效果（提升品牌专业度、增强产品信任感、精准客群定位等）
        3. 具体指令：详细的执行方法，包括欧莱雅洗发水相关的话术示例（如："这款欧莱雅洗发水含有滋养修复成分..."、"针对您的发质问题，我推荐..."等）
        
        请严格按照以下JSON格式返回，不要包含任何其他解释或文本:
        {{
          "diagnoses": ["诊断出的问题1"],
          "strategies": [
            {{
              "id": "ai-gen-{int(time.time())}",
              "name": "战术名称1",
              "goal": "战术目标1",
              "instruction": "详细指令内容1，包括具体话术示例"
            }}
          ]
        }}
        """
        try:
            logger.info("正在调用豆包AI获取诊断和战术指令...")
            response = self.client.chat.completions.create(
                model=self.config['douban_api']['model_name'],
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"} # 开启JSON模式以确保格式正确
            )
            ai_response_content = response.choices[0].message.content
            logger.info(f"成功从AI获取到响应: {ai_response_content}")
            
            # 直接解析AI响应，不进行额外的字符串清理
            # 因为过度的正则表达式清理可能会破坏JSON结构
            try:
                return json.loads(ai_response_content)
            except json.JSONDecodeError as json_error:
                logger.warning(f"JSON解析失败，尝试清理特殊标记: {json_error}")
                # 清理豆包API可能返回的特殊标记和多余内容
                cleaned_content = ai_response_content.strip()
                
                # 移除可能的markdown代码块标记
                if cleaned_content.startswith('```json'):
                    cleaned_content = cleaned_content[7:]
                if cleaned_content.endswith('```'):
                    cleaned_content = cleaned_content[:-3]
                
                # 移除豆包API的特殊标记（如 <[PLHD30_never_used_xxx]>）
                import re
                cleaned_content = re.sub(r'<\[PLHD30_never_used_[^>]+\]>', '', cleaned_content)
                
                # 移除多余的JSON对象和注释文字
                # 查找第一个完整的JSON对象
                brace_count = 0
                json_start = -1
                json_end = -1
                
                for i, char in enumerate(cleaned_content):
                    if char == '{' and json_start == -1:
                        json_start = i
                        brace_count = 1
                    elif json_start != -1:
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                json_end = i + 1
                                break
                
                if json_start >= 0 and json_end > json_start:
                    cleaned_content = cleaned_content[json_start:json_end]
                
                # 额外处理：移除可能的中文注释和说明文字
                cleaned_content = re.sub(r'（注：[^）]*）', '', cleaned_content)
                cleaned_content = re.sub(r'\s*,\s*"diagnoses".*$', '', cleaned_content, flags=re.DOTALL)
                
                cleaned_content = cleaned_content.strip()
                logger.info(f"清理后的JSON内容: {cleaned_content[:200]}...")
                return json.loads(cleaned_content)
        except Exception as e:
            logger.error(f"从AI获取诊断和战术指令失败: {e}", exc_info=True)
            # 在API失败时返回一个包含错误信息的默认结果
            return {
                "diagnoses": ["AI分析异常"], 
                "strategies": [{
                    "id": "error-fallback",
                    "name": "AI分析服务出现问题",
                    "goal": "提示用户检查后台服务",
                    "instruction": f"调用AI进行分析时出现错误，请检查后台日志。错误详情: {str(e)}"
                }]
            }

    # 移除不再需要的匹配方法，直接使用AI生成的战术
    # def _match_strategies(self, diagnoses_keywords, strategy_library):
    #    """新增方法：第二步 - 匹配策略，此步不调用AI"""
    #    matched_strategies = []
    #    if not diagnoses_keywords:
    #        return matched_strategies
    #        
    #    for keyword in diagnoses_keywords:
    #        for strategy in strategy_library:
    #            if keyword in strategy.get('triggers', []):
    #                # 避免重复添加同一个策略
    #                if strategy not in matched_strategies:
    #                    matched_strategies.append(strategy)
    #    return matched_strategies

    def load_speech_data(self):
        """加载主播话术数据"""
        logger.info(f"开始加载主播话术数据从: {self.speech_data_path}")
        try:
            if not os.path.exists(self.speech_data_path):
                logger.warning(f"主播话术数据文件不存在: {self.speech_data_path}")
                return []

            with open(self.speech_data_path, 'r', encoding='utf-8') as f:
                speech_data = json.load(f)
            
            logger.info(f"成功从JSON文件加载数据。")
            if not isinstance(speech_data, list):
                logger.warning("主播话术数据格式应为数组，已转换为单元素数组")
                speech_data = [speech_data]
            
            logger.info(f"数据加载完成，共 {len(speech_data)} 条记录。")
            return speech_data
        except json.JSONDecodeError as e:
            logger.error(f"加载主播话术数据失败: JSON解析错误 - {str(e)}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"加载主播话术数据失败: {str(e)}", exc_info=True)
            return []

    def find_matching_speech(self, date_str, time_range):
        """根据日期和时间段查找匹配的主播话术"""
        speech_data = self.load_speech_data()
        for entry in speech_data:
            # 标准化日期和时间段格式进行匹配
            entry_date = entry.get('日期', '')
            # 标准化日期和时间段格式进行匹配
            entry_date = entry.get('日期', '')
            original_time = entry.get('小时', '')
            # 处理不同格式的时间段表示
            if '点' in original_time:
                # 处理'10点-11点'格式
                start_hour = original_time.split('-')[0].replace('点', '').strip()
                entry_time = f"{start_hour}:00-{int(start_hour)+1}:00"
            else:
                # 直接使用现有格式如'10:00-11:00'
                entry_time = original_time
            if entry_date == date_str and entry_time == time_range:
                return entry.get('text', '')
        logger.info(f"未找到匹配的主播话术数据: {date_str} {time_range}")
        return ""
    
    def load_data_from_csv(self):
        """从 new_format_data.csv 文件中读取最后两行数据（修复：直接从文件读取真正的最后两行）"""
        try:
            csv_path = os.path.join(self.root_dir, 'data', 'baseline_data', '欧莱雅数据登记 - 自动化数据 (4).csv')
            if not os.path.exists(csv_path):
                logger.warning(f"CSV文件不存在: {csv_path}")
                return None, None
            
            # 修复：直接从文件读取最后两行，避免pandas跳过有问题的行
            import pandas as pd
            
            # 首先读取文件的所有行来获取真正的最后两行
            with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            if len(lines) < 3:  # 至少需要头部+2行数据
                logger.warning("CSV文件行数不足")
                return None, None
            
            # 获取头部和最后两行
            header_line = lines[0].strip()
            last_line = lines[-1].strip()
            second_last_line = lines[-2].strip()
            
            logger.info(f"CSV文件总行数: {len(lines)}")
            logger.info(f"真正的最后一行(第{len(lines)}行): {last_line[:100]}...")
            logger.info(f"真正的倒数第二行(第{len(lines)-1}行): {second_last_line[:100]}...")
            
            # 解析头部获取列名
            headers = [h.strip() for h in header_line.split(',')]
            logger.info(f"CSV头部列数: {len(headers)}")
            
            # 解析最后两行数据
            def parse_csv_line(line, headers):
                """解析CSV行，处理可能的格式问题"""
                values = [v.strip() for v in line.split(',')]
                # 如果字段数不匹配，截断或填充
                if len(values) > len(headers):
                    logger.warning(f"行字段数({len(values)})超过头部字段数({len(headers)})，截断多余字段")
                    values = values[:len(headers)]
                elif len(values) < len(headers):
                    logger.warning(f"行字段数({len(values)})少于头部字段数({len(headers)})，填充空值")
                    values.extend([''] * (len(headers) - len(values)))
                
                return dict(zip(headers, values))
            
            current_data = parse_csv_line(last_line, headers)
            previous_data = parse_csv_line(second_last_line, headers)
            
            # 记录读取的数据用于调试
            logger.info(f"解析后的当前数据日期: {current_data.get('日期', 'N/A')} {current_data.get('小时', 'N/A')}")
            logger.info(f"解析后的历史数据日期: {previous_data.get('日期', 'N/A')} {previous_data.get('小时', 'N/A')}")
            
            # 详细记录关键指标的CSV原始值
            key_indicators = ['消耗', '整体GMV', '整体ROI']
            for indicator in key_indicators:
                if indicator in current_data:
                    logger.info(f"CSV当前数据(真正第{len(lines)}行) {indicator}: {current_data[indicator]}")
                if indicator in previous_data:
                    logger.info(f"CSV历史数据(真正第{len(lines)-1}行) {indicator}: {previous_data[indicator]}")
            
            return current_data, previous_data
                
        except Exception as e:
            logger.error(f"从CSV文件读取数据失败: {e}", exc_info=True)
            return None, None
    
    def load_speech_from_json(self, target_date, target_hour):
        """直接从转录JSON文件中读取话术内容"""
        try:
            # 将日期格式转换为文件名格式 (2025-08-28 -> 2025-08-28)
            # 将小时格式转换为文件名格式 (22:00-23:00 -> 22)
            hour_num = target_hour.split(':')[0] if ':' in target_hour else target_hour.split('-')[0].replace('点', '').strip()
            
            # 构建JSON文件路径
            json_filename = f"transcripts_JSON_实时_{target_date}_{hour_num.zfill(2)}.json"
            json_path = os.path.join(self.root_dir, 'text', json_filename)
            
            logger.info(f"正在查找话术文件: {json_path}")
            
            if not os.path.exists(json_path):
                logger.warning(f"话术JSON文件不存在: {json_path}")
                return ""
            
            # 读取JSON文件内容
            with open(json_path, 'r', encoding='utf-8') as f:
                transcript_data = json.load(f)
            
            if not isinstance(transcript_data, list):
                logger.warning(f"话术文件格式不正确: {json_path}")
                return ""
            
            # 合并所有话术文本
            speech_texts = []
            for entry in transcript_data:
                text = entry.get('text', '')
                if text and text.strip():
                    speech_texts.append(text.strip())
            
            combined_speech = ' '.join(speech_texts)
            logger.info(f"成功读取话术内容，总长度: {len(combined_speech)} 字符")
            
            return combined_speech
            
        except Exception as e:
            logger.error(f"从JSON文件读取话术失败: {e}", exc_info=True)
            return ""

    def get_previous_hour_data(self):
        """获取上一小时的数据"""
        try:
            # 修复：从新的hourly_log_path读取数据，而不是旧的data_storage_path
            if not os.path.exists(self.hourly_log_path):
                logger.warning(f"找不到小时数据日志文件: {self.hourly_log_path}")
                return None
                
            with open(self.hourly_log_path, 'r', encoding='utf-8') as f:
                all_data = json.load(f)
                
            if len(all_data) >= 2:
                return all_data[-2]  # 返回倒数第二个元素（上一小时）
            elif len(all_data) == 1:
                logger.info("只有一条历史记录，无法获取上一小时数据")
                return None
            else:
                logger.warning("历史数据日志为空")
                return None
        except Exception as e:
            logger.error(f"获取上一小时数据失败: {e}", exc_info=True)
            return None

    def analyze_with_ai(self, current_data, previous_data, speech_content):
        """
        此方法将被废弃，其逻辑被新的 process_hourly_analysis 流程取代。
        为保持兼容，暂时保留但不再使用。
        """
        # 构建提示词
        # 获取分析阈值并转换为百分比
        threshold_percent = self.config['analysis']['threshold'] * 100
        current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        prompt = self.config['analysis']['prompt'].format(
            current_data=json.dumps(current_data['data'], ensure_ascii=False),
            previous_data=json.dumps(previous_data['data'], ensure_ascii=False),
            speech_content=speech_content,
            threshold=threshold_percent,
            current_time=current_time
        )
        
        # 调用豆包AI进行分析
        response = self.client.chat.completions.create(
            model=self.config['douban_api']['model_name'],
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content

    def _generate_detailed_report_with_ai(self, current_data, previous_data, speech_content):
        """
        新增方法：专门用于生成旧版的、包含详细数据表格和分析的Markdown报告。
        修复数据一致性问题：确保AI使用的数据与CSV文件中的原始数据完全一致。
        修复指标映射问题：动态获取飞书数据源的真实指标名称，确保AI使用正确的指标名称。
        """
        threshold_percent = self.config['analysis']['threshold'] * 100
        current_time_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 修复：确保传递给AI的是纯净的指标数据，而不是包含元数据的完整对象
        current_pure_data = current_data.get('data', current_data)  # 如果是完整对象，提取data字段
        previous_pure_data = previous_data.get('data', previous_data) if previous_data else {}
        
        # 强制记录传递给AI的原始数据
        logger.info(f"🔍 传递给详细报告AI的当前数据: {json.dumps(current_pure_data, ensure_ascii=False)}")
        logger.info(f"🔍 传递给详细报告AI的历史数据: {json.dumps(previous_pure_data, ensure_ascii=False)}")
        
        # 数据一致性修复：清理和标准化数据，确保与CSV原始数据完全一致
        def clean_data_for_ai(data_dict):
            """清理数据字典，移除NaN值和非数值数据，确保数据一致性"""
            cleaned = {}
            for key, value in data_dict.items():
                # 跳过非数值列
                if key in ['日期', '小时', '主播', '场控', '场次']:
                    cleaned[key] = str(value) if value is not None else ''
                else:
                    # 处理数值列
                    if value is None or str(value).lower() in ['nan', 'null', '']:
                        cleaned[key] = 0
                    else:
                        try:
                            # 尝试转换为数值，保持原始精度
                            if isinstance(value, (int, float)):
                                cleaned[key] = float(value)
                            else:
                                # 处理字符串形式的数值
                                str_value = str(value).strip()
                                if str_value == '' or str_value.lower() in ['nan', 'null', 'none']:
                                    cleaned[key] = 0
                                else:
                                    cleaned[key] = float(str_value)
                        except (ValueError, TypeError):
                            logger.warning(f"无法转换数值: {key}={value}, 设置为0")
                            cleaned[key] = 0
            return cleaned
        
        # 清理当前和历史数据
        current_clean_data = clean_data_for_ai(current_pure_data)
        previous_clean_data = clean_data_for_ai(previous_pure_data)
        
        # 记录数据清理日志和关键指标对比
        logger.info(f"数据清理完成 - 当前数据条目数: {len(current_clean_data)}, 历史数据条目数: {len(previous_clean_data)}")
        
        # 详细记录关键指标的原始值和清理后的值
        key_indicators = ['消耗', '整体GMV', '整体ROI']
        for indicator in key_indicators:
            if indicator in current_pure_data and indicator in current_clean_data:
                logger.info(f"当前数据 {indicator}: 原始值={current_pure_data[indicator]}, 清理后={current_clean_data[indicator]}")
            if indicator in previous_pure_data and indicator in previous_clean_data:
                logger.info(f"历史数据 {indicator}: 原始值={previous_pure_data[indicator]}, 清理后={previous_clean_data[indicator]}")
        
        # 修复指标映射：动态生成指标表格行，使用飞书数据源的真实指标名称
        def generate_indicator_table_rows(data_dict):
            """根据实际数据动态生成指标表格行"""
            table_rows = []
            # 排除非指标列
            excluded_columns = ['日期', '小时', '主播', '场控', '场次']
            for key in data_dict.keys():
                if key not in excluded_columns:
                    table_rows.append(f"| {key} |        |          |            |      |      |")
            return "\n".join(table_rows)
        
        # 生成动态指标表格
        indicator_table_rows = generate_indicator_table_rows(current_clean_data)
        
        # 使用修复后的Prompt模板，动态插入真实指标名称
        prompt = f"""分析以下两个小时的直播数据对比和主播话术，检测是否存在异常波动：

【当前小时数据】
{json.dumps(current_clean_data, ensure_ascii=False, indent=2)}

【上一小时数据】
{json.dumps(previous_clean_data, ensure_ascii=False, indent=2)}

【主播话术摘要】
{speech_content}

请执行以下深度分析（严格按格式输出，确保内容详实）：
1. 【全面指标分析】对比所有指标差异，计算变化百分比（保留2位小数），分析统计显著性

2. 【异常检测】遵循以下极其严格的判断规则：
   - 所有指标上涨，无论上涨多少，必须标记为🟢正常
   - 所有指标下降但幅度小于{threshold_percent}%，必须标记为🟢正常
   - 仅当指标下降幅度超过{threshold_percent}%时，才能标记为🔴异常
   - 特别注意：上涨的指标绝对不能标记为异常，即使上涨幅度很大

3. 【欧莱雅洗发水产品分析】
   - 重点关注【滋养修复发质】欧莱雅洗发水护发柔顺洗发露润养秀发发质洗发乳的提及情况
   - 分析产品核心卖点提及：滋养修复、护发柔顺、润养秀发等关键词频次
   - 评估产品功效话术效果：发质改善、柔顺效果、滋养成分等描述的转化影响
   - 识别目标客群话术：针对受损发质、干燥发质、追求柔顺效果用户的话术策略

4. 【洗发护发话术深度分析】
   - 提取关键销售话术：产品功效介绍、使用方法指导、效果对比展示
   - 分析专业护发术语使用：氨基酸、蛋白质修复、深层滋养等专业词汇效果
   - 评估互动引导策略：发质测试、使用体验分享、前后对比等互动方式
   - 建立话术与指标关联性：功效强调与转化率、专业度与客单价关系

5. 【根因诊断】结合数据与话术提供3-5个可能原因，每个原因需包含：
   - 具体数据证据（指标变化值）
   - 相关话术片段（直接引用）
   - 因果关系解释

6. 【趋势预测】基于当前数据和话术效果预测下一小时可能趋势

7. 【预警信息】如有异常，按严重程度分级（P0-P2）

输出格式（使用增强Markdown格式，确保视觉清晰）：
## 📊 指标变化分析
**重要提示：必须显示所有指标的对比，使用飞书数据源中的真实指标名称，不能省略任何指标**
| 指标名称 | 当前值 | 上小时值 | 变化百分比 | 趋势 | 状态 |
|----------|--------|----------|------------|------|------|
{indicator_table_rows}
> **状态说明**：🔴 异常（下降超过{threshold_percent}%） | 🟢 正常（上涨或下降不足{threshold_percent}%）

## 🔍 欧莱雅洗发水产品分析
| 关键词类型 | 具体内容 | 提及次数 | 转化效果 |
|------------|----------|----------|----------|
| 产品全称 | 欧莱雅洗发水/护发柔顺洗发露 | [次数] | [转化率变化] |
| 核心功效 | 滋养修复/护发柔顺/润养秀发 | [次数] | [客单价影响] |
| 目标发质 | 受损发质/干燥发质/毛躁发质 | [次数] | [成交人数变化] |
| 专业术语 | 氨基酸/蛋白质修复/深层滋养 | [次数] | [观看时长影响] |

## ⚠️ 异常指标预警
请严格按照下面的嵌套列表格式输出，使用4个空格进行缩进创建子列表:
- **指标名称 (变化百分比)**:
    - **原因分析**: [AI分析的原因]
    - **数据证据**: [引用的具体数据]
    - **话术证据**: [引用的相关话术]

## 💡 欧莱雅洗发水营销优化建议
1. **产品展示优化**: 加强发质对比展示，突出滋养修复效果的可视化呈现
2. **话术策略调整**: 增加专业护发知识分享，提升品牌专业度和用户信任感
3. **互动引导强化**: 设计发质测试环节，让用户参与产品适配性判断
4. **功效强调重点**: 重点突出"滋养修复"、"护发柔顺"等核心卖点的具体效果
5. **客群精准定位**: 针对不同发质问题（干燥、受损、毛躁）提供个性化解决方案

> **分析周期**：{current_time_str} | **数据来源**：飞书表格"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.config['douban_api']['model_name'],
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"生成详细AI分析报告失败: {e}", exc_info=True)
            return f"# AI分析错误\n\n在生成详细分析报告时发生错误：{e}"


    def process_hourly_analysis(self, special_variables: Optional[str] = None):
        """处理小时级分析，包含错误处理和结构化结果返回"""
        try:
            # 如果没有传入special_variables，设置为空字符串
            if special_variables is None:
                special_variables = ""
            
            current_data, previous_data = self.load_data_from_csv()
            
            if not current_data:
                message = "无法从CSV文件读取数据"
                logger.error(message)
                return {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "diagnoses": ["数据读取失败"],
                    "recommended_strategies": [],
                    "report_markdown": f"# {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} 直播复盘AI指令\n\n{message}"
                }
            
            # 获取当前数据的日期和小时信息
            current_date = current_data.get('日期', '')
            current_hour = current_data.get('小时', '')
            
            # 从JSON文件匹配当前小时的话术内容
            current_speech_content = self.load_speech_from_json(current_date, current_hour)
            
            # 获取上一小时的话术内容（如果有上一小时数据）
            previous_speech_content = ""
            if previous_data:
                previous_date = previous_data.get('日期', '')
                previous_hour = previous_data.get('小时', '')
                previous_speech_content = self.load_speech_from_json(previous_date, previous_hour)
            
            logger.info(f"当前数据: {current_date} {current_hour}")
            logger.info(f"当前话术内容长度: {len(current_speech_content)}")
            if previous_data:
                logger.info(f"上一小时数据: {previous_date} {previous_hour}")
                logger.info(f"上一小时话术内容长度: {len(previous_speech_content)}")

            if not previous_data:
                # 即使没有历史数据，也返回标准格式
                message = "首次运行，无历史数据可供对比分析"
                logger.info(message)
                return {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "diagnoses": ["首次运行"],
                    "recommended_strategies": [],
                    "report_markdown": f"# {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} 直播复盘AI指令\n\n{message}"
                }

            # 构建数据结构用于AI分析
            current_entry = {
                'timestamp': f"{current_date} {current_hour.split('-')[0] if '-' in current_hour else current_hour}",
                'data': current_data,
                'speech_content': current_speech_content
            }
            
            previous_entry = {
                'timestamp': f"{previous_date} {previous_hour.split('-')[0] if '-' in previous_hour else previous_hour}",
                'data': previous_data,
                'speech_content': previous_speech_content
            }

            # 话术匹配分析
            script_analysis_result = None
            script_analysis_md = ""
            logger.info(f"检查话术内容: {'有内容' if current_speech_content else '无内容'}")
            if current_speech_content:
                try:
                    # 添加详细日志，记录传入话术分析器的内容
                    logger.info(f"准备进行话术匹配分析，传入内容长度: {len(current_speech_content)}")
                    logger.debug(f"传入话术内容 (前100字符): {current_speech_content[:100]}")

                    script_analysis_result = self.script_analyzer.analyze_script_coverage(current_speech_content)
                    
                    # 添加日志，记录覆盖率分析结果
                    logger.info(f"话术覆盖率分析完成: {json.dumps(script_analysis_result, ensure_ascii=False)}")

                    script_analysis_md = self.script_analyzer.generate_script_matching_report(current_speech_content, current_data)
                    
                    logger.info(f"话术匹配分析报告生成完毕，整体覆盖率: {script_analysis_result['overall_coverage']*100:.1f}%")

                except Exception as e:
                    # 使用 exc_info=True 记录完整的堆栈跟踪
                    logger.error(f"话术匹配分析过程中发生严重错误: {e}", exc_info=True)
                    script_analysis_md = "\n\n## 🎯 话术模板匹配分析\n\n❌ 话术分析功能暂时不可用 (内部错误)\n\n"
            else:
                script_analysis_md = "\n\n## 🎯 话术模板匹配分析\n\n⚠️ 本小时无话术内容记录\n\n"

            # 关键改动：首先生成详细的分析报告
            detailed_report_md = self._generate_detailed_report_with_ai(current_entry, previous_entry, current_speech_content)

            # 添加动态基线对比分析
            from src.baseline.dynamic_baseline_engine import RealDataDynamicBaseline

            # 初始化基线引擎
            baseline_engine = RealDataDynamicBaseline(data_dir=os.path.join(self.root_dir, 'data'))
            baseline_data_path = os.path.join(self.root_dir, 'data', 'baseline_data', '欧莱雅数据登记 - 自动化数据 (4).csv')
            if not baseline_engine.is_initialized:
                baseline_engine.initialize_system(baseline_data_path)

            # 准备基线查询数据
            current_time = datetime.datetime.fromisoformat(current_entry['timestamp'])
            query_data = {
                "星期几": current_time.weekday(),
                "小时": current_time.hour,
                "主播": current_entry.get('anchor', ''),
                **current_entry['data']
            }

            # 获取基线分析结果
            baseline_result = baseline_engine.real_time_diagnosis(query_data)
            
            # 调试：输出完整的基线结果结构
            logger.info(f"🔍 完整基线结果: {json.dumps(baseline_result, ensure_ascii=False, indent=2)}")

            # 格式化基线分析结果为Markdown
            baseline_md = "\n\n---\n\n## 📊 动态基线对比分析\n\n"
            if 'error' in baseline_result:
                baseline_md += f"**错误信息**: {baseline_result['error']}\n\n"
            else:
                baseline_md += f"**分析时段**: {baseline_result['查询时段']}\n\n"
                baseline_md += "### 指标评估结果\n\n"
                baseline_md += "| 指标名称 | 评估结果 | 系数 | 基线值 | 评估方法 |\n"
                baseline_md += "|----------|----------|------|--------|----------|\n"
                for indicator, result in baseline_result['评估结果'].items():
                    # 修复基线值提取逻辑
                    baseline_value = 'N/A'
                    if '基线值' in result:
                        baseline_value = result['基线值']
                    elif '动态详情' in result and '基线值' in result['动态详情']:
                        baseline_value = result['动态详情']['基线值']
                    logger.info(f"🔍 调试基线值提取 - 指标: {indicator}, 结果: {result}, 提取的基线值: {baseline_value}")
                    
                    baseline_md += f"| {indicator} | {result['评估']} | {result['系数']} | {baseline_value} | {result['评估方法']} |\n"

            # 将基线分析和话术分析添加到报告
            detailed_report_md += baseline_md
            detailed_report_md += script_analysis_md

            # 1. (诊断) 调用AI获取结构化的诊断关键词和战术指令
            diagnosis_result = self._get_diagnosis_from_ai(current_entry, previous_entry, current_speech_content, special_variables)
            diagnoses_keywords = diagnosis_result.get("diagnoses", [])
            matched_strategies = diagnosis_result.get("strategies", []) # 直接使用AI生成的战术
            
            # 2. (整合) 将新的AI指令追加到详细报告末尾
            final_report_md = detailed_report_md
            if matched_strategies:
                instructions_md_parts = [
                    "\n\n---\n\n",
                    "## 🤖 AI战术指令\n\n",
                    f"**AI诊断出的核心问题是**: {', '.join(diagnoses_keywords)}\n\n",
                    "**[AI指令]** 主播及场控请注意，请立即执行以下操作：\n"
                ]
                for i, strategy in enumerate(matched_strategies, 1):
                    # 添加调试日志
                    logger.info(f"处理策略 {i}: {strategy}")
                    
                    # 添加以下几行代码，清理策略中的emoji
                    raw_name = strategy.get('name', '')
                    raw_goal = strategy.get('goal', '')
                    raw_instruction = strategy.get('instruction', '')
                    
                    logger.info(f"原始数据 - name: '{raw_name}', goal: '{raw_goal}', instruction: '{raw_instruction[:100]}...'")
                    
                    clean_name = clean_emojis_for_storage(raw_name)
                    clean_goal = clean_emojis_for_storage(raw_goal)
                    clean_instruction = clean_emojis_for_storage(raw_instruction)
                    
                    logger.info(f"清理后数据 - name: '{clean_name}', goal: '{clean_goal}', instruction: '{clean_instruction[:100]}...'")
                    
                    instructions_md_parts.append(
                        f"\n**{i}. {clean_name} (目标: {clean_goal})**\n"
                        f"   - **指令详情**: {clean_instruction}\n"
                    )
                final_report_md += "".join(instructions_md_parts)

            return {
                "timestamp": datetime.datetime.now().isoformat(),
                "diagnoses": diagnoses_keywords,
                "recommended_strategy_ids": [s.get('id') for s in matched_strategies], # 返回策略ID
                "recommended_strategies": matched_strategies, # 保存完整的战术指令
                "script_analysis": script_analysis_result,  # 添加话术分析结果
                "report_markdown": final_report_md
            }
        
        except Exception as e:
            logger.error(f"处理小时级分析时发生未知错误: {e}", exc_info=True)
            # 修复：使用clean_emojis_for_storage函数清理错误消息中的emoji字符
            error_message = clean_emojis_for_storage(str(e))
            return {
                "timestamp": datetime.datetime.now().isoformat(),
                "diagnoses": ["Error"],
                "recommended_strategies": [],
                "report_markdown": f"# 分析流程错误\n\n处理数据时发生严重错误: {error_message}"
            }


# 在文件顶部，import语句之后添加辅助函数
import re

# def clean_emojis_for_storage(text):
#     """清理文本中的emoji字符，避免在存储和处理时出现编码问题"""
#     if not text:
#         return text
#     # 使用正则表达式移除emoji字符
#     emoji_pattern = re.compile("[" 
#         u"\U0001F600-\U0001F64F"  # 表情符号
#         u"\U0001F300-\U0001F5FF"  # 符号和图标
#         u"\U0001F680-\U0001F6FF"  # 运输和地图符号
#         u"\U0001F1E0-\U0001F1FF"  # 国旗
#         u"\U00002702-\U000027B0"  # 各种符号
#         u"\U000024C2-\U0001F251"  # 各种符号
#         ""]+", flags=re.UNICODE)
#     return emoji_pattern.sub(r'', text)



# 从实例方法改为普通函数，移除self参数
def save_analysis_result(analysis_output: dict, root_dir: str):
    """
    保存分析结果为Markdown报告。
    
    Args:
        analysis_output (dict): 包含报告内容的字典。
        root_dir (str): 项目的根目录 (conclusion/) 的绝对路径。
    """
    report_content = analysis_output.get("report_markdown")
    if not report_content:
        logger.error("分析结果中缺少'report_content'，无法保存报告。")
        return

    # --- 使用 root_dir 构建健壮的报告保存路径 ---
    reports_dir = os.path.join(root_dir, 'analysis_reports')
    os.makedirs(reports_dir, exist_ok=True)
    
    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    file_name = f"{timestamp_str}_analysis_result.md"
    file_path = os.path.join(reports_dir, file_name)

    try:
        # 确保使用UTF-8编码保存
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(report_content)
        logger.info(f"分析报告已成功保存至: {file_path}")
    except IOError as e:
        logger.error(f"保存报告失败: {e}")
        raise
    
    # 此外，也将结构化数据保存到JSON文件中
    results_path = os.path.join(root_dir, 'data', 'results', 'analysis_results.json')
    try:
        all_results = []
        if os.path.exists(results_path):
            with open(results_path, 'r', encoding='utf-8') as f:
                try:
                    all_results = json.load(f)
                    if not isinstance(all_results, list):
                        all_results = []
                except json.JSONDecodeError:
                    all_results = []
        
        # 创建一个仅包含推荐策略的简洁条目，清理diagnoses中的emoji
        structured_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "report_file": file_name,
            "diagnoses": [clean_emojis_for_storage(d) for d in analysis_output.get("diagnoses", [])],
            "recommended_strategies": analysis_output.get("recommended_strategies", [])
        }
        all_results.append(structured_entry)

        # 保存更新后的JSON数据
        os.makedirs(os.path.dirname(results_path), exist_ok=True)
        with open(results_path, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.error(f"保存结构化分析结果失败: {e}")