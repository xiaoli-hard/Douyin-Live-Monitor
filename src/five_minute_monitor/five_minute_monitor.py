#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
五分钟话术监控脚本
定期检查最近五分钟内的实时话术内容，检测是否存在闲聊
"""

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
import re
import logging
from openai import OpenAI
import requests
import hmac
import hashlib
import base64
import urllib.parse

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(Path(__file__).parent / 'five_minute_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class FiveMinuteMonitor:
    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent  # 回到conclusion根目录
        self.text_dir = self.project_root / "text"
        self.config_path = self.project_root / "src" / "host_script_acquisition" / "config.json"
        self.ai_config = self.load_config()
        self.client = self._init_openai_client()
        
        # 钉钉机器人配置
        self.dingtalk_webhook = "https://oapi.dingtalk.com/robot/send?access_token=b4b62aaed287b7ff8a0a7b1b483e938588605bb4c50ab42d1b8f1db92ff11a7a"
        self.dingtalk_secret = "SECe7a613695185509b0124baae939445607ef27af357c6a6ef1b348cbf869c80ce"
        self.dingtalk_send_all = True  # True: 所有监控结果都发送, False: 只发送异常警报
        
        # 闲聊关键词
        self.chat_keywords = [
            "哈哈", "呵呵", "嘻嘻", "哎呀", "天哪", "我的天", "真的吗", "不是吧",
            "好吧", "算了", "随便", "无聊", "累了", "困了", "饿了", "渴了",
            "今天天气", "昨天", "明天", "周末", "假期", "旅游", "电影", "音乐",
            "游戏", "聊天", "八卦", "gossip", "闲聊", "随便聊聊", "聊什么",
            "话说", "对了", "顺便说", "题外话", "扯远了", "说起来"
        ]
    
    def load_config(self):
        """加载配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get('douban_api', {})
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            return {}
    
    def _init_openai_client(self):
        """初始化OpenAI客户端"""
        try:
            return OpenAI(
                api_key=self.ai_config.get('api_key', ''),
                base_url=self.ai_config.get('endpoint', '')
            )
        except Exception as e:
            logger.error(f"初始化AI客户端失败: {e}")
            return None
    
    def get_latest_transcript_files(self):
        """获取最新的实时话术文件，确保跨小时数据获取"""
        json_files = list(self.text_dir.glob("transcripts_JSON_实时_*.json"))
        if not json_files:
            return []
        
        # 按文件名排序，获取最新的文件
        json_files.sort(key=lambda x: x.name)
        
        # 获取当前时间
        current_time = datetime.now()
        current_hour = current_time.hour
        previous_hour = (current_hour - 1) % 24
        
        # 构建当前小时和前一小时的文件名模式
        current_date = current_time.strftime('%Y-%m-%d')
        current_hour_pattern = f"transcripts_JSON_实时_{current_date}_{current_hour:02d}.json"
        previous_hour_pattern = f"transcripts_JSON_实时_{current_date}_{previous_hour:02d}.json"
        
        # 如果是跨天的情况（前一小时是23点）
        if previous_hour == 23 and current_hour == 0:
            previous_date = (current_time - timedelta(days=1)).strftime('%Y-%m-%d')
            previous_hour_pattern = f"transcripts_JSON_实时_{previous_date}_23.json"
        
        # 查找需要的文件
        target_files = []
        for file_path in json_files:
            if file_path.name == current_hour_pattern or file_path.name == previous_hour_pattern:
                target_files.append(file_path)
        
        # 如果没找到特定文件，返回最新的两个文件作为备选
        if not target_files:
            return json_files[-2:] if len(json_files) >= 2 else json_files
        
        return target_files
    
    def get_recent_transcripts(self, minutes=5):
        """获取最近指定分钟内的话术内容，确保跨小时数据完整性"""
        current_time = datetime.now()
        start_time = current_time - timedelta(minutes=minutes)
        
        logger.info(f"获取最近{minutes}分钟的话术数据，时间范围：{start_time.strftime('%Y-%m-%d %H:%M:%S')} 到 {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        recent_transcripts = []
        
        # 获取最新的话术文件
        files = self.get_latest_transcript_files()
        logger.info(f"找到话术文件：{[f.name for f in files]}")
        
        for file_path in files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                file_transcript_count = 0
                for item in data:
                    timestamp_str = item.get('timestamp', '')
                    text = item.get('text', '')
                    
                    # 解析时间戳
                    try:
                        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                        
                        # 检查是否在指定时间范围内
                        if start_time <= timestamp <= current_time:
                            recent_transcripts.append({
                                'timestamp': timestamp_str,
                                'text': text
                            })
                            file_transcript_count += 1
                    except ValueError as ve:
                        logger.warning(f"时间戳解析失败：{timestamp_str}, 错误：{ve}")
                        continue
                
                logger.info(f"从文件 {file_path.name} 获取到 {file_transcript_count} 条符合时间范围的话术")
                        
            except Exception as e:
                logger.error(f"读取文件 {file_path} 失败: {e}")
                continue
        
        # 按时间戳排序
        recent_transcripts.sort(key=lambda x: x['timestamp'])
        
        logger.info(f"总共获取到 {len(recent_transcripts)} 条最近{minutes}分钟的话术记录")
        
        # 如果没有数据，记录详细信息
        if not recent_transcripts:
            logger.warning(f"最近{minutes}分钟内没有话术数据")
            logger.info(f"当前时间：{current_time.strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"查找时间范围：{start_time.strftime('%Y-%m-%d %H:%M:%S')} - {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        return recent_transcripts
    
    def detect_chat_keywords(self, transcripts):
        """基于关键词检测闲聊"""
        chat_instances = []
        
        for transcript in transcripts:
            text = transcript['text'].lower()
            
            for keyword in self.chat_keywords:
                if keyword.lower() in text:
                    chat_instances.append({
                        'timestamp': transcript['timestamp'],
                        'text': transcript['text'],
                        'keyword': keyword,
                        'type': 'keyword_match'
                    })
                    break
        
        return chat_instances
    
    def load_ai_prompt(self):
        """加载AI分析prompt"""
        prompt_file = Path(__file__).parent / 'ai_analysis_prompt.txt'
        try:
            with open(prompt_file, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            logger.warning(f"AI prompt文件未找到: {prompt_file}，使用默认prompt")
            return self.get_default_prompt()
    
    def get_default_prompt(self):
        """获取默认的AI分析prompt"""
        return """
请分析以下直播话术内容，识别其中与室内游乐园销售无关的闲聊部分（摸鱼行为）：

{combined_text}

请以JSON格式返回结果：
{{
  "analysis_result": {{
    "is_off_topic": true/false,
    "risk_level": "high/medium/low",
    "confidence_score": 0.85,
    "detected_keywords": ["关键词1", "关键词2"],
    "off_topic_content": "具体的摸鱼内容摘要",
    "duration_estimate": "预估偏离时长（秒）",
    "recommendation": "建议主播回归正题"
  }},
  "alert_trigger": {{
    "should_alert": true/false,
    "alert_level": "warning/critical",
    "alert_message": "发送给钉钉的警报消息"
  }}
}}
"""
    
    def analyze_with_ai(self, transcripts):
        """使用AI分析话术内容"""
        if not self.client or not transcripts:
            return []
        
        # 合并所有文本
        combined_text = "\n".join([f"[{t['timestamp']}] {t['text']}" for t in transcripts])
        
        # 加载专业的AI分析prompt
        base_prompt = self.load_ai_prompt()
        
        # 构建完整的分析请求
        prompt = f"""
{base_prompt}

## 待分析的直播话术内容：
{combined_text}

请基于上述标准对以上内容进行分析，并严格按照JSON格式输出结果。
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.ai_config.get('model_name', 'doubao-seed-1-6-250615'),
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )
            
            content = response.choices[0].message.content
            
            # 尝试解析JSON
            try:
                # 清理可能的markdown标记
                content = re.sub(r'^```json\s*', '', content)
                content = re.sub(r'\s*```$', '', content)
                
                result = json.loads(content)
                return result
            except json.JSONDecodeError:
                logger.error(f"AI返回内容无法解析为JSON: {content}")
                return {}
                
        except Exception as e:
            logger.error(f"AI分析失败: {e}")
            return {}
    
    def generate_alert_report(self, transcripts, keyword_results, ai_results):
        """生成监控报告"""
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 解析新的AI分析结果格式
        analysis_result = ai_results.get('analysis_result', {}) if ai_results else {}
        alert_trigger = ai_results.get('alert_trigger', {}) if ai_results else {}
        
        report = {
            "monitor_time": current_time,
            "time_window": "最近5分钟",
            "total_transcripts": len(transcripts),
            "keyword_detection": {
                "chat_count": len(keyword_results),
                "instances": keyword_results
            },
            "ai_analysis": {
                "is_off_topic": analysis_result.get('is_off_topic', False),
                "risk_level": analysis_result.get('risk_level', 'low'),
                "confidence_score": analysis_result.get('confidence_score', 0),
                "detected_keywords": analysis_result.get('detected_keywords', []),
                "off_topic_content": analysis_result.get('off_topic_content', ''),
                "duration_estimate": analysis_result.get('duration_estimate', ''),
                "recommendation": analysis_result.get('recommendation', '')
            },
            "alert_trigger": {
                "should_alert": alert_trigger.get('should_alert', False),
                "alert_level": alert_trigger.get('alert_level', 'normal'),
                "alert_message": alert_trigger.get('alert_message', '')
            },
            "alert_level": "normal"
        }
        
        # 确定最终警报级别
        keyword_ratio = len(keyword_results) / len(transcripts) if transcripts else 0
        ai_risk_level = analysis_result.get('risk_level', 'low')
        ai_should_alert = alert_trigger.get('should_alert', False)
        ai_alert_level = alert_trigger.get('alert_level', 'normal')
        
        # 综合判断警报级别
        if (keyword_ratio > 0.3 or 
            ai_risk_level == 'high' or 
            (ai_should_alert and ai_alert_level == 'critical')):
            report["alert_level"] = "high"
        elif (keyword_ratio > 0.1 or 
              ai_risk_level == 'medium' or 
              (ai_should_alert and ai_alert_level == 'warning')):
            report["alert_level"] = "medium"
        
        return report
    
    def save_report(self, report):
        """保存监控报告"""
        # 创建监控报告文件夹
        reports_dir = self.project_root / "monitor_reports"
        reports_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"five_minute_monitor_{timestamp}.json"
        filepath = reports_dir / filename
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            logger.info(f"监控报告已保存: {filepath}")
        except Exception as e:
            logger.error(f"保存报告失败: {e}")
    
    def generate_dingtalk_signature(self, timestamp, secret):
        """生成钉钉机器人签名"""
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        return sign
    
    def send_dingtalk_message(self, report):
        """发送消息到钉钉机器人"""
        try:
            # 生成时间戳和签名
            timestamp = str(round(time.time() * 1000))
            sign = self.generate_dingtalk_signature(timestamp, self.dingtalk_secret)
            
            # 构建webhook URL
            webhook_url = f"{self.dingtalk_webhook}&timestamp={timestamp}&sign={sign}"
            
            # 构建消息内容
            alert_level = report.get('alert_level', 'normal')
            monitor_time = report.get('monitor_time', '')
            total_transcripts = report.get('total_transcripts', 0)
            keyword_count = report.get('keyword_detection', {}).get('chat_count', 0)
            
            # 获取新的AI分析结果
            ai_analysis = report.get('ai_analysis', {})
            alert_trigger = report.get('alert_trigger', {})
            
            is_off_topic = ai_analysis.get('is_off_topic', False)
            risk_level = ai_analysis.get('risk_level', 'low')
            confidence_score = ai_analysis.get('confidence_score', 0)
            detected_keywords = ai_analysis.get('detected_keywords', [])
            off_topic_content = ai_analysis.get('off_topic_content', '')
            recommendation = ai_analysis.get('recommendation', '')
            
            should_alert = alert_trigger.get('should_alert', False)
            ai_alert_message = alert_trigger.get('alert_message', '')
            
            # 根据警报级别设置消息颜色和标题
            if alert_level == 'high':
                title = "🚨 高级警报 - 直播摸鱼检测"
                emoji = "🚨"
            elif alert_level == 'medium':
                title = "⚠️ 中等警报 - 直播摸鱼检测"
                emoji = "⚠️"
            else:
                title = "✅ 正常监控 - 直播摸鱼检测"
                emoji = "✅"
            
            # 构建详细的消息内容
            message_text = f"""## {title}

**监控时间：** {monitor_time}
**监控窗口：** 最近5分钟
**话术总数：** {total_transcripts} 条

### 📊 检测结果
**关键词检测：** {keyword_count} 条疑似闲聊
**AI摸鱼判定：** {'是' if is_off_topic else '否'}
**风险等级：** {risk_level.upper()}
**置信度：** {confidence_score:.2%}
"""
            
            # 添加检测到的关键词
            if detected_keywords:
                keywords_str = '、'.join(detected_keywords[:5])  # 最多显示5个关键词
                if len(detected_keywords) > 5:
                    keywords_str += f"等{len(detected_keywords)}个"
                message_text += f"**检测关键词：** {keywords_str}\n"
            
            # 添加摸鱼内容摘要
            if off_topic_content:
                message_text += f"\n### 🎯 摸鱼内容\n{off_topic_content[:100]}{'...' if len(off_topic_content) > 100 else ''}\n"
            
            # 添加AI建议
            if recommendation:
                message_text += f"\n### 💡 AI建议\n{recommendation}\n"
            
            # 添加自定义警报消息
            if should_alert and ai_alert_message:
                message_text += f"\n### 🔔 警报详情\n{ai_alert_message}\n"
            
            message_text += "\n---\n> 💡 **提示：** 详细分析报告已保存到监控日志文件"
            
            # 构建消息体
            message = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title,
                    "text": message_text
                }
            }
            
            # 发送消息
            headers = {'Content-Type': 'application/json'}
            response = requests.post(webhook_url, json=message, headers=headers, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('errcode') == 0:
                    logger.info("钉钉消息发送成功")
                    return True
                else:
                    logger.error(f"钉钉消息发送失败: {result.get('errmsg', '未知错误')}")
                    return False
            else:
                logger.error(f"钉钉API请求失败，状态码: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"发送钉钉消息时发生错误: {e}")
            return False
    
    def run_monitor(self):
        """执行一次监控"""
        logger.info("开始执行五分钟话术监控...")
        
        # 获取最近5分钟的话术
        transcripts = self.get_recent_transcripts(minutes=5)
        
        if not transcripts:
            logger.info("最近5分钟内没有话术数据")
            return
        
        logger.info(f"获取到 {len(transcripts)} 条最近5分钟的话术记录")
        
        # 关键词检测
        keyword_results = self.detect_chat_keywords(transcripts)
        
        # AI分析
        ai_results = self.analyze_with_ai(transcripts)
        
        # 生成报告
        report = self.generate_alert_report(transcripts, keyword_results, ai_results)
        
        # 输出结果
        logger.info(f"监控结果 - 警报级别: {report['alert_level']}")
        logger.info(f"关键词检测到闲聊: {len(keyword_results)} 条")
        
        if ai_results:
            logger.info(f"AI分析闲聊比例: {ai_results.get('chat_ratio', 0):.2%}")
        
        # 根据配置决定是否发送钉钉消息
        should_send_dingtalk = self.dingtalk_send_all or report['alert_level'] != 'normal'
        dingtalk_success = True
        
        if should_send_dingtalk:
            dingtalk_success = self.send_dingtalk_message(report)
        
        # 如果有异常，保存详细报告
        if report['alert_level'] != 'normal':
            self.save_report(report)
            logger.warning(f"检测到异常闲聊行为，详细报告已保存")
            if should_send_dingtalk and not dingtalk_success:
                logger.warning("钉钉消息发送失败，但监控报告已保存到本地")
        else:
            if should_send_dingtalk:
                if dingtalk_success:
                    logger.info("正常监控状态已通知到钉钉")
                else:
                    logger.warning("钉钉消息发送失败，但监控正常")
            else:
                logger.info("监控正常，未发送钉钉消息（配置为仅异常时发送）")
        
        return report
    
    def start_continuous_monitor(self, interval_minutes=5):
        """启动连续监控"""
        logger.info(f"启动连续监控，每 {interval_minutes} 分钟检查一次")
        
        while True:
            try:
                self.run_monitor()
                time.sleep(interval_minutes * 60)  # 转换为秒
            except KeyboardInterrupt:
                logger.info("监控已停止")
                break
            except Exception as e:
                logger.error(f"监控过程中发生错误: {e}")
                time.sleep(60)  # 出错后等待1分钟再继续

def main():
    monitor = FiveMinuteMonitor()
    
    # 可以选择运行单次监控或连续监控
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--continuous':
        monitor.start_continuous_monitor()
    else:
        monitor.run_monitor()

if __name__ == "__main__":
    main()