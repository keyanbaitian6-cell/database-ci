"""タッチ変換が飲み込むマウス側面ボタンを、この窓の履歴操作へ接続する。

WebView2の子プロセスに焦点がある場合も通知を受け、手前がこの窓のときだけ入力を読む。
左クリック等は変更せず、戻る／進むの解放だけを見る。座標や機器情報は保存しない。
"""
from __future__ import annotations

import ctypes
import struct

WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
# RI_MOUSE_BUTTON_4_UP / RI_MOUSE_BUTTON_5_UP（0x0400はホイール）。
# https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-rawmouse
BACK_UP = 0x0080
FORWARD_UP = 0x0200


def button_direction(flags):
    """押下では動かず、1回の解放につき1段だけ戻る／進む。"""
    released = flags & (BACK_UP | FORWARD_UP)
    return -1 if released == BACK_UP else 1 if released == FORWARD_UP else 0


def raw_mouse_flags(data, header_size):
    if len(data) < header_size + 24 or struct.unpack_from('<I', data)[0] != 0:
        return 0
    return struct.unpack_from('<H', data, header_size + 4)[0]


def navigate(control, direction, log):
    core = control.CoreWebView2
    if core is None:
        log.write('mouse_history_unavailable', reason='not_initialized')
        return False
    if direction == -1 and core.CanGoBack:
        core.GoBack()
    elif direction == 1 and core.CanGoForward:
        core.GoForward()
    else:
        log.write('mouse_history_unavailable', reason='history_end', direction=direction)
        return False
    log.write('mouse_history', direction='back' if direction == -1 else 'forward')
    return True


def install(window, log):
    """WinFormsのUIスレッドで呼ぶ。戻り値を窓が閉じるまで保持する。"""
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    comctl32 = ctypes.WinDLL('comctl32', use_last_error=True)

    class Device(ctypes.Structure):
        _fields_ = [('usage_page', ctypes.c_ushort), ('usage', ctypes.c_ushort),
                    ('flags', ctypes.c_uint), ('target', ctypes.c_void_p)]

    user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(Device), ctypes.c_uint, ctypes.c_uint]
    user32.RegisterRawInputDevices.restype = ctypes.c_bool
    user32.GetRawInputData.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p,
                                      ctypes.POINTER(ctypes.c_uint), ctypes.c_uint]
    user32.GetRawInputData.restype = ctypes.c_uint
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    hwnd = int(window.native.Handle.ToInt64())
    header_size = 8 + ctypes.sizeof(ctypes.c_void_p) * 2

    def receive(raw_handle):
        if user32.GetForegroundWindow() != hwnd:
            return
        size = ctypes.c_uint()
        if user32.GetRawInputData(raw_handle, RID_INPUT, None, ctypes.byref(size), header_size) != 0:
            return
        if not header_size + 24 <= size.value <= 4096:
            return
        data = ctypes.create_string_buffer(size.value)
        count = user32.GetRawInputData(raw_handle, RID_INPUT, data, ctypes.byref(size), header_size)
        if count != size.value:
            return
        flags = raw_mouse_flags(data.raw, header_size)
        if flags & 0x03C0:  # 側面ボタンの押下・解放だけ記録。座標や他の入力は残さない。
            log.write('mouse_history_input', buttons=flags & 0x03C0)
        direction = button_direction(flags)
        if direction:
            navigate(window.native.webview, direction, log)

    proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
                                  ctypes.c_size_t, ctypes.c_ssize_t, ctypes.c_size_t, ctypes.c_size_t)
    comctl32.SetWindowSubclass.argtypes = [ctypes.c_void_p, proc_type, ctypes.c_size_t, ctypes.c_size_t]
    comctl32.SetWindowSubclass.restype = ctypes.c_bool
    comctl32.RemoveWindowSubclass.argtypes = [ctypes.c_void_p, proc_type, ctypes.c_size_t]
    comctl32.RemoveWindowSubclass.restype = ctypes.c_bool
    comctl32.DefSubclassProc.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    comctl32.DefSubclassProc.restype = ctypes.c_ssize_t

    class Receiver:
        pass

    receiver = Receiver()
    receiver.receive = receive
    receiver.closed = False

    def close():
        if receiver.closed:
            return
        receiver.closed = True
        removal = Device(1, 2, 1, None)
        user32.RegisterRawInputDevices(ctypes.byref(removal), 1, ctypes.sizeof(Device))
        comctl32.RemoveWindowSubclass(hwnd, receiver.callback, id(receiver))

    def procedure(handle, message, wparam, lparam, subclass_id, reference):
        try:
            if message == WM_INPUT:
                receiver.receive(lparam)
            elif message == 0x0082:  # WM_NCDESTROY
                close()
        except Exception:
            log.write('mouse_history_failed')
        return comctl32.DefSubclassProc(handle, message, wparam, lparam)

    receiver.callback = proc_type(procedure)
    if not comctl32.SetWindowSubclass(hwnd, receiver.callback, id(receiver), 0):
        raise ctypes.WinError(ctypes.get_last_error())
    # WebView2の入力子窓は別プロセス。INPUTSINKで親へも通知を受けるが、
    # receiveの先頭で手前の窓を確認し、他アプリ中の入力は読み出さない。
    # NOLEGACYは指定せず、通常のクリック・タッチ変換を維持する。
    device = Device(1, 2, 0x0100, hwnd)  # RIDEV_INPUTSINK
    if not user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(Device)):
        error = ctypes.get_last_error()
        close()
        raise ctypes.WinError(error)

    def closed(sender, args):
        close()

    window.native.FormClosed += closed
    log.write('mouse_history_ready')
    return receiver, closed
