#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
五分钟话术监控启动脚本
提供简单的启动界面和配置选项
"""

import sys
import os
import time
import logging

# 添加当前目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from five_minute_monitor import FiveMinuteMonitor

def print_banner():
    """打印启动横幅"""
    print("="*60)
    print("           五分钟话术监控系统")
    print("="*60)
    print("功能说明：")
    print("- 每5分钟自动检查最近5分钟内的话术内容")
    print("- 使用关键词和AI双重检测闲聊行为")
    print("- 自动生成监控报告和警报")
    print("="*60)

def show_menu():
    """显示菜单"""
    print("\n请选择运行模式：")
    print("1. 单次监控 - 检查最近5分钟的话术内容")
    print("2. 连续监控 - 每5分钟自动检查一次")
    print("3. 自定义间隔连续监控")
    print("4. 查看帮助")
    print("5. 退出")
    print("-"*40)

def show_help():
    """显示帮助信息"""
    print("\n=== 使用帮助 ===")
    print("\n监控原理：")
    print("- 系统会读取text目录下的实时话术JSON文件")
    print("- 根据时间戳筛选最近5分钟内的话术内容")
    print("- 使用关键词匹配和AI分析两种方式检测闲聊")
    print("\n警报级别：")
    print("- normal: 正常，闲聊比例 < 10%")
    print("- medium: 中等警报，闲聊比例 10%-30%")
    print("- high: 高级警报，闲聊比例 > 30%")
    print("\n输出文件：")
    print("- 监控日志：five_minute_monitor.log")
    print("- 异常报告：five_minute_monitor_YYYYMMDD_HHMMSS.json")
    print("\n命令行参数：")
    print("- python five_minute_monitor.py : 单次监控")
    print("- python five_minute_monitor.py --continuous : 连续监控")
    print("\n按任意键返回主菜单...")
    input()

def run_single_monitor():
    """运行单次监控"""
    print("\n正在执行单次监控...")
    monitor = FiveMinuteMonitor()
    
    try:
        report = monitor.run_monitor()
        
        print("\n=== 监控结果 ===")
        print(f"监控时间: {report['monitor_time']}")
        print(f"话术记录数: {report['total_transcripts']}")
        print(f"警报级别: {report['alert_level']}")
        print(f"关键词检测闲聊: {report['keyword_detection']['chat_count']} 条")
        
        if report.get('ai_analysis'):
            ai_ratio = report['ai_analysis'].get('chat_ratio', 0)
            print(f"AI分析闲聊比例: {ai_ratio:.2%}")
            
            if report['ai_analysis'].get('summary'):
                print(f"AI分析总结: {report['ai_analysis']['summary']}")
        
        if report['alert_level'] != 'normal':
            print("\n⚠️  检测到异常闲聊行为，建议关注！")
        else:
            print("\n✅ 话术内容正常，未发现明显闲聊")
            
    except Exception as e:
        print(f"\n❌ 监控执行失败: {e}")
    
    print("\n按任意键返回主菜单...")
    input()

def run_continuous_monitor(interval=5):
    """运行连续监控"""
    print(f"\n启动连续监控模式，每 {interval} 分钟检查一次")
    print("按 Ctrl+C 停止监控\n")
    
    monitor = FiveMinuteMonitor()
    
    try:
        monitor.start_continuous_monitor(interval_minutes=interval)
    except KeyboardInterrupt:
        print("\n监控已停止")
    except Exception as e:
        print(f"\n监控过程中发生错误: {e}")
    
    print("\n按任意键返回主菜单...")
    input()

def get_custom_interval():
    """获取自定义监控间隔"""
    while True:
        try:
            interval = input("\n请输入监控间隔（分钟，建议1-30分钟）: ")
            interval = int(interval)
            
            if 1 <= interval <= 30:
                return interval
            else:
                print("请输入1-30之间的数字")
        except ValueError:
            print("请输入有效的数字")
        except KeyboardInterrupt:
            return None

def main():
    """主函数"""
    print_banner()
    
    while True:
        show_menu()
        
        try:
            choice = input("请输入选项 (1-5): ").strip()
            
            if choice == '1':
                run_single_monitor()
            
            elif choice == '2':
                run_continuous_monitor()
            
            elif choice == '3':
                interval = get_custom_interval()
                if interval:
                    run_continuous_monitor(interval)
            
            elif choice == '4':
                show_help()
            
            elif choice == '5':
                print("\n感谢使用五分钟话术监控系统！")
                break
            
            else:
                print("\n无效选项，请重新选择")
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\n\n程序已退出")
            break
        except Exception as e:
            print(f"\n发生错误: {e}")
            time.sleep(2)

if __name__ == "__main__":
    main()