"""翻译上下文窗口：将前序 N 页文本打包为 Context。

维持专有名词（剧名/人名/道具/黑话）跨页统一。
"""

from __future__ import annotations

from typing import List


def build_context(
    prev_pages: List[List[str]],
    max_chars: int = 6000,
) -> str:
    """prev_pages: 最近在前页的文本行列表（旧页在前）。

    拼装为「【前序页 k】…」结构，从最新页往前截断以适配 token 上限。
    """
    if not prev_pages:
        return ""
    parts: List[str] = []
    used = 0
    # 从最新的前序页开始回溯（prev_pages 已按时间序）
    for k in range(len(prev_pages) - 1, -1, -1):
        texts = prev_pages[k]
        if not texts:
            continue
        block = f"【前序页 {k + 1}】\n" + "\n".join(texts)
        if used + len(block) > max_chars:
            # 保留前 max_chars 字符
            room = max_chars - used
            if room > 64:
                parts.append(block[:room])
            break
        parts.append(block)
        used += len(block)
    parts.reverse()
    return "\n\n".join(parts)
