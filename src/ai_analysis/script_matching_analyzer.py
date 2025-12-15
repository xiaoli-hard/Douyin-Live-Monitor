import json
import os
import re
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import pandas as pd
from difflib import SequenceMatcher

# 配置日志
logger = logging.getLogger(__name__)

class ScriptMatchingAnalyzer:
    """
    话术匹配分析器
    基于欧莱雅话术模板，分析主播实际话术是否覆盖关键要点
    """
    
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.script_template_path = os.path.join(root_dir, 'data', 'baseline_data', '2.0欧莱雅话术.xlsx')
        logger.info(f"初始化话术分析器，模板路径: {self.script_template_path}")
        self.script_template = self._load_script_template()
        logger.info(f"话术模板加载完成，共{len(self.script_template)}条记录")
        
        # 定义话术场景和关键要点
        self.script_scenarios = {
            "开场暖场": {
                "keywords": ["欢迎", "关注", "福袋", "抽奖", "免费", "惊喜"],
                "required_elements": ["欢迎语", "关注引导", "福袋提醒"]
            },
            "痛点挖掘": {
                "keywords": ["干枯", "毛躁", "打结", "分叉", "受损", "暗哑", "枯草", "炸开", "扫把"],
                "required_elements": ["发质问题描述", "用户痛点共鸣", "问题严重性强调"]
            },
            "核心卖点": {
                "keywords": ["欧莱雅", "花卉精粹", "精油", "GPS定点", "科技", "修复", "滋养", "营养"],
                "required_elements": ["品牌背书", "核心成分", "技术优势"]
            },
            "利益点阐述": {
                "keywords": ["瀑布", "顺滑", "光泽", "蓬松", "香水", "法式", "香氛", "迷人"],
                "required_elements": ["使用效果描述", "感官体验", "社交价值"]
            },
            "品牌背书": {
                "keywords": ["巴黎欧莱雅", "百年", "专业", "科技", "官方", "旗舰店", "正品", "包邮"],
                "required_elements": ["品牌权威性", "专业性证明", "购买保障"]
            },
            "价格机制": {
                "keywords": ["99元", "三瓶", "500ml", "33元", "性价比", "福利", "惊喜价", "年度"],
                "required_elements": ["价格优势", "价值对比", "优惠理由"]
            },
            "促单催单": {
                "keywords": ["小黄车", "库存", "200单", "拼手速", "倒计时", "最后", "下次"],
                "required_elements": ["紧迫感营造", "稀缺性强调", "行动指令"]
            }
        }
    
    def _load_script_template(self) -> List[Dict]:
        """加载话术模板"""
        try:
            if os.path.exists(self.script_template_path):
                df = pd.read_excel(self.script_template_path)
                template_data = []
                for _, row in df.iterrows():
                    # 确保所有字段都是字符串类型，避免NaN导致的类型错误
                    scenario = row.get('Unnamed: 0', '')
                    category = row.get('Unnamed: 1', '')
                    content = row.get('2.0版本', '')
                    
                    # 处理NaN值，转换为字符串
                    scenario = str(scenario) if pd.notna(scenario) else ''
                    category = str(category) if pd.notna(category) else ''
                    content = str(content) if pd.notna(content) else ''
                    
                    template_data.append({
                        "场景": scenario,
                        "类型": category,
                        "内容": content
                    })
                logger.info(f"成功加载话术模板，共{len(template_data)}条")
                return template_data
            else:
                logger.warning(f"话术模板文件不存在: {self.script_template_path}")
                return []
        except Exception as e:
            logger.error(f"加载话术模板失败: {e}")
            return []
    
    def analyze_script_coverage(self, actual_script: str) -> Dict:
        """
        分析实际话术对模板要点的覆盖情况
        
        Args:
            actual_script: 主播实际话术文本
            
        Returns:
            Dict: 包含覆盖率分析结果的字典
        """
        logger.info(f"开始分析话术覆盖情况，话术长度: {len(actual_script) if actual_script else 0}")
        
        if not actual_script or not actual_script.strip():
            logger.warning("话术内容为空，返回默认结果")
            return {
                "overall_coverage": 0.0,
                "scenario_coverage": {},
                "missing_scenarios": list(self.script_scenarios.keys()),
                "covered_scenarios": [],
                "detailed_analysis": {},
                "recommendations": ["主播话术内容为空，建议按照模板进行话术输出"]
            }
        
        # 清理和预处理话术文本
        cleaned_script = self._clean_script_text(actual_script)
        
        # 分析各场景覆盖情况
        scenario_results = {}
        covered_scenarios = []
        missing_scenarios = []
        
        for scenario, config in self.script_scenarios.items():
            coverage_result = self._analyze_scenario_coverage(cleaned_script, scenario, config)
            scenario_results[scenario] = coverage_result
            
            if coverage_result["coverage_score"] >= 0.3:  # 30%以上认为覆盖
                covered_scenarios.append(scenario)
            else:
                missing_scenarios.append(scenario)
        
        # 计算整体覆盖率
        overall_coverage = len(covered_scenarios) / len(self.script_scenarios) if self.script_scenarios else 0
        logger.info(f"话术分析完成，整体覆盖率: {overall_coverage:.2f}, 覆盖场景: {len(covered_scenarios)}/{len(self.script_scenarios)}")
        
        # 生成优化建议
        recommendations = self._generate_recommendations(scenario_results, missing_scenarios)
        
        return {
            "overall_coverage": round(overall_coverage, 2),
            "scenario_coverage": {k: v["coverage_score"] for k, v in scenario_results.items()},
            "missing_scenarios": missing_scenarios,
            "covered_scenarios": covered_scenarios,
            "detailed_analysis": scenario_results,
            "recommendations": recommendations,
            "analysis_timestamp": datetime.now().isoformat()
        }
    
    def _clean_script_text(self, text: str) -> str:
        """清理话术文本"""
        # 移除特殊字符和多余空格
        cleaned = re.sub(r'[\n\r\t]+', ' ', text)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = cleaned.strip()
        return cleaned
    
    def _analyze_scenario_coverage(self, script: str, scenario: str, config: Dict) -> Dict:
        """分析单个场景的覆盖情况"""
        # 类型检查和转换，确保script是字符串类型
        if not isinstance(script, str):
            logger.warning(f"话术内容不是字符串类型，类型为: {type(script)}, 值为: {script}")
            if script is None:
                script = ""
            else:
                script = str(script)
        
        keywords = config["keywords"]
        required_elements = config["required_elements"]
        
        # 关键词匹配分析
        keyword_matches = []
        for keyword in keywords:
            if keyword in script:
                keyword_matches.append(keyword)
        
        keyword_coverage = len(keyword_matches) / len(keywords) if keywords else 0
        
        # 语义相似度分析（基于模板内容）
        template_similarity = self._calculate_template_similarity(script, scenario)
        
        # 综合评分
        coverage_score = (keyword_coverage * 0.6 + template_similarity * 0.4)
        
        return {
            "coverage_score": round(coverage_score, 2),
            "keyword_coverage": round(keyword_coverage, 2),
            "template_similarity": round(template_similarity, 2),
            "matched_keywords": keyword_matches,
            "missing_keywords": [k for k in keywords if k not in keyword_matches],
            "required_elements": required_elements,
            "analysis_details": {
                "total_keywords": len(keywords),
                "matched_count": len(keyword_matches),
                "scenario": scenario
            }
        }
    
    def _calculate_template_similarity(self, script: str, scenario: str) -> float:
        """计算与模板的相似度"""
        # 找到对应场景的模板内容
        template_content = ""
        for template_item in self.script_template:
            if scenario in template_item.get("场景", "") or scenario in template_item.get("类型", ""):
                template_content += template_item.get("内容", "") + " "
        
        if not template_content.strip():
            return 0.0
        
        # 使用序列匹配计算相似度
        similarity = SequenceMatcher(None, script.lower(), template_content.lower()).ratio()
        return similarity
    
    def _generate_recommendations(self, scenario_results: Dict, missing_scenarios: List[str]) -> List[str]:
        """生成优化建议"""
        recommendations = []
        
        if not missing_scenarios:
            recommendations.append("✅ 话术覆盖完整，各个场景要点都有涉及")
            return recommendations
        
        # 针对缺失场景给出建议
        scenario_suggestions = {
            "开场暖场": "建议增加欢迎语、关注引导和福袋提醒，营造直播间氛围",
            "痛点挖掘": "建议增加用户发质问题描述，引起共鸣，强调问题严重性",
            "核心卖点": "建议强调欧莱雅品牌、花卉精粹成分和GPS定点科技等核心卖点",
            "利益点阐述": "建议描述使用后的顺滑效果、香氛体验等感官利益",
            "品牌背书": "建议强调巴黎欧莱雅的百年专业背景和官方正品保障",
            "价格机制": "建议突出99元三瓶的价格优势和性价比，说明优惠理由",
            "促单催单": "建议增加紧迫感和稀缺性话术，引导用户立即下单"
        }
        
        for scenario in missing_scenarios:
            if scenario in scenario_suggestions:
                recommendations.append(f"❌ 缺失{scenario}：{scenario_suggestions[scenario]}")
        
        # 针对覆盖不足的场景给出改进建议
        for scenario, result in scenario_results.items():
            if 0.1 <= result["coverage_score"] < 0.3:  # 覆盖不足
                missing_keywords = result["missing_keywords"]
                if missing_keywords:
                    recommendations.append(f"⚠️ {scenario}覆盖不足：建议增加关键词 {', '.join(missing_keywords[:3])}")
        
        return recommendations
    
    def generate_script_matching_report(self, actual_script: str, hour_data: Dict) -> str:
        """生成话术匹配分析报告"""
        analysis_result = self.analyze_script_coverage(actual_script)
        
        # 构建Markdown报告
        report_lines = [
            "## 🎯 话术模板匹配分析\n",
            f"**分析时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            f"**整体覆盖率**: {analysis_result['overall_coverage']*100:.1f}%\n\n",
            
            "### 📊 各场景覆盖情况\n\n",
            "| 场景 | 覆盖率 | 状态 | 关键词匹配 |\n",
            "|------|--------|------|------------|\n"
        ]
        
        # 添加场景详情
        for scenario, details in analysis_result["detailed_analysis"].items():
            coverage_pct = details["coverage_score"] * 100
            status = "✅" if coverage_pct >= 30 else "⚠️" if coverage_pct >= 10 else "❌"
            matched_keywords = ", ".join(details["matched_keywords"][:3]) if details["matched_keywords"] else "无"
            report_lines.append(f"| {scenario} | {coverage_pct:.1f}% | {status} | {matched_keywords} |\n")
        
        report_lines.extend([
            "\n### 🎯 优化建议\n\n"
        ])
        
        for i, recommendation in enumerate(analysis_result["recommendations"], 1):
            report_lines.append(f"{i}. {recommendation}\n")
        
        # 添加缺失场景的模板参考
        if analysis_result["missing_scenarios"]:
            report_lines.extend([
                "\n### 📝 缺失场景模板参考\n\n"
            ])
            
            for scenario in analysis_result["missing_scenarios"][:3]:  # 只显示前3个
                template_content = self._get_scenario_template(scenario)
                if template_content:
                    report_lines.append(f"**{scenario}模板**:\n```\n{template_content[:200]}...\n```\n\n")
        
        return "".join(report_lines)
    
    def _get_scenario_template(self, scenario: str) -> str:
        """获取指定场景的模板内容"""
        for template_item in self.script_template:
            if scenario in template_item.get("场景", ""):
                return template_item.get("内容", "")
        return ""
    
    def get_real_time_script_suggestions(self, current_script: str, missing_scenarios: List[str]) -> List[Dict]:
        """获取实时话术建议"""
        suggestions = []
        
        for scenario in missing_scenarios[:2]:  # 只返回最重要的2个建议
            template_content = self._get_scenario_template(scenario)
            if template_content:
                suggestions.append({
                    "scenario": scenario,
                    "priority": "high" if scenario in ["核心卖点", "促单催单"] else "medium",
                    "suggestion": template_content[:100] + "...",
                    "keywords": self.script_scenarios.get(scenario, {}).get("keywords", [])[:3]
                })
        
        return suggestions