"""
爬取论文，专利等。
其中谷歌驱动链接：
"""
import os
import time
from urllib.robotparser import RobotFileParser
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service

# 配置信息（请根据实际情况修改）
DOWNLOAD_DIR = "./downloads"  # 下载目录
CHROMEDRIVER_PATH = "chromedriver.exe"  # 你的chromedriver完整路径
robots_url = f"https://arxiv.org/robots.txt" # 爬虫协议网站
delay = 15 # 爬虫间隔时间
TARGET_URL = "https://arxiv.org/search/physics?query=123&searchtype=all&abstracts=show&order=-announced_date_first&size=50"  # 要爬取的目标网站
FILE_EXTENSIONS = ["pdf", "docx", "xlsx"]  # 支持的文件类型
# 创建下载目录
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def check_robots_txt(base_url: str) -> bool:
    """检查 robots.txt 是否允许爬取"""
    rp = RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
        if not rp.can_fetch("*", base_url):  # "*" 表示通用爬虫
            print(f"robots.txt 禁止爬取: {base_url}")
            return False
        print(f"robots.txt 允许爬取: {base_url}")
        return True
    except Exception as e:
        print(f"无法读取 robots.txt: {e}")
        return False


def setup_driver() -> webdriver.Chrome:
    """配置Chrome WebDriver"""
    chrome_options = webdriver.ChromeOptions()
    # 设置下载路径和自动下载行为
    prefs = {
        "download.default_directory": os.path.abspath(DOWNLOAD_DIR),
        "plugins.always_open_pdf_externally": True,  # 自动下载PDF
        "download.prompt_for_download": False,
    }
    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.add_argument('--ignore-certificate-errors')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    # chrome_options.add_argument('--headless')  # 无头模式（按需启用）

    # 使用本地chromedriver
    service = Service(executable_path=CHROMEDRIVER_PATH)
    return webdriver.Chrome(service=service, options=chrome_options)


def get_file_links(driver: webdriver.Chrome) -> list[str]:
    """获取容器内的所有指定类型的文件链接"""
    try:
        # 显式等待容器加载
        container = WebDriverWait(driver, 15).until(
            # 等待所用该类标签加载完整
            EC.presence_of_element_located((By.ID, "main-container"))
        )
        # 等待容器内的链接加载完成
        links = WebDriverWait(driver, 15).until(
            EC.presence_of_all_elements_located((By.CLASS_NAME, "list-title"))
        )
        # 查找所有链接并过滤支持的文件类型
        links = container.find_elements(By.TAG_NAME, "a") # 多种标签可以选择
        file_links = []
        for link in links:
            href = link.get_attribute("href")
            print(href)
            if href and any(ext in href.lower() for ext in FILE_EXTENSIONS):
                file_links.append(href)
        return file_links
    except Exception as e:
        print(f"获取链接失败: {e}")
        return []


def is_download_complete(download_dir: str, initial_files: set[str]) -> bool:
    """检查下载是否完成"""
    current_files = set(os.listdir(download_dir))
    new_files = current_files - initial_files
    return all(not file.endswith(".crdownload") for file in new_files)


def download_files(driver: webdriver.Chrome, file_links: list[str], delay: int = 0) -> None:
    """下载所有文件"""
    initial_files = set(os.listdir(DOWNLOAD_DIR))  # 记录初始文件列表
    for url in file_links:
        # 检查 robots.txt
        if not check_robots_txt(url):
            print("爬虫被禁止，退出程序。")
            continue
        try:
            # 检查是否已下载
            file_name = os.path.basename(urlparse(url).path)
            if os.path.exists(os.path.join(DOWNLOAD_DIR, file_name)):
                print(f"文件已存在，跳过下载: {file_name}")
                continue
            # 开始下载
            driver.get(url)
            print(f"正在下载: {url}")

            # 等待下载完成
            while not is_download_complete(DOWNLOAD_DIR, initial_files):
                time.sleep(1)
            print(f"下载成功: {file_name}")
            time.sleep(delay)
        except Exception as e:
            print(f"下载失败: {url} - {e}")


def cleanup_temp_files(download_dir: str) -> None:
    """清理未完成的下载文件"""
    for file in os.listdir(download_dir):
        if file.endswith(".crdownload"):
            os.remove(os.path.join(download_dir, file))
            print(f"清理临时文件: {file}")


def main() -> None:
    # 初始化浏览器
    driver = setup_driver()
    try:
        # 访问目标页面
        driver.get(TARGET_URL)
        # 获取文件链接
        file_links = get_file_links(driver)
        if not file_links:
            print("未找到符合条件的文件")
            return
        # 下载文件
        print(f"找到 {len(file_links)} 个文件，开始下载...")
        download_files(driver, file_links, delay=delay)
    finally:
        # 清理临时文件
        cleanup_temp_files(DOWNLOAD_DIR)
        # 关闭浏览器
        driver.quit()


if __name__ == "__main__":
    main()