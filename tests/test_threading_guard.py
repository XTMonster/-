"""§3.1 主线程守卫测试。

依据：架构审核实测表明 Blender 不提供跨线程护栏，因此必须由本模块补上。
"""

from __future__ import annotations

import threading

import pytest

from block_director.utils.threading_guard import (
    ThreadViolation,
    assert_main_thread,
    capture_main_thread,
    is_main_thread,
    main_thread_only,
    off_main_thread,
)


def test_main_thread_is_detected():
    capture_main_thread()
    assert is_main_thread()
    assert not off_main_thread()
    assert_main_thread("unit-test")     # 不应抛异常


def test_background_thread_is_rejected():
    capture_main_thread()
    captured = {}

    def worker():
        try:
            assert_main_thread("worker")
            captured["raised"] = False
        except ThreadViolation as exc:
            captured["raised"] = True
            captured["message"] = str(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert captured["raised"] is True
    assert "非主线程" in captured["message"]
    assert "worker" in captured["message"]


def test_off_main_thread_helper_in_worker():
    capture_main_thread()
    captured = {}

    def worker():
        captured["off"] = off_main_thread("w")

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert captured["off"] is True


def test_decorator_blocks_worker_thread():
    capture_main_thread()

    @main_thread_only("guarded")
    def guarded(value):
        return value * 2

    assert guarded(21) == 42          # 主线程正常

    captured = {}

    def worker():
        try:
            guarded(1)
            captured["raised"] = False
        except ThreadViolation:
            captured["raised"] = True

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert captured["raised"] is True


def test_capture_returns_identifier():
    ident = capture_main_thread()
    assert isinstance(ident, int)
    assert ident == threading.main_thread().ident
