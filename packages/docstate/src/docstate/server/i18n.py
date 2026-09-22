"""UI strings. English is the reference; `zh-CN` is complete. Add a language
by adding a dict — missing keys fall back to English."""

from __future__ import annotations

from collections.abc import Callable

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "toggle_tree": "Show / hide categories",
        "home": "Home",
        "timeline": "Timeline",
        "search": "Search",
        "search_placeholder": "Search titles, tags, text",
        "demo_switch": "Demo: switch reader",
        "logout": "Sign out",
        "categories": "Categories",
        "all": "All",
        "recent": "Recently updated",
        "recent_sub": "{n} documents, most recently updated first",
        "docs_count": "{n} documents",
        "category_timeline": "Timeline of this category",
        "all_docs": "All documents",
        "see_all": "See all",
        "timeline_sub": "Every publication is an entry, grouped by day",
        "new": "new",
        "no_events": "Nothing has been published yet",
        "search_hint": "Type a keyword in the top bar to match titles, tags, summaries and text",
        "search_count": "“{q}” · {n} results",
        "no_matches": "No matching documents",
        "versions": "Version history",
        "versions_sub": "{title} · {n} versions · permanent address",
        "version": "Version",
        "label": "Label",
        "author": "Author",
        "time": "Time",
        "size": "Size",
        "source": "Source",
        "latest": "latest",
        "view": "View",
        "raw": "Raw",
        "source_file": "Source file",
        "download_source": "Download the {kind} source",
        "no_docs": "No documents yet",
        "switch_version": "Switch version",
        "fullscreen": "Full-screen preview (Esc to exit)",
        "toggle_outline": "Show / hide outline",
        "old_version_notice": "You are reading v{v} ({time}); the latest is v{latest}.",
        "back_to_latest": "Back to latest",
        "esc_exit": "exits full screen",
        "outline": "Outline",
        "outline_loading": "Reading headings…",
        "outline_empty": "No headings in this document",
        "sign_in_required": "Sign in required",
        "forbidden": "No permission",
        "go_login": "Sign in",
        "doc_not_found": "Document not found",
        "version_not_found": "Version not found",
        "saved_shared": "Saved · shared with everyone",
        "saved_me": "Saved · only you see this",
        "saved_memory": "This page only",
        "save_failed": "Could not save",
        "sidebar_resize": "Drag to resize, double-click to reset",
        "guest": "guest",
    },
    "zh-CN": {
        "toggle_tree": "显示 / 隐藏分类",
        "home": "首页",
        "timeline": "时间轴",
        "search": "搜索",
        "search_placeholder": "搜索标题、标签、正文",
        "demo_switch": "演示用：切换读者身份",
        "logout": "退出",
        "categories": "分类",
        "all": "全部",
        "recent": "最近更新",
        "recent_sub": "{n} 篇文档，按最后更新时间排列",
        "docs_count": "{n} 篇",
        "category_timeline": "看这个分类的时间轴",
        "all_docs": "全部文档",
        "see_all": "看全部",
        "timeline_sub": "每一次发布都是一条记录，按天分组",
        "new": "新建",
        "no_events": "还没有任何发布记录",
        "search_hint": "在顶部输入关键词，匹配标题、标签、摘要和正文",
        "search_count": "“{q}” · {n} 条",
        "no_matches": "没有匹配的文档",
        "versions": "版本历史",
        "versions_sub": "{title} · {n} 个版本 · 固定地址",
        "version": "版本",
        "label": "说明",
        "author": "发布者",
        "time": "时间",
        "size": "大小",
        "source": "来源",
        "latest": "最新",
        "view": "查看",
        "raw": "原始",
        "source_file": "源文件",
        "download_source": "下载 {kind} 源文件",
        "no_docs": "还没有文档",
        "switch_version": "切换版本",
        "fullscreen": "全屏预览（Esc 退出）",
        "toggle_outline": "显示 / 隐藏目录",
        "old_version_notice": "你在看 v{v}（{time}），最新是 v{latest}。",
        "back_to_latest": "回到最新",
        "esc_exit": "退出全屏",
        "outline": "目录",
        "outline_loading": "正在读取标题…",
        "outline_empty": "这篇没有小标题",
        "sign_in_required": "请先登录",
        "forbidden": "没有权限",
        "go_login": "去登录",
        "doc_not_found": "文档不存在",
        "version_not_found": "版本不存在",
        "saved_shared": "已保存 · 全员共享",
        "saved_me": "已保存 · 仅自己可见",
        "saved_memory": "仅本页内存",
        "save_failed": "保存失败",
        "sidebar_resize": "拖动调整宽度，双击恢复默认",
        "guest": "访客",
    },
}

Translator = Callable[..., str]


def translator(lang: str) -> Translator:
    table = STRINGS.get(lang) or STRINGS.get(lang.split("-")[0]) or STRINGS["en"]

    def t(key: str, **kw) -> str:
        template = table.get(key) or STRINGS["en"].get(key) or key
        return template.format(**kw) if kw else template

    return t


def ui_strings(lang: str) -> dict[str, str]:
    """The strings the rendered document itself needs (task-list hints)."""
    t = translator(lang)
    return {k: t(k) for k in ("saved_shared", "saved_me", "saved_memory", "save_failed")}
