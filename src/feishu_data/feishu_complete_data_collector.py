import requests
import json
import logging
import os
import csv
from time import sleep
import datetime
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 配置参数
APP_ID = 'cli_a8f7653655bad00e'  # 替换为你的App ID
APP_SECRET = 'WcoLeiZO4UpGRviW7bP7U8bxeXsVbSyy'  # 替换为你的App Secret
SHEET_TOKEN = 'MxtKs4CrthhAhUtf45QcLNevntg'  # 新的表格Token
SHEET_ID = 'ecc6ae'  # 新的工作表ID
CELL_RANGE = 'A1:BF'  # 调整为包含表头和数据的范围

# 创建带有重试和SSL配置的会话
def create_session():
    import os
    
    # 彻底清除所有代理环境变量
    proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 
                  'ALL_PROXY', 'all_proxy', 'NO_PROXY', 'no_proxy']
    for var in proxy_vars:
        if var in os.environ:
            del os.environ[var]
    
    session = requests.Session()
    
    # 明确禁用代理
    session.proxies = {}
    session.trust_env = False  # 不信任环境变量中的代理设置
    
    # 配置重试策略
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # 禁用SSL警告（如果需要）
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    return session

def get_tenant_access_token(app_id, app_secret):
    """获取tenant_access_token"""
    url = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'
    headers = {
        'Content-Type': 'application/json'
    }
    data = {
        'app_id': app_id,
        'app_secret': app_secret
    }
    
    session = create_session()
    
    try:
        logger.debug(f'请求访问令牌: {url}')
        logger.debug(f'请求数据: {data}')
        
        response = session.post(
            url, 
            headers=headers, 
            json=data, 
            timeout=30,
            verify=True
        )
        
        logger.debug(f'令牌响应状态码: {response.status_code}')
        logger.debug(f'令牌响应内容: {response.text}')
        
        response.raise_for_status()
        result = response.json()
        
        if result.get('code') == 0:
            token = result.get('tenant_access_token')
            logger.info('成功获取访问令牌')
            session.close()
            return token
        else:
            logger.error(f'获取访问令牌失败: {result.get("msg")} (错误码: {result.get("code")})')
            session.close()
            return None
            
    except Exception as e:
        logger.error(f'获取访问令牌时发生异常: {str(e)}')
        session.close()
        return None

def get_complete_sheet_data(sheet_token, access_token, max_retries=3):
    """获取完整的表格数据（所有行）"""
    url = f'https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{sheet_token}/values/{SHEET_ID}!{CELL_RANGE}'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    session = create_session()
    
    for retry in range(max_retries):
        try:
            logger.info(f'请求表格数据: {url} (重试次数: {retry+1})')
            
            response = session.get(
                url, 
                headers=headers, 
                timeout=30,
                verify=True
            )
            
            logger.info(f'响应状态码: {response.status_code}')
            
            response.raise_for_status()
            result = response.json()
            
            # 检查API错误码
            if result.get('code') != 0:
                logger.error(f'API错误: {result.get("msg")} (错误码: {result.get("code")})')
                if retry < max_retries - 1:
                    sleep(2)
                    continue
                return None
            
            # 处理表头与数据
            if 'data' in result and 'valueRange' in result['data']:
                values = result['data']['valueRange'].get('values', [])
                if len(values) >= 1:
                    # 获取表头
                    table_headers = values[0]
                    
                    # 处理重复表头
                    header_counts = {}
                    unique_headers = []
                    for header in table_headers:
                        if header in header_counts:
                            header_counts[header] += 1
                            unique_header = f'{header}_{header_counts[header]}'
                            unique_headers.append(unique_header)
                        else:
                            header_counts[header] = 0
                            unique_headers.append(header)
                    
                    table_headers = unique_headers
                    
                    # 获取所有数据行
                    data_rows = values[1:]
                    
                    logger.info(f'成功获取表格数据: {len(table_headers)} 列, {len(data_rows)} 行数据')
                    
                    session.close()
                    return {
                        'headers': table_headers,
                        'data_rows': data_rows
                    }
                else:
                    logger.warning("表格中没有数据")
            
            session.close()
            return None
            
        except requests.exceptions.SSLError as e:
            logger.error(f'SSL连接错误 (重试 {retry+1}/{max_retries}): {str(e)}')
            if retry < max_retries - 1:
                sleep(2)
                continue
        except requests.exceptions.RequestException as e:
            logger.error(f'请求异常 (重试 {retry+1}/{max_retries}): {str(e)}')
            if retry < max_retries - 1:
                sleep(2)
                continue
        except Exception as e:
            logger.error(f'获取表格数据时发生异常 (重试 {retry+1}/{max_retries}): {str(e)}')
            if retry < max_retries - 1:
                sleep(2)
                continue
    
    session.close()
    return None

def save_to_csv(sheet_data, output_file):
    """将表格数据保存到CSV文件"""
    try:
        # 确保输出目录存在
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        headers = sheet_data['headers']
        data_rows = sheet_data['data_rows']
        
        with open(output_file, 'w', newline='', encoding='utf-8-sig') as csvfile:
            writer = csv.writer(csvfile)
            
            # 写入表头
            writer.writerow(headers)
            
            # 写入数据行
            for row in data_rows:
                # 确保行数据长度与表头一致
                padded_row = row + [''] * (len(headers) - len(row))
                writer.writerow(padded_row[:len(headers)])
        
        logger.info(f'成功保存数据到CSV文件: {output_file}')
        logger.info(f'文件包含 {len(headers)} 列, {len(data_rows)} 行数据')
        return True
        
    except Exception as e:
        logger.error(f'保存CSV文件失败: {str(e)}')
        return False

def collect_complete_data():
    """采集完整的飞书表格数据并保存到CSV"""
    logger.info('开始采集飞书表格完整数据...')
    
    # 获取访问令牌
    logger.info('正在获取访问令牌...')
    token = get_tenant_access_token(APP_ID, APP_SECRET)
    if not token:
        logger.error('获取访问令牌失败，无法继续')
        return False
    
    # 获取完整表格数据
    logger.info('正在获取表格数据...')
    sheet_data = get_complete_sheet_data(SHEET_TOKEN, token, max_retries=3)
    
    if not sheet_data:
        logger.error('获取表格数据失败')
        return False
    
    # 生成输出文件名（包含时间戳）
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = f'data/feishu_complete_data/飞书完整数据_{timestamp}.csv'
    
    # 保存到CSV文件
    logger.info(f'正在保存数据到: {output_file}')
    success = save_to_csv(sheet_data, output_file)
    
    if success:
        logger.info('数据采集完成！')
        logger.info(f'输出文件: {os.path.abspath(output_file)}')
        return True
    else:
        logger.error('数据保存失败')
        return False

if __name__ == '__main__':
    # 执行完整数据采集
    collect_complete_data()