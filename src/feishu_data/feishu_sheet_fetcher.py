import requests
import json
import logging
import os
from time import sleep
import datetime
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 配置日志
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 配置参数
APP_ID = 'cli_a8f7653655bad00e'  # 替换为你的App ID
APP_SECRET = 'WcoLeiZO4UpGRviW7bP7U8bxeXsVbSyy'  # 替换为你的App Secret
SHEET_TOKEN = 'MxtKs4CrthhAhUtf45QcLNevntg'  # 新的表格Token
SHEET_ID = 'ecc6ae'  # 新的工作表ID
CELL_RANGE = 'A1:BF'  # 调整为包含表头和数据的范围  # 单元格范围


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
    
    # 设置User-Agent
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    logging.info(f"Session proxies: {session.proxies}")
    logging.info(f"Session trust_env: {session.trust_env}")
    
    return session

# 获取tenant_access_token
def get_tenant_access_token(app_id, app_secret):
    url = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/'
    headers = {'Content-Type': 'application/json'}
    data = {
        'app_id': app_id,
        'app_secret': app_secret
    }
    
    session = create_session()
    
    try:
        logger.debug(f'请求tenant_access_token: {url}')
        # 增加更详细的调试信息
        logger.debug(f'请求头: {headers}')
        logger.debug(f'请求数据: {data}')
        
        response = session.post(
            url, 
            headers=headers, 
            json=data, 
            timeout=30,  # 增加超时时间
            verify=True  # 明确启用SSL验证
        )
        
        logger.debug(f'响应状态码: {response.status_code}')
        logger.debug(f'响应头: {dict(response.headers)}')
        
        response.raise_for_status()  # 抛出HTTP错误
        result = response.json()
        logger.debug(f'token响应: {json.dumps(result, ensure_ascii=False)}')
        
        if result.get('code') != 0:
            logger.error(f'获取token失败: {result.get("msg")} (错误码: {result.get("code")})')
            return None
        
        return result.get('tenant_access_token')
    except requests.exceptions.SSLError as e:
        logger.error(f'SSL连接错误: {str(e)}')
        logger.error('尝试使用不验证SSL的方式重新连接...')
        try:
            response = session.post(
                url, 
                headers=headers, 
                json=data, 
                timeout=30,
                verify=False  # 禁用SSL验证作为备选方案
            )
            response.raise_for_status()
            result = response.json()
            if result.get('code') != 0:
                logger.error(f'获取token失败: {result.get("msg")} (错误码: {result.get("code")})')
                return None
            return result.get('tenant_access_token')
        except Exception as fallback_e:
            logger.error(f'备选方案也失败: {str(fallback_e)}')
            return None
    except requests.exceptions.ConnectionError as e:
        logger.error(f'连接错误: {str(e)}')
        logger.error('请检查网络连接或防火墙设置')
        return None
    except requests.exceptions.Timeout as e:
        logger.error(f'请求超时: {str(e)}')
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f'网络请求异常: {str(e)}')
        logger.error(f'异常类型: {type(e).__name__}')
        return None
    finally:
        session.close()

# 获取表格数据
def get_sheet_data(sheet_token, access_token, max_retries=3):
    url = f'https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{sheet_token}/values/{SHEET_ID}!{CELL_RANGE}'  # 组合工作表ID和单元格范围
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    session = create_session()
    
    for retry in range(max_retries):
        try:
            logger.debug(f'请求表格数据: {url} (重试次数: {retry+1})')
            logger.debug(f'请求头: {headers}')
            
            response = session.get(
                url, 
                headers=headers, 
                timeout=30,  # 增加超时时间
                verify=True  # 明确启用SSL验证
            )
            
            logger.debug(f'响应状态码: {response.status_code}')
            logger.debug(f'响应头: {dict(response.headers)}')
            
            response.raise_for_status()
            result = response.json()
            logger.debug(f'表格数据响应: {json.dumps(result, ensure_ascii=False)[:200]}...')  # 截断长响应
            
            # 检查API错误码
            if result.get('code') != 0:
                logger.error(f'API错误: {result.get("msg")} (错误码: {result.get("code")})')
                if retry < max_retries - 1:
                    sleep(2)  # 重试前等待
                    continue
            # 处理表头与数据匹配
            if 'data' in result and 'valueRange' in result['data']:
                values = result['data']['valueRange'].get('values', [])
                if len(values) >= 1:
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
                    data_rows = values[1:]
                    # 仅保留最新一行数据
                    if data_rows:
                        latest_row = data_rows[-1]
                        formatted_data = {table_headers[i]: latest_row[i] if i < len(latest_row) else None for i in range(len(table_headers))}
                        session.close()
                        return formatted_data
                    logger.warning("未找到数据行")
            session.close()
            return None
        except requests.exceptions.SSLError as e:
            logger.error(f'SSL连接错误 (重试 {retry+1}/{max_retries}): {str(e)}')
            if retry < max_retries - 1:
                logger.error('尝试使用不验证SSL的方式重新连接...')
                try:
                    response = session.get(
                        url, 
                        headers=headers, 
                        timeout=30,
                        verify=False  # 禁用SSL验证作为备选方案
                    )
                    response.raise_for_status()
                    result = response.json()
                    if result.get('code') == 0:
                        # 处理数据...
                        if 'data' in result and 'valueRange' in result['data']:
                            values = result['data']['valueRange'].get('values', [])
                            if len(values) >= 1:
                                table_headers = values[0]
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
                                data_rows = values[1:]
                                if data_rows:
                                    latest_row = data_rows[-1]
                                    formatted_data = {table_headers[i]: latest_row[i] if i < len(latest_row) else None for i in range(len(table_headers))}
                                    session.close()
                                    return formatted_data
                        session.close()
                        return None
                except Exception as fallback_e:
                    logger.error(f'SSL备选方案失败: {str(fallback_e)}')
                sleep(2 ** retry)  # 指数退避
            else:
                break
        except requests.exceptions.ConnectionError as e:
            logger.error(f'连接错误 (重试 {retry+1}/{max_retries}): {str(e)}')
            if retry < max_retries - 1:
                sleep(2 ** retry)  # 指数退避
        except requests.exceptions.Timeout as e:
            logger.error(f'请求超时 (重试 {retry+1}/{max_retries}): {str(e)}')
            if retry < max_retries - 1:
                sleep(2 ** retry)  # 指数退避
        except requests.exceptions.RequestException as e:
            # 获取详细错误响应
            error_details = e.response.text if hasattr(e, 'response') and e.response else '无响应内容'
            logger.error(f'网络请求异常 (重试 {retry+1}/{max_retries}): {str(e)}')
            logger.error(f'异常类型: {type(e).__name__}')
            logger.error(f'API响应: {error_details}')
            if retry < max_retries - 1:
                sleep(2 ** retry)  # 指数退避
        except Exception as e:
            logger.error(f'未知错误 (重试 {retry+1}/{max_retries}): {str(e)}')
            if retry < max_retries - 1:
                sleep(2 ** retry)
    
    session.close()
    return None

def get_next_run_time():
    """计算下一次运行时间（每个小时的10分）"""
    now = datetime.datetime.now()
    target_minute = 10
    
    # 如果当前分钟已经过了10分，则下一个小时的10分
    if now.minute >= target_minute:
        next_hour = now.hour + 1
        # 处理跨天情况
        if next_hour >= 24:
            next_hour = 0
            next_time = now.replace(day=now.day + 1, hour=next_hour, minute=target_minute, second=0, microsecond=0)
        else:
            next_time = now.replace(hour=next_hour, minute=target_minute, second=0, microsecond=0)
    else:
        next_time = now.replace(minute=target_minute, second=0, microsecond=0)
    
    # 确保next_time在当前时间之后
    if next_time <= now:
        next_time += datetime.timedelta(days=1)
    
    return next_time

def fetch_and_process_data():
    """获取并处理表格数据"""
    # 获取访问令牌
    logger.info('开始获取访问令牌...')
    token = get_tenant_access_token(APP_ID, APP_SECRET)
    if not token:
        logger.error('获取访问令牌失败')
        return False

    # 获取表格数据（使用max_retries=3）
    logger.info('开始获取表格数据...')
    sheet_data = get_sheet_data(SHEET_TOKEN, token, max_retries=3)
    
    if not sheet_data:
        logger.error('表格数据获取失败')
        return False
    
    # 处理数据
    logger.debug(f'完整API响应: {json.dumps(sheet_data, indent=2, ensure_ascii=False)}')
    
    # 直接使用get_sheet_data返回的格式化数据
    if sheet_data:
        logger.info('成功获取表格数据')
        logger.info(f'最新数据行: {json.dumps(sheet_data, ensure_ascii=False)}')
        
        # 保存数据到JSON文件（保留最新两条）
        output_file = 'data/raw/feishu_sheet_data.json'
        try:
            # 读取现有数据
            existing_data = []
            if os.path.exists(output_file):
                with open(output_file, 'r', encoding='utf-8') as f:
                    try:
                        existing_data = json.load(f)
                        # 确保是数组结构
                        if not isinstance(existing_data, list):
                            existing_data = [existing_data]
                    except json.JSONDecodeError:
                        logger.warning("JSON文件格式错误，将创建新文件")
                        existing_data = []
            
            # 添加新数据并保留最新两条
            existing_data.append(sheet_data)
            if len(existing_data) > 2:
                existing_data = existing_data[-2:]
            
            # 写入更新后的数据
            # 确保目录存在
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, ensure_ascii=False, indent=2)
            # 验证文件内容
            if os.path.getsize(output_file) == 0:
                logger.error("生成的JSON文件为空，请检查数据获取逻辑")
            else:
                logger.info(f"成功生成JSON文件，大小: {os.path.getsize(output_file)} bytes")
            logger.info(f'数据已保存到 {output_file}，当前保留最新{len(existing_data)}条记录')
            
            # 调用数据加载器处理并写入CSV
            from feishu_data_loader import load_feishu_data
            load_feishu_data(file_path=output_file)
        except Exception as e:
            logger.error(f'保存JSON文件失败: {str(e)}')
            return False
    else:
        logger.warning('表格数据为空')
    
    return True

if __name__ == '__main__':
    # 立即执行一次
    logger.info('立即执行首次数据获取...')
    fetch_and_process_data()
    
    # 定时任务循环
    while True:
        next_run_time = get_next_run_time()
        now = datetime.datetime.now()
        wait_seconds = (next_run_time - now).total_seconds()
        logger.info(f'下次执行时间: {next_run_time.strftime("%Y-%m-%d %H:%M:%S")}, 等待 {int(wait_seconds)} 秒')
        
        # 等待到下次执行时间
        sleep(wait_seconds)
        
        # 执行任务
        logger.info('开始定时数据获取...')
        fetch_and_process_data()