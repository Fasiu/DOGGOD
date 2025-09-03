#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import requests
import json
import keyboard
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel,
                             QTextEdit, QVBoxLayout, QHBoxLayout, QSystemTrayIcon,
                             QMenu, QAction, QStyle, QLineEdit, QPushButton, QDialog, QComboBox,
                             QScrollArea, QSizeGrip, QFrame)
from PyQt5.QtCore import Qt, QPoint, pyqtSignal, QThread, QTimer, QSize, QRect
from PyQt5.QtGui import QIcon, QFont, QCursor, QTextCursor, QMouseEvent


class StreamingAPICallThread(QThread):
    """用于在后台流式调用API的线程"""
    result_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, url, method="POST", data=None, headers=None):
        super().__init__()
        self.url = url
        self.method = method
        self.data = data
        self.headers = headers

    def run(self):
        try:
            # 调试信息
            print(f"Request URL: {self.url}")
            print(f"Request Method: {self.method}")
            print(f"Request Headers: {self.headers}")
            print(f"Request Data: {self.data}")

            # 启用流式输出
            if self.data and isinstance(self.data, dict):
                self.data["stream"] = True

            # 发送请求，使用流式模式
            if self.method == "GET":
                response = requests.get(self.url, headers=self.headers, stream=True)
            elif self.method == "POST":
                response = requests.post(self.url, json=self.data, headers=self.headers, stream=True)
            else:
                raise ValueError(f"Unsupported HTTP method: {self.method}")

            print(f"Response Status: {response.status_code}")

            if response.status_code != 200:
                error_msg = f"HTTP Error: {response.status_code}, Response: {response.text}"
                print(error_msg)
                self.error_signal.emit(error_msg)
                return

            # ✅ 关键：不要用 decode_unicode=True，我们自己控制 UTF-8 解码
            for line in response.iter_lines():
                if not line:
                    continue

                # ✅ 手动以 UTF-8 解码原始字节
                try:
                    line_str = line.decode('utf-8').strip()
                except Exception as e:
                    print(f"Decode error: {e}, raw line: {line}")
                    continue

                print(f"Raw line: {line_str}")  # 调试输出

                if line_str.startswith("data: "):
                    json_text = line_str[6:].strip()
                elif line_str.startswith("data:"):
                    json_text = line_str[5:].strip()
                else:
                    continue  # 忽略其他类型

                if json_text == "[DONE]":
                    print("Stream ended.")
                    break

                try:
                    data = json.loads(json_text)
                    print(f"Parsed data: {data}")

                    # 提取 content 流
                    if "choices" in data and len(data["choices"]) > 0:
                        delta = data["choices"][0].get("delta", {})
                        if "content" in delta and delta["content"] is not None:
                            self.result_signal.emit(delta["content"])

                except json.JSONDecodeError as e:
                    print(f"JSON decode error: {e}, raw json text: {json_text}")
                    continue

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            print(error_msg)
            self.error_signal.emit(error_msg)
        finally:
            self.finished_signal.emit()


class SettingsDialog(QDialog):
    """设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setFixedSize(400, 500)

        layout = QVBoxLayout()

        # API设置
        api_group = QVBoxLayout()
        api_group.addWidget(QLabel("API URL:"))
        self.api_url = QLineEdit()
        api_group.addWidget(self.api_url)

        api_group.addWidget(QLabel("Method:"))
        self.method_combo = QComboBox()
        self.method_combo.addItems(["GET", "POST"])
        api_group.addWidget(self.method_combo)

        api_group.addWidget(QLabel("Headers (JSON):"))
        self.headers_edit = QTextEdit()
        self.headers_edit.setMaximumHeight(60)
        api_group.addWidget(self.headers_edit)

        api_group.addWidget(QLabel("Data (JSON):"))
        self.data_edit = QTextEdit()
        self.data_edit.setMaximumHeight(60)
        api_group.addWidget(self.data_edit)

        layout.addLayout(api_group)

        # 快捷键设置
        shortcut_group = QVBoxLayout()
        shortcut_group.addWidget(QLabel("快捷键:"))
        self.shortcut_edit = QLineEdit()
        shortcut_group.addWidget(self.shortcut_edit)

        layout.addLayout(shortcut_group)

        # 按钮
        button_layout = QHBoxLayout()
        save_btn = QPushButton("保存")
        cancel_btn = QPushButton("取消")
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)
        self.setLayout(layout)

        # 连接信号
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)


class MessageWidget(QWidget):
    """单个消息部件"""

    def __init__(self, text, is_user=True, parent=None):
        super().__init__(parent)
        self.initUI(text, is_user)

    def initUI(self, text, is_user):
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 5, 10, 5)

        message_label = QLabel(text)
        message_label.setWordWrap(True)
        message_label.setStyleSheet(f"""
            QLabel {{
                background-color: {'#e6f7ff' if not is_user else '#f0f0f0'};
                color: black;
                padding: 8px;
                border-radius: 8px;
                border: 1px solid {'#91d5ff' if not is_user else '#d9d9d9'};
            }}
        """)
        message_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        if is_user:
            layout.addStretch()
            layout.addWidget(message_label)
        else:
            layout.addWidget(message_label)
            layout.addStretch()

        self.setLayout(layout)


class ResizableFloatingWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.minimum_size = QSize(400, 300)
        self.initUI()
        self.initTray()
        self.initHotkeys()

        # 存储设置
        self.api_url = "http://mlops.huawei.com/mlops-service/api/v1/agentService/v1/chat/completions"
        self.method = "POST"
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer sk-eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJkZXBhcnRtZW50TmFtZSI6IuWuieWFqOino-WGs-aWueahiOW8gOWPkemDqCIsImFjY291bnRJZCI6ImgzMDA2OTEwNCIsImtleVZlcnNpb24iOiIyLjAiLCJhY2NvdW50TmFtZSI6Imh1ZmFuZ3h1IiwidGVuYW50SWQiOiJlMzYyNmQzMTE0YmI5ZjY1OWQ0ZTE3NTkwY2ZjNDUzNSJ9._THTS4W34ksFru1JXdgZWbVuScQhOiM8mX8NnT5Y-wI'
        }
        self.data = {
            "stream": True,
            "model": "qwen3-235b",
            "messages": []
        }
        self.hotkey = "ctrl+alt+a"

        # 对话历史
        self.conversation = []
        self.current_bot_response = ""
        self.current_response_widget = None

        # 窗口大小调整相关
        self.dragging = False
        self.resizing = False
        self.drag_position = QPoint()
        self.resize_edge = None
        self.margin = 8

    def initUI(self):
        # 设置窗口属性
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(self.minimum_size)

        # 中心部件
        central_widget = QWidget()
        central_widget.setStyleSheet("""
            QWidget {
                background-color: rgba(50, 50, 50, 200);
                border-radius: 10px;
                border: 1px solid gray;
            }
        """)
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # 标题栏
        title_bar = QWidget()
        title_bar.setFixedHeight(25)
        title_bar.setStyleSheet(
            "background-color: rgba(30, 30, 30, 200); border-top-left-radius: 10px; border-top-right-radius: 10px;")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(5, 0, 5, 0)

        self.title_label = QLabel("AI 对话助手")
        self.title_label.setStyleSheet("color: white;")
        title_layout.addWidget(self.title_label)

        close_btn = QPushButton("×")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet(
            "QPushButton { color: white; border: none; } QPushButton:hover { background-color: rgba(255, 100, 100, 150); }")
        close_btn.clicked.connect(self.hideWindow)
        title_layout.addWidget(close_btn)

        main_layout.addWidget(title_bar)

        # 对话区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: rgba(255, 255, 255, 200);
                border: none;
                border-radius: 5px;
            }
        """)

        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.addStretch()

        self.scroll_area.setWidget(self.chat_container)
        main_layout.addWidget(self.scroll_area)

        # 输入区域
        input_widget = QWidget()
        input_widget.setStyleSheet("""
            QWidget {
                background-color: white;
                border-radius: 5px;
            }
        """)
        input_layout = QHBoxLayout(input_widget)
        input_layout.setContentsMargins(5, 5, 5, 5)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入您的问题...")
        self.input_field.setStyleSheet("""
            QLineEdit {
                background-color: white;
                color: black;
                border: 1px solid #d9d9d9;
                border-radius: 3px;
                padding: 5px;
            }
            QLineEdit:focus {
                border: 1px solid #1890ff;
            }
        """)
        self.input_field.returnPressed.connect(self.sendMessage)
        input_layout.addWidget(self.input_field)

        send_btn = QPushButton("发送")
        send_btn.setStyleSheet("""
            QPushButton {
                background-color: #1890ff;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 5px 10px;
                margin-left: 5px;
            }
            QPushButton:hover {
                background-color: #40a9ff;
            }
        """)
        send_btn.clicked.connect(self.sendMessage)
        input_layout.addWidget(send_btn)

        clear_btn = QPushButton("清空")
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #f5222d;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 5px 10px;
                margin-left: 5px;
            }
            QPushButton:hover {
                background-color: #ff4d4f;
            }
        """)
        clear_btn.clicked.connect(self.clearConversation)
        input_layout.addWidget(clear_btn)

        main_layout.addWidget(input_widget)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.pos()

            # 检查是否在标题栏区域（用于拖动）
            title_bar_rect = QRect(5, 5, self.width() - 10, 20)  # 稍微宽松的标题栏检测
            if title_bar_rect.contains(pos):
                self.dragging = True
                self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
                event.accept()
                return

            # 检查是否在边缘区域（用于调整大小）
            edge = self.getEdgeAt(pos)

            if edge:
                self.resizing = True
                self.resize_edge = edge
                self.resize_start_pos = event.globalPos()
                self.resize_start_geometry = self.geometry()
                event.accept()
                return

    def getEdgeAt(self, pos):
        """获取鼠标位置对应的边缘 - 使用窗口几何位置"""
        # 使用窗口的实际几何位置进行边缘检测
        rect = QRect(0, 0, self.width(), self.height())
        margin = 10  # 边缘检测区域

        # 检查角落
        if pos.x() <= margin and pos.y() <= margin:
            return 'top left'
        elif pos.x() >= rect.width() - margin and pos.y() <= margin:
            return 'top right'
        elif pos.x() <= margin and pos.y() >= rect.height() - margin:
            return 'bottom left'
        elif pos.x() >= rect.width() - margin and pos.y() >= rect.height() - margin:
            return 'bottom right'

        # 检查边缘
        elif pos.x() <= margin:
            return 'left'
        elif pos.x() >= rect.width() - margin:
            return 'right'
        elif pos.y() <= margin:
            return 'top'
        elif pos.y() >= rect.height() - margin:
            return 'bottom'

        return None

    def mouseMoveEvent(self, event):
        pos = event.pos()

        # 实时更新光标形状（即使没有按下鼠标）
        edge = self.getEdgeAt(pos)
        if edge:
            self.updateCursor(edge)
        else:
            self.unsetCursor()

        # 处理拖动
        if event.buttons() == Qt.LeftButton and self.dragging:
            self.move(event.globalPos() - self.drag_position)
            event.accept()
            return

        # 处理调整大小
        if event.buttons() == Qt.LeftButton and self.resizing and self.resize_edge:
            global_pos = event.globalPos()

            # 直接使用当前鼠标位置来计算新的几何形状
            new_geom = self.geometry()

            if 'left' in self.resize_edge:
                new_geom.setLeft(global_pos.x())
            if 'right' in self.resize_edge:
                new_geom.setRight(global_pos.x())
            if 'top' in self.resize_edge:
                new_geom.setTop(global_pos.y())
            if 'bottom' in self.resize_edge:
                new_geom.setBottom(global_pos.y())

            # 确保最小尺寸
            min_width = max(100, self.minimum_size.width())
            min_height = max(60, self.minimum_size.height())

            if new_geom.width() < min_width:
                if 'left' in self.resize_edge:
                    new_geom.setLeft(new_geom.right() - min_width)
                else:
                    new_geom.setRight(new_geom.left() + min_width)

            if new_geom.height() < min_height:
                if 'top' in self.resize_edge:
                    new_geom.setTop(new_geom.bottom() - min_height)
                else:
                    new_geom.setBottom(new_geom.top() + min_height)

            self.setGeometry(new_geom)

            # 更新起始位置，确保连续调整大小
            self.resize_start_pos = global_pos
            self.resize_start_geometry = new_geom

            event.accept()
            return

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False
            self.resizing = False
            self.resize_edge = None
            self.unsetCursor()

            # 鼠标释放后也需要更新光标状态
            pos = self.mapFromGlobal(QCursor.pos())
            edge = self.getEdgeAt(pos)
            if edge:
                self.updateCursor(edge)

    def updateCursor(self, edge):
        """根据边缘更新光标"""
        cursors = {
            'left': Qt.SizeHorCursor,
            'right': Qt.SizeHorCursor,
            'top': Qt.SizeVerCursor,
            'bottom': Qt.SizeVerCursor,
            'top left': Qt.SizeFDiagCursor,
            'top right': Qt.SizeBDiagCursor,
            'bottom left': Qt.SizeBDiagCursor,
            'bottom right': Qt.SizeFDiagCursor
        }
        self.setCursor(cursors.get(edge, Qt.ArrowCursor))

    def enterEvent(self, event):
        """鼠标进入窗口时更新光标"""
        pos = self.mapFromGlobal(QCursor.pos())
        edge = self.getEdgeAt(pos)
        if edge:
            self.updateCursor(edge)
        else:
            self.unsetCursor()

    def leaveEvent(self, event):
        """鼠标离开窗口时恢复默认光标"""
        self.unsetCursor()

    def initTray(self):
        # 创建系统托盘图标
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))

        # 创建托盘菜单
        tray_menu = QMenu()

        show_action = QAction("显示", self)
        show_action.triggered.connect(self.show)
        tray_menu.addAction(show_action)

        settings_action = QAction("设置", self)
        settings_action.triggered.connect(self.showSettings)
        tray_menu.addAction(settings_action)

        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.quitApp)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        self.tray_icon.activated.connect(self.trayIconActivated)

    def initHotkeys(self):
        # 初始化快捷键
        try:
            keyboard.add_hotkey('ctrl+alt+a', self.focusInput)
        except Exception as e:
            print(f"Failed to register hotkey: {e}")

    def focusInput(self):
        """聚焦到输入框"""
        self.show()
        self.raise_()
        self.activateWindow()
        self.input_field.setFocus()

    def sendMessage(self):
        """发送用户消息"""
        user_message = self.input_field.text().strip()
        if not user_message:
            return

        self.input_field.clear()

        # 添加用户消息到对话
        self.addMessage(user_message, is_user=True)

        # 更新API请求数据
        self.data["messages"].append({"role": "user", "content": user_message})

        # 调用API
        self.callAPI()

    def addMessage(self, text, is_user=True):
        """添加消息到对话区域"""
        message_widget = MessageWidget(text, is_user)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, message_widget)

        # 如果不是用户消息，保存引用以便更新
        if not is_user:
            self.current_response_widget = message_widget

        # 滚动到底部
        QTimer.singleShot(100, self.scrollToBottom)

    def updateBotResponse(self, content):
        """更新机器人的回复（流式）"""
        if not self.current_response_widget:
            # 创建新的机器人回复部件
            self.addMessage(content, is_user=False)
        else:
            # 更新现有的机器人回复部件
            for i in range(self.chat_layout.count()):
                widget = self.chat_layout.itemAt(i).widget()
                if widget == self.current_response_widget:
                    # 找到消息标签并更新文本
                    label = widget.findChild(QLabel)
                    if label:
                        label.setText(label.text() + content)
                    break

        # 滚动到底部
        QTimer.singleShot(100, self.scrollToBottom)

    def scrollToBottom(self):
        """滚动到底部"""
        self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        )

    def callAPI(self):
        """调用API并更新显示"""
        # 创建并启动API调用线程
        self.api_thread = StreamingAPICallThread(self.api_url, self.method, self.data, self.headers)
        self.api_thread.result_signal.connect(self.updateBotResponse)
        self.api_thread.error_signal.connect(self.handleAPIError)
        self.api_thread.finished_signal.connect(self.finishResponse)
        self.api_thread.start()

        # 重置当前响应状态
        self.current_bot_response = ""
        self.current_response_widget = None

    def finishResponse(self):
        """完成响应，保存到对话历史"""
        if self.current_response_widget:
            # 获取完整的响应文本
            for i in range(self.chat_layout.count()):
                widget = self.chat_layout.itemAt(i).widget()
                if widget == self.current_response_widget:
                    label = widget.findChild(QLabel)
                    if label:
                        full_response = label.text()
                        self.data["messages"].append({"role": "assistant", "content": full_response})
                    break

            self.current_response_widget = None

    def handleAPIError(self, error):
        """处理API调用错误"""
        self.addMessage(f"错误: {error}", is_user=False)

    def clearConversation(self):
        """清空对话"""
        # 清空UI
        while self.chat_layout.count():
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.chat_layout.addStretch()

        # 清空对话历史
        self.conversation = []
        self.data["messages"] = []

        # 重置状态
        self.current_bot_response = ""
        self.current_response_widget = None

    def showSettings(self):
        """显示设置对话框"""
        dialog = SettingsDialog(self)
        dialog.api_url.setText(self.api_url)
        dialog.method_combo.setCurrentText(self.method)
        dialog.headers_edit.setPlainText(json.dumps(self.headers, indent=2))
        dialog.data_edit.setPlainText(json.dumps(self.data, indent=2))
        dialog.shortcut_edit.setText(self.hotkey)

        if dialog.exec_() == QDialog.Accepted:
            # 保存设置
            self.api_url = dialog.api_url.text()
            self.method = dialog.method_combo.currentText()

            try:
                self.headers = json.loads(
                    dialog.headers_edit.toPlainText()) if dialog.headers_edit.toPlainText() else {}
            except:
                self.headers = {}

            try:
                new_data = json.loads(dialog.data_edit.toPlainText()) if dialog.data_edit.toPlainText() else {}
                # 保留现有的消息历史
                if "messages" in new_data:
                    self.data["messages"] = new_data["messages"]
                # 更新其他字段
                for key in new_data:
                    if key != "messages":
                        self.data[key] = new_data[key]
            except:
                pass

            # 重新注册快捷键
            try:
                keyboard.unregister_all_hotkeys()
                keyboard.add_hotkey(dialog.shortcut_edit.text(), self.focusInput)
                self.hotkey = dialog.shortcut_edit.text()
            except Exception as e:
                print(f"Failed to register hotkey: {e}")

    def trayIconActivated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            if self.isVisible():
                self.hide()
            else:
                self.show()

    def hideWindow(self):
        self.hide()

    def quitApp(self):
        self.tray_icon.hide()
        QApplication.quit()

    def closeEvent(self, event):
        event.ignore()
        self.hide()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 9))
    window = ResizableFloatingWindow()
    window.show()
    sys.exit(app.exec_())
