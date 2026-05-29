import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import threading
import time
import ctypes
import sys
import win32gui
import win32con
import win32api
from pynput import mouse, keyboard
import json
import os

# ==================== 1. 基础适配与权限提升 ====================
def fix_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    if not is_admin():
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        sys.exit()

fix_dpi_awareness()

# ==================== 2. 底层引擎 ====================
class BgEngine:
    @staticmethod
    def find_all_windows(title):
        """找出所有标题匹配的窗口，返回包含句柄、坐标、大小的列表"""
        matched_windows = []
        def callback(hwnd, extra):
            if win32gui.IsWindowVisible(hwnd) and title in win32gui.GetWindowText(hwnd):
                rect = win32gui.GetWindowRect(hwnd)
                matched_windows.append({
                    'hwnd': hwnd,
                    'title': win32gui.GetWindowText(hwnd),
                    'rect': rect # (左, 上, 右, 下)
                })
        win32gui.EnumWindows(callback, None)
        return matched_windows

    @staticmethod
    def find_window(title, index=0):
        """根据标题和索引获取特定窗口句柄"""
        all_windows = BgEngine.find_all_windows(title)
        if not all_windows:
            raise Exception(f"未找到标题包含 '{title}' 的窗口")
        if index >= len(all_windows):
            raise Exception(f"窗口索引超出范围，当前仅找到 {len(all_windows)} 个匹配窗口")
        return all_windows[index]['hwnd']

    @staticmethod
    def send_mouse_down(hwnd, x, y, btn='left'):
        lParam = win32api.MAKELONG(int(x), int(y))
        if btn == 'left':
            win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lParam)
        elif btn == 'right':
            win32gui.PostMessage(hwnd, win32con.WM_RBUTTONDOWN, win32con.MK_RBUTTON, lParam)

    @staticmethod
    def send_mouse_up(hwnd, x, y, btn='left'):
        lParam = win32api.MAKELONG(int(x), int(y))
        if btn == 'left':
            win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lParam)
        elif btn == 'right':
            win32gui.PostMessage(hwnd, win32con.WM_RBUTTONUP, 0, lParam)

    @staticmethod
    def send_key(hwnd, key_name):
        vk_map = {
            'enter': 0x0D, 'esc': 0x1B, 'space': 0x20, 'tab': 0x09,
            'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
            'backspace': 0x08, 'delete': 0x2E, 'home': 0x24, 'end': 0x23
        }
        if len(key_name) == 1 and key_name.isalnum():
            vk = ord(key_name.upper())
        else:
            vk = vk_map.get(key_name.lower(), None)
        if vk is None: return

        scan_code = win32api.MapVirtualKey(vk, 0)
        l_down = 1 | (scan_code << 16)
        l_up = 1 | (scan_code << 16) | (1 << 30) | (1 << 31)
        
        win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, l_down)
        time.sleep(0.03)
        win32gui.PostMessage(hwnd, win32con.WM_KEYUP, vk, l_up)

# ==================== 3. GUI 主程序 ====================
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Win11 后台自动化 Pro (多窗口识别版)")
        self.root.geometry("950x700")

        self.simple_tasks = [] 
        self.workflow = []     
        self.is_running = False 

        self._build_ui()
        self._bind_hotkeys() 
        self.load_tasks() 

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        if self.is_running:
            if not messagebox.askyesno("警告", "工作流正在运行，确定要强制退出吗？"):
                return
        self.save_tasks()
        self.root.destroy()

    def _bind_hotkeys(self):
        def on_press(key):
            try:
                if key == keyboard.Key.f5:
                    self.toggle_record()
                elif key == keyboard.Key.f6:
                    self.get_foreground_window()
            except:
                pass
        keyboard.Listener(on_press=on_press).start()

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use('clam')

        # --- 顶部：录制区 ---
        labelframe_rec = ttk.LabelFrame(self.root, text="1. 简单任务录制 (F5开始/停止 | F6获取当前窗口)", padding=10)
        labelframe_rec.pack(fill='x', padx=10, pady=5)

        row1 = ttk.Frame(labelframe_rec)
        row1.pack(fill='x', pady=2)
        ttk.Label(row1, text="窗口标题:", width=10).pack(side='left')
        self.entry_win_title = ttk.Entry(row1)
        self.entry_win_title.pack(side='left', fill='x', expand=True, padx=5)
        ttk.Button(row1, text="查找所有窗口", command=self.find_all_windows_ui).pack(side='left', padx=2)
        ttk.Button(row1, text="绑定并测试", command=self.test_bind).pack(side='left')

        row2 = ttk.Frame(labelframe_rec)
        row2.pack(fill='x', pady=2)
        ttk.Label(row2, text="任务名称:", width=10).pack(side='left')
        self.entry_task_name = ttk.Entry(row2)
        self.entry_task_name.pack(side='left', fill='x', expand=True, padx=5)
        self.btn_record = ttk.Button(row2, text="开始录制 (F5)", command=self.toggle_record)
        self.btn_record.pack(side='left', padx=5)

        # --- 中部：左右分栏 ---
        paned = ttk.PanedWindow(self.root, orient='horizontal')
        paned.pack(fill='both', expand=True, padx=10, pady=5)

        # 左侧：简单任务列表
        left_frame = ttk.Frame(paned, width=300)
        paned.add(left_frame, weight=1)

        ttk.Label(left_frame, text="已保存的简单任务 (右键重命名/删除)").pack(anchor='w')
        self.list_simple = tk.Listbox(left_frame, height=10)
        self.list_simple.pack(fill='both', expand=True, pady=5)
        self.list_simple.bind('<Double-Button-1>', lambda e: self.play_simple_task(self.list_simple.curselection()[0]))
        
        self.simple_menu = tk.Menu(self.root, tearoff=0)
        self.simple_menu.add_command(label="重命名任务", command=self.rename_simple_task)
        self.simple_menu.add_command(label="删除任务", command=self.delete_simple_task)
        self.list_simple.bind("<Button-3>", self.show_simple_menu)

        # 右侧：复杂工作流
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=2)

        wf_top = ttk.Frame(right_frame)
        wf_top.pack(fill='x', pady=5)
        ttk.Button(wf_top, text="+ 添加当前选中的简单任务", command=self.add_task_to_workflow).pack(side='left', padx=2)
        ttk.Button(wf_top, text="+ 添加独立延迟(秒)", command=self.add_delay_to_workflow).pack(side='left', padx=2)

        ttk.Label(right_frame, text="工作流队列 (双击任务可修改独立倍速)").pack(anchor='w')
        self.list_workflow = tk.Listbox(right_frame, height=15)
        self.list_workflow.pack(fill='both', expand=True, pady=5)
        self.list_workflow.bind('<Delete>', lambda e: self.remove_wf_item())
        self.list_workflow.bind('<Double-Button-1>', self.edit_wf_speed)

        wf_bottom = ttk.Frame(right_frame)
        wf_bottom.pack(fill='x')
        ttk.Button(wf_bottom, text="↑ 上移", command=lambda: self.move_wf_item(-1)).pack(side='left', expand=True, fill='x', padx=2)
        ttk.Button(wf_bottom, text="↓ 下移", command=lambda: self.move_wf_item(1)).pack(side='left', expand=True, fill='x', padx=2)
        ttk.Button(wf_bottom, text="删除 (Del)", command=self.remove_wf_item).pack(side='left', expand=True, fill='x', padx=2)

        # --- 底部：播放控制 ---
        bottom_frame = ttk.Frame(self.root)
        bottom_frame.pack(fill='x', padx=10, pady=10)

        ttk.Label(bottom_frame, text="循环次数:").pack(side='left')
        self.entry_loops = ttk.Entry(bottom_frame, width=5)
        self.entry_loops.insert(0, "1")
        self.entry_loops.pack(side='left', padx=5)

        ttk.Label(bottom_frame, text="全局速度(倍率):").pack(side='left')
        self.entry_speed = ttk.Entry(bottom_frame, width=5)
        self.entry_speed.insert(0, "1.0")
        self.entry_speed.pack(side='left', padx=5)

        self.btn_play_all = ttk.Button(bottom_frame, text="▶ 开始执行工作流", command=self.start_workflow_thread)
        self.btn_play_all.pack(side='left', padx=10)
        
        self.btn_stop_all = ttk.Button(bottom_frame, text="⏹ 停止工作流", command=self.stop_workflow, state='disabled')
        self.btn_stop_all.pack(side='left', padx=5)

        self.is_recording = False
        self.rec_actions = []
        self.rec_start_time = 0
        self.mouse_listener = None
        self.keyboard_listener = None

    # ==================== 存档与加载 ====================
    def save_tasks(self):
        data = {
            "simple_tasks": self.simple_tasks,
            "workflow": self.workflow
        }
        try:
            with open("automation_tasks.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"保存失败: {e}")

    def load_tasks(self):
        if os.path.exists("automation_tasks.json"):
            try:
                with open("automation_tasks.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.simple_tasks = data.get("simple_tasks", [])
                    self.workflow = data.get("workflow", [])
                    self.list_simple.delete(0, tk.END)
                    for task in self.simple_tasks:
                        self.list_simple.insert(tk.END, task['name'])
                    self.refresh_workflow_list()
            except Exception as e:
                print(f"加载存档失败: {e}")

    # ==================== 核心业务逻辑 ====================
    def find_all_windows_ui(self):
        """弹出界面让用户选择具体是哪个窗口"""
        title = self.entry_win_title.get()
        if not title:
            messagebox.showwarning("提示", "请先输入要查找的窗口标题")
            return
        
        windows = BgEngine.find_all_windows(title)
        if not windows:
            messagebox.showerror("错误", f"未找到标题包含 '{title}' 的任何窗口")
            return
        
        # 构建选择列表
        choices = []
        for i, w in enumerate(windows):
            rect = w['rect']
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            # 显示：索引 - 标题 - 屏幕位置及大小
            choices.append(f"{i} | 位置:({rect[0]},{rect[1]}) 大小:{width}x{height}")
        
        # 弹出选择框
        choice_win = tk.Toplevel(self.root)
        choice_win.title("请选择目标窗口")
        choice_win.geometry("400x200")
        choice_win.transient(self.root)
        choice_win.grab_set()
        
        ttk.Label(choice_win, text=f"找到 {len(windows)} 个匹配窗口，请双击选择：").pack(pady=10)
        
        listbox = tk.Listbox(choice_win, height=8)
        listbox.pack(fill='both', expand=True, padx=10)
        for c in choices:
            listbox.insert(tk.END, c)
        
        def on_select(event):
            sel = listbox.curselection()
            if sel:
                idx = sel[0]
                # 将选中的索引记录在 entry_win_title 的隐藏属性中
                self.entry_win_title.delete(0, tk.END)
                self.entry_win_title.insert(0, title)
                self.entry_win_title.window_index = idx 
                messagebox.showinfo("成功", f"已选定第 {idx} 个窗口！\n现在可以开始录制了。")
                choice_win.destroy()
        
        listbox.bind('<Double-Button-1>', on_select)

    def show_simple_menu(self, event):
        try:
            self.list_simple.selection_clear(0, tk.END)
            index = self.list_simple.nearest(event.y)
            self.list_simple.selection_set(index)
            self.simple_menu.post(event.x_root, event.y_root)
        except:
            pass

    def rename_simple_task(self):
        sel = self.list_simple.curselection()
        if not sel: return
        idx = sel[0]
        old_name = self.simple_tasks[idx]['name']
        new_name = simpledialog.askstring("重命名", "请输入新的任务名称:", initialvalue=old_name)
        if new_name:
            self.simple_tasks[idx]['name'] = new_name
            self.list_simple.delete(idx)
            self.list_simple.insert(idx, new_name)
            self.save_tasks()

    def get_foreground_window(self):
        try:
            hwnd = win32gui.GetForegroundWindow()
            if hwnd == 0: return
            title = win32gui.GetWindowText(hwnd)
            if title:
                self.entry_win_title.delete(0, tk.END)
                self.entry_win_title.insert(0, title)
                # 前台获取的窗口，索引默认为 0
                if hasattr(self.entry_win_title, 'window_index'):
                    del self.entry_win_title.window_index
                self.test_bind()
        except Exception as e:
            messagebox.showerror("错误", f"获取窗口失败: {str(e)}")

    def test_bind(self):
        title = self.entry_win_title.get()
        if not title: return
        # 获取用户选定的索引，默认为 0
        index = getattr(self.entry_win_title, 'window_index', 0)
        try:
            hwnd = BgEngine.find_window(title, index)
            rect = win32gui.GetClientRect(hwnd)
            msg = f"窗口句柄: {hwnd}\n客户区大小: {rect[2]}x{rect[3]}"
            if len(BgEngine.find_all_windows(title)) > 1:
                msg += f"\n(已锁定第 {index} 个同名窗口)"
            messagebox.showinfo("绑定成功", msg)
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def toggle_record(self):
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        title = self.entry_win_title.get()
        if not title:
            messagebox.showwarning("提示", "请先输入窗口标题并绑定")
            return
        
        # 录制时锁定窗口索引
        self.current_record_index = getattr(self.entry_win_title, 'window_index', 0)
        
        try:
            self.target_hwnd = BgEngine.find_window(title, self.current_record_index)
        except Exception as e:
            messagebox.showerror("错误", str(e))
            return

        self.is_recording = True
        self.rec_actions = []
        self.rec_start_time = time.time()
        self.btn_record.config(text="停止录制 (F5)")
        self.entry_win_title.config(state='disabled')

        rect = win32gui.GetClientRect(self.target_hwnd)
        x, y = 0, 0
        self.win_offset_x, self.win_offset_y = win32gui.ClientToScreen(self.target_hwnd, (x, y))

        def on_click(x, y, button, pressed):
            if not self.is_recording: return
            rel_x = x - self.win_offset_x
            rel_y = y - self.win_offset_y
            delay = round(time.time() - self.rec_start_time, 3)
            btn_str = 'left' if button == mouse.Button.left else 'right'
            action_type = 'press' if pressed else 'release'
            self.rec_actions.append({'t': action_type, 'd': delay, 'x': rel_x, 'y': rel_y, 'b': btn_str})
            self.rec_start_time = time.time()

        def on_press(key):
            if not self.is_recording: return
            if hasattr(key, 'vk') and key.vk == 116: return 
            try:
                k = key.char
            except AttributeError:
                k = str(key).split('.')[-1] 
            delay = round(time.time() - self.rec_start_time, 3)
            self.rec_actions.append({'t': 'key', 'd': delay, 'k': k})
            self.rec_start_time = time.time()

        self.mouse_listener = mouse.Listener(on_click=on_click)
        self.keyboard_listener = keyboard.Listener(on_press=on_press)
        self.mouse_listener.start()
        self.keyboard_listener.start()

    def stop_recording(self):
        self.is_recording = False
        if self.mouse_listener: self.mouse_listener.stop()
        if self.keyboard_listener: self.keyboard_listener.stop()
        self.btn_record.config(text="开始录制 (F5)")
        self.entry_win_title.config(state='normal')

        name = self.entry_task_name.get() or f"Task_{len(self.simple_tasks)+1}"
        task_data = {
            'name': name,
            'title': self.entry_win_title.get(),
            'window_index': self.current_record_index, # 保存窗口索引
            'actions': self.rec_actions
        }
        self.simple_tasks.append(task_data)
        self.list_simple.insert(tk.END, name)
        self.save_tasks()
        messagebox.showinfo("完成", f"任务 '{name}' 已保存，包含 {len(self.rec_actions)} 个动作。")

    def delete_simple_task(self):
        sel = self.list_simple.curselection()
        if not sel: return
        idx = sel[0]
        del self.simple_tasks[idx]
        self.list_simple.delete(idx)
        self.save_tasks()

    def play_simple_task(self, index):
        t = self.simple_tasks[index]
        threading.Thread(target=self._execute_actions, args=(t['title'], t['actions'], 1.0, t.get('window_index', 0)), daemon=True).start()

    # ==================== 工作流逻辑 ====================
    def add_task_to_workflow(self):
        sel = self.list_simple.curselection()
        if not sel:
            messagebox.showwarning("提示", "请在左侧选择一个简单任务")
            return
        idx = sel[0]
        self.workflow.append({'type': 'task', 'ref_id': idx, 'speed': 1.0})
        self.refresh_workflow_list()
        self.save_tasks()

    def add_delay_to_workflow(self):
        # 补全的添加延迟弹窗逻辑
        top = tk.Toplevel(self.root)
        top.title("设置延迟时间")
        top.geometry("250x120") 
        top.resizable(False, False)
        
        ttk.Label(top, text="请输入延迟秒数：").pack(pady=(15, 5))
        ent = ttk.Entry(top, width=15)
        ent.pack(pady=5)
        ent.focus_set()
        
        def ok():
            try:
                sec = float(ent.get())
                self.workflow.append({'type': 'delay', 'sec': sec})
                self.refresh_workflow_list()
                self.save_tasks()
                top.destroy()
            except:
                messagebox.showwarning("提示", "请输入有效的数字")
        ttk.Button(top, text="确认添加", command=ok).pack(pady=10)
    def edit_wf_speed(self, event):
        """双击修改工作流中任务的独立倍速"""
        sel = self.list_workflow.curselection()
        if not sel: return
        idx = sel[0]
        item = self.workflow[idx]
        
        if item['type'] == 'task':
            current_speed = item['speed']
            new_speed = simpledialog.askfloat("修改播放速度", "请输入该任务的独立播放倍率 (例如 0.5 或 2.0):", initialvalue=current_speed)
            if new_speed and new_speed > 0:
                self.workflow[idx]['speed'] = new_speed
                self.refresh_workflow_list()
                self.save_tasks()

    def remove_wf_item(self):
        sel = self.list_workflow.curselection()
        if not sel: return
        idx = sel[0]
        del self.workflow[idx]
        self.refresh_workflow_list()
        self.save_tasks()

    def move_wf_item(self, direction):
        sel = self.list_workflow.curselection()
        if not sel: return
        idx = sel[0]
        new_idx = idx + direction
        if 0 <= new_idx < len(self.workflow):
            self.workflow[idx], self.workflow[new_idx] = self.workflow[new_idx], self.workflow[idx]
            self.refresh_workflow_list()
            self.save_tasks()

    def refresh_workflow_list(self):
        self.list_workflow.delete(0, tk.END)
        for i, item in enumerate(self.workflow):
            if item['type'] == 'task':
                task_name = self.simple_tasks[item['ref_id']]['name']
                speed = item['speed']
                text = f"[任务] {task_name} (速度: {speed}x)"
            else:
                text = f"[延迟] {item['sec']} 秒"
            self.list_workflow.insert(tk.END, text)

    # ==================== 播放与控制逻辑 ====================
    def start_workflow_thread(self):
        if not self.workflow:
            messagebox.showwarning("提示", "工作流队列为空，请先添加任务！")
            return
        threading.Thread(target=self.run_workflow, daemon=True).start()

    def stop_workflow(self):
        self.is_running = False
        self.btn_play_all.config(state='normal')
        self.btn_stop_all.config(state='disabled')

    def run_workflow(self):
        self.is_running = True
        self.btn_play_all.config(state='disabled')
        self.btn_stop_all.config(state='normal')
        
        try:
            loops = int(self.entry_loops.get())
            global_speed = float(self.entry_speed.get())
        except:
            messagebox.showerror("错误", "循环次数或全局速度格式不正确")
            self.stop_workflow()
            return

        for _ in range(loops):
            if not self.is_running: break
            
            for item in self.workflow:
                if not self.is_running: break
                
                if item['type'] == 'delay':
                    time.sleep(item['sec'])
                elif item['type'] == 'task':
                    task = self.simple_tasks[item['ref_id']]
                    # 最终速度 = 全局速度 * 独立速度
                    final_speed = global_speed * item['speed']
                    self._execute_actions(task['title'], task['actions'], final_speed, task.get('window_index', 0))
        
        self.stop_workflow()

    def _execute_actions(self, title, actions, speed, window_index=0):
        """核心动作执行引擎"""
        try:
            hwnd = BgEngine.find_window(title, window_index)
        except Exception as e:
            print(f"执行任务失败：{e}")
            return

        for action in actions:
            if not self.is_running: return
            
            # 根据倍速计算实际延迟时间
            delay = action['d'] / speed
            if delay > 0:
                time.sleep(delay)
            
            if action['t'] == 'press':
                BgEngine.send_mouse_down(hwnd, action['x'], action['y'], action['b'])
            elif action['t'] == 'release':
                BgEngine.send_mouse_up(hwnd, action['x'], action['y'], action['b'])
            elif action['t'] == 'key':
                BgEngine.send_key(hwnd, action['k'])

# ==================== 程序启动入口 ====================
if __name__ == "__main__":
    run_as_admin() # 自动获取管理员权限，确保后台消息能发送成功
    root = tk.Tk()
    app = App(root)
    root.mainloop()