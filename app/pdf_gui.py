# SPDX-License-Identifier: AGPL-3.0-or-later
"""Native Windows GUI for the isolated pdf2zh_next + Codex workflow."""
import argparse
import datetime
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from runtime import ROOT, CODEX_HOME, CODE_ROOT, PROJECT_ROOT, OUTPUT_ROOT, prepare_environment, translation_profile, open_file
from model_catalog import fetch_models, load_cached_models, save_translation_selection

SETTINGS = ROOT / 'config' / 'gui-settings.json'
HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def validate_pages(text, page_count):
    normalized = re.sub(r'\s+', '', text.replace('，', ',').replace('、', ',').replace('–', '-'))
    if not normalized:
        raise ValueError('请填写原文页码，例如 1-3 或 1,3,5-7。')
    for item in normalized.split(','):
        if re.fullmatch(r'\d+', item):
            start = end = int(item)
        elif re.fullmatch(r'\d*-\d*', item) and item != '-':
            lo, hi = item.split('-')
            start, end = int(lo) if lo else 1, int(hi) if hi else page_count
        else:
            raise ValueError('页码格式不正确，请使用 1-3 或 1,3,5-7。')
        if start < 1 or end < start or end > page_count:
            raise ValueError(f'页码超出范围或顺序不正确。当前 PDF 共 {page_count} 页。')
    return normalized


def validate_output_directory(text):
    path = Path(text.strip().strip('"') or str(OUTPUT_ROOT)).resolve()
    if path.exists() and not path.is_dir():
        raise ValueError('保存位置应为文件夹。')
    return path


def build_command(pdf, only_pages, pages, remove_numbers, output_directory=None, output_chinese=True, output_bilingual=False):
    if not (output_chinese or output_bilingual):
        raise ValueError('请至少选择一种生成文件：纯中文 PDF 或中英对照 PDF。')
    mode = 'both' if output_chinese and output_bilingual else ('chinese' if output_chinese else 'bilingual')
    path = Path(pdf.strip().strip('"')).expanduser()
    if not path.is_file() or path.suffix.lower() != '.pdf':
        raise ValueError('请先选择一个存在的 PDF 文件。')
    import fitz
    with fitz.open(path) as document:
        if document.needs_pass:
            raise ValueError('这个 PDF 有密码保护，请先解锁后再翻译。')
        page_count = len(document)
    if page_count < 1:
        raise ValueError('这个 PDF 没有可翻译的页面。')
    command = [sys.executable, str(CODE_ROOT / 'translate_pdf.py'), str(path.resolve())]
    command += ['--output-mode', mode]
    if only_pages:
        command += ['--pages', validate_pages(pages, page_count)]
    if remove_numbers:
        command.append('--remove-line-numbers')
    if output_directory is not None:
        command += ['--output-dir', str(validate_output_directory(output_directory))]
    return command


def inside_outputs(path):
    try:
        return Path(path).is_absolute()
    except (ValueError, OSError):
        return False


def localize_login_line(line):
    """Localize known CLI notices, preserving URLs and unknown diagnostics verbatim."""
    prefix = 'Starting local login server on '
    if line.startswith(prefix):
        return '正在启动本机登录回调服务：' + line[len(prefix):]
    messages = {
        'If your browser did not open, navigate to this URL to authenticate:':
            '如果浏览器未自动打开，请访问下面的链接完成登录授权：',
        'On a remote or headless machine? Use `codex login --device-auth` instead.':
            '在远程或无图形界面的电脑上，可改用设备码登录：codex login --device-auth。',
        'Operation failed. Read the message above.':
            '本次操作未完成，请查看上方提示。',
        'Successfully logged in':
            '浏览器授权已完成，正在验证登录信息。',
    }
    return messages.get(line, line)


def has_chatgpt_session():
    """Read local login presence without printing credentials or calling the network."""
    try:
        auth = json.loads((CODEX_HOME / 'auth.json').read_text(encoding='utf-8-sig'))
        tokens = auth.get('tokens')
        return auth.get('auth_mode') == 'chatgpt' and isinstance(tokens, dict) and bool(tokens.get('access_token'))
    except (OSError, ValueError, AttributeError):
        return False


def checkbox_images(window):
    """Draw our own tick indicators; clam's built-in indicator uses a cross."""
    size = max(16, round(16 * float(window.tk.call('tk', 'scaling')) / (96 / 72)))
    images = []
    for selected, disabled in [(False, False), (True, False), (False, True), (True, True)]:
        image = tk.PhotoImage(master=window, width=size+6, height=size)
        border = '#087f8c' if selected else '#ccd7e2'
        background = '#087f8c' if selected else '#f8fafc'
        if disabled:
            border, background = '#becbd6', '#c5d8db' if selected else '#edf1f5'
        image.put(border, to=(0, 0, size, size))
        image.put(background, to=(1, 1, size-1, size-1))
        if selected:
            points = [(round(size*.22), round(size*.51)), (round(size*.43), round(size*.72)), (round(size*.79), round(size*.29))]
            for (x1,y1),(x2,y2) in zip(points,points[1:]):
                steps = max(abs(x2-x1), abs(y2-y1))
                for step in range(steps+1):
                    x=round(x1+(x2-x1)*step/steps)
                    y=round(y1+(y2-y1)*step/steps)
                    radius=max(1,round(size/18))
                    image.put('white',to=(max(1,x-radius),max(1,y-radius),min(size-1,x+radius+1),min(size-1,y+radius+1)))
        images.append(image)
    return images


class TranslationWindow:
    def __init__(self, window, initial_pdf='', initial_pages='', remove_numbers=False, initial_output='', refresh_catalog=True):
        self.window = window
        self.events = queue.Queue()
        self.process = None
        self.cancel_requested = threading.Event()
        self.busy = False
        self.close_when_done = False
        self.destination = None
        self.final_pdf = None
        self.gui_log = None
        self.started_at = None
        self.running_command = None
        self.running_settings = None
        self.paused_command = None
        self.paused_settings = None
        self.models = []
        self.catalog_loading = False
        self.login_in_progress = False
        self.login_process = None
        self.login_cancel_requested = threading.Event()
        self.login_cancel_file = None
        profile, _ = translation_profile()
        self.model = tk.StringVar(value='' if profile['model']=='default' else profile['model'])
        self.reasoning_effort = tk.StringVar(value=profile['model_reasoning_effort'])
        self.catalog_status = tk.StringVar(value='等待获取官方列表')
        preferences = {}
        try:
            preferences = json.loads(SETTINGS.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
        self.last_pdf_directory = preferences.get('last_pdf_directory', '')
        self.pdf = tk.StringVar(value=initial_pdf)
        self.output_directory = tk.StringVar(value=initial_output or preferences.get('output_directory', str(OUTPUT_ROOT)))
        self.only_pages = tk.BooleanVar(value=bool(initial_pages) or preferences.get('only_pages', False))
        self.pages = tk.StringVar(value=initial_pages or preferences.get('pages', '1-3'))
        self.remove_numbers = tk.BooleanVar(value=remove_numbers or preferences.get('remove_numbers', False))
        self.output_chinese = tk.BooleanVar(value=preferences.get('output_chinese', True))
        self.output_bilingual = tk.BooleanVar(value=preferences.get('output_bilingual', False))
        self.open_finished = tk.BooleanVar(value=preferences.get('open_finished', True))
        self.remember = tk.BooleanVar(value=preferences.get('remember', True))
        self.status = tk.StringVar(value='等待选择 PDF')
        self.elapsed = tk.StringVar(value='')
        self.details = tk.StringVar(value='选择英文 PDF 后，点击“开始翻译”。')
        self._build()
        cached = load_cached_models()
        if cached:
            self.apply_catalog(cached, cached=True)
        if refresh_catalog:
            self.window.after(200, self.refresh_models)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.after(150, self.poll)
        if initial_pdf:
            self.inspect_file()

    def _build(self):
        w = self.window
        w.title('pdf2zh-viacodex · 论文 PDF 翻译')
        work_left, work_top = 0, 0
        work_width, work_height = w.winfo_screenwidth(), w.winfo_screenheight() - 48
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            area = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0):
                work_left, work_top = area.left, area.top
                work_width, work_height = area.right - area.left, area.bottom - area.top
        height = min(920, work_height - 64)
        width = min(1160, work_width - 32)
        x = work_left + max(0, (work_width - width) // 2)
        w.geometry(f'{width}x{height}+{x}+{work_top + 8}')
        w.minsize(860, min(820, height))
        w.configure(bg='#f3f6fa')
        style = ttk.Style(w)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10), background='#f3f6fa', foreground='#162b3d')
        style.configure('Card.TFrame', background='white')
        style.configure('Card.TLabel', background='white')
        style.configure('Section.TLabel', background='white', font=('Microsoft YaHei UI', 12, 'bold'))
        style.configure('Number.TLabel', background='#e8f5f4', foreground='#087f8c', padding=(7, 4), font=('Microsoft YaHei UI', 9, 'bold'))
        style.configure('Hint.TLabel', foreground='#718096', font=('Microsoft YaHei UI', 9))
        style.configure('CardHint.TLabel', background='white', foreground='#718096', font=('Microsoft YaHei UI', 9))
        style.configure('TButton', background='white', foreground='#162b3d', bordercolor='#dfe7ef', lightcolor='#dfe7ef', darkcolor='#dfe7ef', padding=(12, 7), relief='solid', borderwidth=1)
        style.map('TButton', background=[('active', '#e8f5f4')], foreground=[('disabled', '#9ba8b7')])
        style.configure('Primary.TButton', background='#087f8c', foreground='white', padding=(22, 9), bordercolor='#087f8c', font=('Microsoft YaHei UI', 10, 'bold'))
        style.map('Primary.TButton', background=[('disabled', '#b7cdd1'), ('active', '#066c78')], foreground=[('disabled', 'white'), ('!disabled', 'white')])
        style.configure('TEntry', padding=6, fieldbackground='#f8fafc', bordercolor='#dfe7ef', lightcolor='#dfe7ef', darkcolor='#dfe7ef')
        style.configure('TCombobox', padding=6, fieldbackground='#f8fafc', background='#f8fafc', bordercolor='#dfe7ef', lightcolor='#dfe7ef', darkcolor='#dfe7ef', arrowcolor='#087f8c', arrowsize=14)
        style.map('TCombobox', fieldbackground=[('disabled', '#edf1f5'), ('readonly', '#f8fafc')], foreground=[('disabled', '#9ba8b7'), ('readonly', '#162b3d')], background=[('disabled', '#edf1f5'), ('active', '#e8f5f4'), ('readonly', '#f8fafc')], bordercolor=[('focus', '#087f8c'), ('active', '#087f8c')])
        self.checkbox_images = checkbox_images(w)
        unchecked, checked, disabled, disabled_checked = self.checkbox_images
        style.element_create('Paper.Check.indicator', 'image', unchecked,
                             ('disabled', 'selected', disabled_checked),
                             ('selected', checked), ('disabled', disabled), sticky='')
        style.layout('TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children': [
            ('Paper.Check.indicator', {'side': 'left', 'sticky': ''}),
            ('Checkbutton.focus', {'side': 'left', 'sticky': 'w', 'children': [
                ('Checkbutton.label', {'sticky': 'nswe'})]})]})])
        style.configure('TCheckbutton', background='white', padding=0)
        style.map('TCheckbutton', background=[('active', 'white')], indicatorbackground=[('selected', '#087f8c'), ('!selected', '#f8fafc')], indicatorforeground=[('selected', 'white')])
        style.configure('Horizontal.TProgressbar', background='#087f8c', troughcolor='#dfe7ef', borderwidth=0, thickness=5)
        style.configure('Vertical.TScrollbar', background='#c7d3df', troughcolor='#f8fafc', borderwidth=0, arrowsize=12)
        w.columnconfigure(0, weight=1)
        w.rowconfigure(0, weight=1)
        outer = ttk.Frame(w, padding=(24, 18))
        outer.grid(row=0, column=0, sticky='nsew')
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky='ew', pady=(0, 14))
        header.columnconfigure(1, weight=1)
        tk.Label(header, text='译', bg='#087f8c', fg='white', font=('Microsoft YaHei UI', 19, 'bold'), padx=10, pady=4).grid(row=0, column=0, rowspan=2, padx=(0, 14))
        ttk.Label(header, text='论文 PDF 翻译', font=('Microsoft YaHei UI', 19, 'bold')).grid(row=0, column=1, sticky='w')
        ttk.Label(header, text='pdf2zh-viacodex  /  英文 → 简体中文', style='Hint.TLabel').grid(row=1, column=1, sticky='w', pady=(2, 0))
        self.login_button = ttk.Button(header, text='登录 ChatGPT', command=self.login_chatgpt)
        self.login_button.grid(row=0, column=3, rowspan=2, sticky='e')
        self.account_status = tk.StringVar()
        self.account_badge = tk.Label(header, textvariable=self.account_status,
                                      bg='#e8f5f4', fg='#0b8068', padx=12, pady=6,
                                      font=('Microsoft YaHei UI', 9))
        self.account_badge.grid(row=0, column=2, rowspan=2, sticky='e', padx=(12, 14))
        self.refresh_account_status()

        def card(row, number, title, expand=False):
            box = ttk.Frame(outer, style='Card.TFrame', padding=(18, 8))
            box.grid(row=row, column=0, sticky='nsew' if expand else 'ew', pady=(0, 12))
            box.columnconfigure(0, weight=1)
            heading = ttk.Frame(box, style='Card.TFrame')
            heading.grid(row=0, column=0, sticky='ew', pady=(0, 6))
            heading.columnconfigure(1, weight=1)
            ttk.Label(heading, text=number, style='Number.TLabel').grid(row=0, column=0, padx=(0, 10))
            ttk.Label(heading, text=title, style='Section.TLabel').grid(row=0, column=1, sticky='w')
            return box, heading

        self.file_box, _ = card(2, '01', '文件与保存位置')
        file_box = ttk.Frame(self.file_box, style='Card.TFrame')
        file_box.grid(row=1, column=0, sticky='ew')
        file_box.columnconfigure(1, weight=1)
        ttk.Label(file_box, text='原始 PDF', style='CardHint.TLabel').grid(row=0, column=0, sticky='w', padx=(0, 18))
        self.file_entry = ttk.Entry(file_box, textvariable=self.pdf)
        self.file_entry.grid(row=0, column=1, sticky='ew', padx=(0, 12))
        self.file_entry.bind('<FocusOut>', lambda event: self.inspect_file())
        self.browse_button = ttk.Button(file_box, text='选择 PDF…', command=self.browse)
        self.browse_button.grid(row=0, column=2, sticky='ew')
        ttk.Label(file_box, text='保存位置', style='CardHint.TLabel').grid(row=1, column=0, sticky='w', padx=(0, 18), pady=(8, 0))
        self.output_entry = ttk.Entry(file_box, textvariable=self.output_directory)
        self.output_entry.grid(row=1, column=1, sticky='ew', padx=(0, 12), pady=(8, 0))
        self.output_button = ttk.Button(file_box, text='浏览文件夹…', command=self.browse_output)
        self.output_button.grid(row=1, column=2, sticky='ew', pady=(8, 0))

        self.options_box, _ = card(3, '02', '翻译设置')
        options = ttk.Frame(self.options_box, style='Card.TFrame')
        options.grid(row=1, column=0, sticky='ew')
        options.columnconfigure(0, weight=1)
        model_row = ttk.Frame(options, style='Card.TFrame')
        model_row.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        model_row.columnconfigure(4, weight=1)
        ttk.Label(model_row, text='翻译模型', style='CardHint.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 5))
        ttk.Label(model_row, text='思考强度', style='CardHint.TLabel').grid(row=0, column=1, sticky='w', pady=(0, 5))
        self.model_box = ttk.Combobox(model_row, textvariable=self.model, state='readonly', width=23)
        self.model_box.grid(row=1, column=0, sticky='ew', padx=(0, 18))
        self.model_box.bind('<<ComboboxSelected>>', self.sync_efforts)
        self.effort_box = ttk.Combobox(model_row, textvariable=self.reasoning_effort, state='readonly', width=9)
        self.effort_box.grid(row=1, column=1, sticky='ew', padx=(0, 18))
        for combo in (self.model_box, self.effort_box):
            self.style_dropdown(combo)
        self.refresh_models_button = ttk.Button(model_row, text='刷新模型', command=self.refresh_models)
        self.refresh_models_button.grid(row=1, column=2)
        ttk.Label(model_row, textvariable=self.catalog_status, style='CardHint.TLabel', width=24).grid(row=1, column=4, sticky='e', padx=(12, 0))
        flags = ttk.Frame(options, style='Card.TFrame')
        flags.grid(row=1, column=0, sticky='ew', pady=(0, 8))
        flags.columnconfigure(0, weight=1)
        self.line_check = ttk.Checkbutton(flags, text='清理论文中的行号（无行号时不用勾选）', variable=self.remove_numbers)
        self.line_check.grid(row=0, column=0, sticky='w')
        self.pages_check = ttk.Checkbutton(flags, text='仅翻译指定页码', variable=self.only_pages, command=self.sync_pages)
        self.pages_check.grid(row=0, column=1, sticky='w', padx=(14, 8))
        self.pages_entry = ttk.Entry(flags, textvariable=self.pages, width=12)
        self.pages_entry.grid(row=0, column=2)
        output_row = ttk.Frame(options, style='Card.TFrame')
        output_row.grid(row=2, column=0, sticky='ew')
        output_row.columnconfigure(1, weight=1)
        output_left = ttk.Frame(output_row, style='Card.TFrame')
        output_left.grid(row=0, column=0, sticky='w')
        self.chinese_check = ttk.Checkbutton(output_left, text='纯中文 PDF', variable=self.output_chinese)
        self.chinese_check.pack(side='left', padx=(0, 16))
        self.bilingual_check = ttk.Checkbutton(output_left, text='中英对照 PDF（中文左 / 原文右）', variable=self.output_bilingual)
        self.bilingual_check.pack(side='left')
        output_right = ttk.Frame(output_row, style='Card.TFrame')
        output_right.grid(row=0, column=1, sticky='e', padx=(12, 0))
        self.open_check = ttk.Checkbutton(output_right, text='完成后打开 PDF', variable=self.open_finished)
        self.open_check.pack(side='left', padx=(0, 12))
        self.remember_check = ttk.Checkbutton(output_right, text='记住这些设置', variable=self.remember)
        self.remember_check.pack(side='left')

        self.progress_box, status_heading = card(4, '03', '运行状态与日志', expand=True)
        progress = self.progress_box
        progress.rowconfigure(3, weight=1)
        ttk.Label(status_heading, textvariable=self.elapsed, style='CardHint.TLabel').grid(row=0, column=2, padx=(12, 14))
        self.log_expanded = False
        self.expand_log_button = ttk.Button(status_heading, text='放大日志', command=self.toggle_log_view)
        self.expand_log_button.grid(row=0, column=3)
        self.status_label = ttk.Label(progress, textvariable=self.status, style='Card.TLabel', font=('Microsoft YaHei UI', 10, 'bold'), wraplength=740)
        self.status_label.grid(row=1, column=0, sticky='w')
        self.bar = ttk.Progressbar(progress, mode='indeterminate')
        self.bar.grid(row=2, column=0, sticky='ew', pady=(8, 12))
        log_frame = ttk.Frame(progress, style='Card.TFrame')
        log_frame.grid(row=3, column=0, sticky='nsew')
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.activity = tk.Text(log_frame, height=14, width=1, wrap='word', bg='#f8fafc', fg='#42566b', relief='flat', highlightthickness=1, highlightbackground='#dfe7ef', highlightcolor='#087f8c', font=('Microsoft YaHei UI', 10), padx=14, pady=12, state='disabled', selectbackground='#cdebea')
        self.activity.grid(row=0, column=0, sticky='nsew')
        self.log_scrollbar = ttk.Scrollbar(log_frame, orient='vertical', command=self.activity.yview)
        self.log_scrollbar.grid(row=0, column=1, sticky='ns')
        self.activity.configure(yscrollcommand=self.log_scrollbar.set)
        actions = ttk.Frame(outer)
        actions.grid(row=5, column=0, sticky='ew')
        self.start_button = ttk.Button(actions, text='开始翻译', style='Primary.TButton', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(actions, text='停止', command=self.stop_or_resume, state='disabled')
        self.stop_button.pack(side='left', padx=(12, 0))
        self.log_button = ttk.Button(actions, text='查看本次日志', command=self.open_log, state='disabled')
        self.log_button.pack(side='right')
        ttk.Button(actions, text='打开输出文件夹', command=self.open_outputs).pack(side='right', padx=(0, 12))
        self.controls = [self.file_entry, self.browse_button, self.output_entry, self.output_button, self.line_check, self.pages_check, self.open_check, self.remember_check, self.chinese_check, self.bilingual_check]
        self.sync_pages()

    def style_dropdown(self, combo):
        # The popup is a Tk listbox, so ttk.Style alone cannot theme it.
        popup = combo.tk.call('ttk::combobox::PopdownWindow', combo._w)
        combo.tk.call(str(popup)+'.f.l', 'configure',
                      '-font', ('Microsoft YaHei UI', 11),
                      '-background', 'white', '-foreground', '#162b3d',
                      '-selectbackground', '#e8f5f4', '-selectforeground', '#087f8c',
                      '-selectborderwidth', 0, '-activestyle', 'none',
                      '-borderwidth', 0, '-highlightthickness', 1,
                      '-highlightbackground', '#dfe7ef', '-highlightcolor', '#087f8c')

    def refresh_account_status(self):
        logged_in = self.logged_in = has_chatgpt_session()
        self.login_button.configure(text='取消登录' if self.login_in_progress else ('切换账号' if logged_in else '登录 ChatGPT'))
        self.account_status.set('● 已登录' if logged_in else '○ 未登录')
        self.account_badge.configure(bg='#e8f5f4' if logged_in else '#edf1f5',
                                     fg='#0b8068' if logged_in else '#718096')

    def apply_catalog(self, catalog, cached=False):
        self.models = catalog['models']
        if not self.model.get() or self.model.get() == 'default':
            row = next((x for x in self.models if x['is_default']), self.models[0])
            self.model.set(row['model'])
        self.model_box.configure(values=[row['model'] for row in self.models])
        self.sync_efforts()
        timestamp = catalog.get('official_fetched_at') or catalog.get('checked_at', '')
        try:
            shown_time = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00')).astimezone().strftime('%H:%M')
        except ValueError:
            shown_time = ''
        using_cache = cached or not catalog.get('remote_refreshed', False)
        self.catalog_status.set(('已缓存官方列表' if using_cache else '官方列表已更新') + (' · ' + shown_time if shown_time else ''))
        self.sync_model_controls()

    def sync_efforts(self, event=None):
        row = next((x for x in self.models if x['model'] == self.model.get()), None)
        if row is None:
            self.effort_box.configure(values=[])
            self.catalog_status.set('当前模型不在列表中，请选择')
            return
        self.effort_box.configure(values=row['efforts'])
        if self.reasoning_effort.get() not in row['efforts']:
            default = row['default_effort']
            self.reasoning_effort.set(default if default in row['efforts'] else row['efforts'][0])

    def sync_model_controls(self):
        state = 'disabled' if self.busy or self.login_in_progress else 'readonly'
        self.model_box.configure(state=state)
        self.effort_box.configure(state=state)
        cancelling = self.login_in_progress and self.login_cancel_requested.is_set()
        self.refresh_models_button.configure(state='disabled' if self.busy or self.catalog_loading or self.login_in_progress else 'normal')
        self.login_button.configure(text='取消登录' if self.login_in_progress else ('切换账号' if self.logged_in else '登录 ChatGPT'),
            state='disabled' if self.busy or self.catalog_loading or cancelling else 'normal')
        self.start_button.configure(state='disabled' if self.busy or self.login_in_progress else 'normal')
        if not self.busy and self.paused_command:
            self.stop_button.configure(state='disabled' if self.login_in_progress else 'normal')

    def cancel_login(self):
        if not self.login_in_progress or self.login_cancel_requested.is_set():
            return
        try:
            self.login_cancel_file.touch()
        except OSError as exc:
            self.note('无法取消登录：' + str(exc))
            return
        self.login_cancel_requested.set()
        self.status.set('正在取消未完成的登录；原账号保持不变…')
        self.sync_model_controls()

    def login_chatgpt(self):
        if self.login_in_progress:
            self.cancel_login()
            return
        if self.busy or self.catalog_loading:
            return
        sessions = ROOT / 'login-sessions'
        sessions.mkdir(mode=0o700, exist_ok=True)
        cancel_file = sessions / ('cancel-' + uuid.uuid4().hex)
        self.login_cancel_file = cancel_file
        self.login_cancel_requested.clear()
        self.login_in_progress = True
        self.sync_model_controls()
        self.status.set('正在等待 ChatGPT 授权（最多 5 分钟）')
        def worker():
            return_code = 1
            try:
                script = PROJECT_ROOT / '登录ChatGPT.cmd'
                if not script.is_file():
                    raise FileNotFoundError('找不到登录ChatGPT.cmd，请检查项目文件是否完整。')
                environment = os.environ.copy()
                environment['PDF2ZH_LOGIN_FROM_GUI'] = '1'
                environment['PDF2ZH_LOGIN_SCRIPT'] = str(script)
                environment['PDF2ZH_LOGIN_CANCEL_FILE'] = str(cancel_file)
                # cmd requires its own quoting syntax rather than list2cmdline.
                command = f'"{os.environ.get("COMSPEC", "cmd.exe")}" /d /c call "%PDF2ZH_LOGIN_SCRIPT%"'
                process = subprocess.Popen(command, cwd=PROJECT_ROOT, env=environment,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace', creationflags=HIDDEN)
                self.login_process = process
                with process.stdout:
                    for line in process.stdout:
                        if line.strip():self.events.put(('line', localize_login_line(line.strip())))
                return_code = process.wait()
            except Exception as exc:
                self.events.put(('error', str(exc)))
            finally:
                self.login_process = None
                cancel_file.unlink(missing_ok=True)
                self.events.put(('login_done', return_code))
        threading.Thread(target=worker,daemon=True).start()

    def refresh_models(self):
        if self.busy or self.catalog_loading or self.login_in_progress:
            return
        self.catalog_loading = True
        self.catalog_status.set('正在获取官方列表…')
        self.sync_model_controls()
        def worker():
            try:
                self.events.put(('models', fetch_models()))
            except Exception as exc:
                self.events.put(('models_error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def toggle_log_view(self):
        self.log_expanded = not self.log_expanded
        for group in (self.file_box, self.options_box):
            group.grid_remove() if self.log_expanded else group.grid()
        self.expand_log_button.configure(text='返回设置' if self.log_expanded else '放大日志')

    def note(self, text):
        at_bottom = self.activity.yview()[1] >= 0.995
        self.activity.configure(state='normal')
        self.activity.insert('end', datetime.datetime.now().strftime('%H:%M:%S') + '  ' + text + '\n')
        if at_bottom:
            self.activity.see('end')
        self.activity.configure(state='disabled')

    def restore_log(self, path):
        path = Path(path).resolve()
        path.relative_to(ROOT.resolve())
        if not path.is_file():
            return
        text = path.read_text(encoding='utf-8', errors='replace')
        self.gui_log = path
        self.log_button.configure(state='normal')
        self.activity.configure(state='normal')
        self.activity.insert('end', text + '\n')
        self.activity.see('end')
        self.activity.configure(state='disabled')
        for line in text.splitlines():
            if line.startswith('输出目录：'):
                directory = Path(line.split('：', 1)[1].strip())
                if inside_outputs(directory):
                    self.destination = directory
        if self.destination:
            try:
                manifest = json.loads((self.destination / 'manifest.json').read_text(encoding='utf-8-sig'))
                if manifest.get('status') == 'failed':
                    self.status.set('上次翻译未完成，缓存已保留')
                elif manifest.get('status') == 'completed':
                    self.status.set('上次翻译已完成')
            except (OSError, ValueError):
                pass

    def sync_pages(self):
        self.pages_entry.configure(state='normal' if self.only_pages.get() and not self.busy else 'disabled')

    def inspect_file(self):
        if self.busy:
            return
        path = Path(self.pdf.get().strip().strip('"'))
        if not path.is_file() or path.suffix.lower() != '.pdf':
            self.details.set('选择英文 PDF 后，点击“开始翻译”。')
            return
        try:
            import fitz
            with fitz.open(path) as doc:
                self.details.set(f'共 {len(doc)} 页  ·  原文只读，译文另存')
        except Exception:
            self.details.set('无法读取这个 PDF，请检查文件。')

    def browse(self):
        initial = Path(self.last_pdf_directory) if self.last_pdf_directory else None
        if initial is None or not initial.is_dir():
            current = Path(self.pdf.get().strip().strip('"'))
            initial = current.parent if current.is_file() else PROJECT_ROOT
        chosen = filedialog.askopenfilename(parent=self.window, title='选择英文论文 PDF', initialdir=str(initial), filetypes=[('PDF 文件', '*.pdf')])
        if chosen:
            self.pdf.set(chosen)
            self.last_pdf_directory = str(Path(chosen).resolve().parent)
            self.inspect_file()
            try:
                self.save_settings()
            except OSError as exc:
                self.note('无法保存上次选择的文件夹：' + str(exc))

    def browse_output(self):
        initial = Path(self.output_directory.get())
        if not initial.is_dir():
            initial = OUTPUT_ROOT if OUTPUT_ROOT.is_dir() else ROOT.parent
        chosen = filedialog.askdirectory(parent=self.window, title='选择生成 PDF 保存位置', initialdir=str(initial), mustexist=False)
        if chosen:
            try:
                directory = validate_output_directory(chosen)
            except ValueError as exc:
                messagebox.showerror('请检查保存位置', str(exc), parent=self.window)
                return
            self.output_directory.set(str(directory))

    def save_settings(self):
        # File-dialog history is independent of remembering translation options.
        preferences = {'last_pdf_directory': self.last_pdf_directory} if self.last_pdf_directory else {}
        if self.remember.get():
            preferences.update({'only_pages':self.only_pages.get(), 'pages':self.pages.get(), 'remove_numbers':self.remove_numbers.get(), 'open_finished':self.open_finished.get(), 'remember':True, 'output_directory':self.output_directory.get(), 'output_chinese':self.output_chinese.get(), 'output_bilingual':self.output_bilingual.get()})
        if preferences:
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            temporary = SETTINGS.with_suffix('.tmp')
            temporary.write_text(json.dumps(preferences, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(SETTINGS)
        else:
            SETTINGS.unlink(missing_ok=True)

    def set_busy(self, value):
        self.busy = value
        for control in self.controls:
            control.configure(state='disabled' if value else 'normal')
        self.start_button.configure(state='disabled' if value else 'normal')
        self.stop_button.configure(text='停止' if value or not self.paused_command else '继续', state='normal' if value or self.paused_command else 'disabled')
        self.sync_pages()
        self.sync_model_controls()
        if value:
            self.bar.start(12)
        else:
            self.bar.stop()

    def stop_or_resume(self):
        if self.busy:
            self.ask_stop()
        elif self.paused_command:
            self.start(resume=True)

    def task_settings(self):
        return {name: getattr(self, name).get() for name in (
            'pdf', 'output_directory', 'only_pages', 'pages', 'remove_numbers',
            'output_chinese', 'output_bilingual', 'open_finished')}

    def start(self, resume=False):
        if self.busy or self.login_in_progress:
            return
        try:
            if resume:
                if not self.paused_command or not self.paused_settings:
                    return
                for name, value in self.paused_settings.items():
                    getattr(self, name).set(value)
                command = list(self.paused_command)
            else:
                command = build_command(self.pdf.get(), self.only_pages.get(), self.pages.get(), self.remove_numbers.get(), self.output_directory.get(), self.output_chinese.get(), self.output_bilingual.get())
            save_translation_selection(self.model.get(), self.reasoning_effort.get(), self.models)
            self.save_settings()
        except Exception as exc:
            messagebox.showerror('请检查翻译设置', str(exc), parent=self.window)
            return
        self.running_command = list(command)
        self.running_settings = self.task_settings()
        self.paused_command = None
        self.paused_settings = None
        self.destination = None
        self.final_pdf = None
        self.cancel_requested.clear()
        self.started_at = time.monotonic()
        self.gui_log = ROOT / 'logs' / ('gui-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.log')
        self.log_button.configure(state='normal')
        self.set_busy(True)
        self.status.set('正在准备翻译…')
        self.note(('继续翻译：' if resume else '开始翻译：') + Path(command[2]).name)
        if resume:
            self.note('继续处理任务；仅复用同模型、同强度的缓存，PDF 解析与排版会重新执行。')
        self.note('生成：' + '、'.join(name for enabled, name in [(self.output_chinese.get(), '纯中文 PDF'), (self.output_bilingual.get(), '中英对照 PDF（中文左 / 原文右）')] if enabled))
        self.note('范围：' + (self.pages.get() if self.only_pages.get() else '全文') + '；行号清理：' + ('启用' if self.remove_numbers.get() else '关闭'))
        threading.Thread(target=self.run_worker, args=(command,), daemon=True).start()

    def run_worker(self, command):
        return_code = 1
        try:
            if self.cancel_requested.is_set():
                self.events.put(('done', None, True))
                return
            with self.gui_log.open('w', encoding='utf-8') as log:
                self.process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', errors='replace', creationflags=HIDDEN)
                if self.cancel_requested.is_set():
                    self.kill_process_tree()
                for line in self.process.stdout:
                    log.write(line)
                    log.flush()
                    self.events.put(('line', line.strip()))
                return_code = self.process.wait()
        except Exception as exc:
            self.events.put(('error', str(exc)))
        finally:
            self.process = None
        self.events.put(('done', return_code, self.cancel_requested.is_set()))

    def kill_process_tree(self):
        process = self.process
        if process is not None and process.poll() is None:
            subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=HIDDEN, timeout=25)

    def ask_stop(self):
        if self.busy and messagebox.askyesno('停止翻译', '停止本次翻译？已经完成的译文缓存会保留。', parent=self.window):
            self.stop()

    def stop(self):
        self.cancel_requested.set()
        self.status.set('正在停止…')
        self.stop_button.configure(state='disabled')
        def terminate():
            try:
                self.kill_process_tree()
            except Exception as exc:
                self.events.put(('error', '停止任务时出现问题：' + str(exc)))
        threading.Thread(target=terminate, daemon=True).start()

    def finish(self, return_code, cancelled):
        self.set_busy(False)
        manifest = None
        if self.destination:
            path = self.destination / 'manifest.json'
            try:
                manifest = json.loads(path.read_text(encoding='utf-8'))
                if cancelled and manifest.get('status') != 'completed':
                    manifest['status'] = 'cancelled'
                    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            except (OSError, ValueError):
                pass
        completed = return_code == 0 and manifest is not None and manifest.get('status') == 'completed'
        if completed:
            path = Path(manifest.get('output', ''))
            outputs = manifest.get('outputs') or [{'mode':'chinese', 'path':str(path)}]
            if inside_outputs(path) and path.is_file() and all(inside_outputs(item['path']) and Path(item['path']).is_file() for item in outputs):
                self.final_pdf = path
            else:
                completed = False
        if completed:
            self.paused_command = None
            self.paused_settings = None
            self.set_busy(False)
            self.status.set('翻译完成')
            for item in outputs:
                label = '中英对照 PDF' if item['mode'] == 'bilingual' else '纯中文 PDF'
                self.note(label + ' 已保存：' + item['path'])
            if self.open_finished.get() and not self.close_when_done:
                try:
                    open_file(self.final_pdf)
                except OSError as exc:
                    self.note('自动打开失败，可以从输出文件夹打开：' + str(exc))
        elif cancelled or (manifest and manifest.get('status') == 'paused'):
            self.status.set('已暂停' if manifest and manifest.get('status') == 'paused' else '已停止')
            self.paused_command = list(self.running_command) if self.running_command else None
            self.paused_settings = dict(self.running_settings) if self.running_settings else None
            self.set_busy(False)
            self.note('任务已停止，已完成译文缓存保留。点击“继续”处理剩余段落。')
        else:
            self.status.set('翻译未完成')
            self.note('请点击“查看本次日志”检查原因；未切换到付费 API。')
        if self.close_when_done:
            self.window.destroy()

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == 'login_done':
                    self.refresh_account_status()
                    self.login_in_progress = False
                    self.login_cancel_requested.clear()
                    self.login_cancel_file = None
                    self.sync_model_controls()
                    if event[1] == 0:
                        self.status.set('ChatGPT 登录成功，已切换至本次授权的账号')
                        self.note('授权成功，已切换账号，正在刷新模型列表。')
                        self.models = []
                        self.model_box.configure(values=[])
                        self.effort_box.configure(values=[])
                        self.refresh_models()
                    elif event[1] == 124:
                        self.status.set('登录等待已超过 5 分钟；原账号保留')
                        self.note('登录等待超时，已结束本次授权；界面操作已恢复。')
                    elif event[1] == 130:
                        self.status.set('登录已取消；原账号保留')
                        self.note('本次登录已取消；界面操作已恢复，原账号保持不变。')
                    else:
                        self.status.set('登录未完成；原账号保留，请查看下方日志')
                        self.note(f'登录脚本退出码：{event[1]}。原账号保持不变。')
                elif kind == 'models':
                    self.catalog_loading = False
                    self.apply_catalog(event[1])
                elif kind == 'models_error':
                    self.catalog_loading = False
                    self.catalog_status.set('刷新失败；使用官方缓存' if self.models else '获取失败，请刷新')
                    self.note('官方模型列表获取失败：' + event[1])
                    self.sync_model_controls()
                elif kind == 'line':
                    text = event[1]
                    if text.startswith('输出目录：'):
                        directory = Path(text.split('：', 1)[1].strip())
                        if inside_outputs(directory):
                            self.destination = directory
                        self.note(text)
                    elif text.startswith('完成：'):
                        pass
                    elif text:
                        self.note(text)
                        if '开始 PDF 解析' in text:
                            self.status.set('正在解析、翻译和排版…')
                        elif text.startswith('翻译进度：'):
                            self.status.set(text)
                elif kind == 'error':
                    self.note(event[1])
                elif kind == 'done':
                    self.finish(event[1], event[2])
        except queue.Empty:
            pass
        if self.busy and self.started_at:
            seconds = int(time.monotonic() - self.started_at)
            self.elapsed.set(f'已运行 {seconds // 60:02d}:{seconds % 60:02d}')
        if not self.close_when_done or self.busy:
            self.window.after(150, self.poll)

    def open_outputs(self):
        try:
            directory = self.destination if self.destination and self.destination.exists() else validate_output_directory(self.output_directory.get())
            directory.mkdir(parents=True, exist_ok=True)
            open_file(directory)
        except (ValueError, OSError) as exc:
            messagebox.showerror('无法打开保存位置', str(exc), parent=self.window)

    def open_log(self):
        path = self.destination / 'translation.log' if self.destination else self.gui_log
        if path and path.exists():
            open_file(path)

    def close(self):
        if self.login_in_progress:
            self.cancel_login()
        if self.busy:
            if not messagebox.askyesno('关闭窗口', '翻译仍在进行。停止任务并关闭窗口？', parent=self.window):
                return
            self.close_when_done = True
            self.stop()
        else:
            try:
                self.save_settings()
            except OSError:
                pass
            self.window.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-pdf', default='')
    parser.add_argument('--restore-log', default='')
    parser.add_argument('--pages', default='')
    parser.add_argument('--output-dir', default='')
    parser.add_argument('--remove-line-numbers', action='store_true')
    args = parser.parse_args()
    prepare_environment()
    window = tk.Tk()
    app = TranslationWindow(window, args.input_pdf, args.pages, args.remove_line_numbers, args.output_dir)
    if args.restore_log:
        app.restore_log(args.restore_log)
    window.mainloop()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # pythonw has no console: report startup failures visibly.
        messagebox.showerror('无法打开 PDF 翻译界面', str(exc))
