#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF章节切分工具

功能：根据PDF书签（目录）自动将PDF按章节切分成多个独立的PDF文件

依赖库：
    pip install pymupdf

使用方法：
    python pdf_chapter_splitter.py

作者：AI Assistant
日期：2026-01-17
"""

import os
import re
import sys
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Tuple, Optional


def sanitize_filename(name: str) -> str:
    """清理文件名，移除不合法字符"""
    # 移除或替换不合法的文件名字符
    invalid_chars = r'[<>:"/\\|?*]'
    name = re.sub(invalid_chars, '_', name)
    # 移除首尾空格和点
    name = name.strip(' .')
    # 限制文件名长度
    if len(name) > 100:
        name = name[:100]
    return name


def get_chapter_bookmarks(doc: fitz.Document) -> List[Tuple[int, str, int]]:
    """
    从PDF书签中提取章节信息
    
    返回: [(level, title, page_number), ...]
    """
    toc = doc.get_toc()  # 获取目录/书签
    if not toc:
        print("⚠️  警告：未找到PDF书签/目录，将尝试按固定页数切分")
        return []
    
    print(f"📚 找到 {len(toc)} 个书签条目")
    return toc


def find_chapters(toc: List[Tuple[int, str, int]]) -> List[Tuple[str, int, int]]:
    """
    从目录中识别章节及其页面范围
    
    返回: [(chapter_title, start_page, end_page), ...]
    """
    chapters = []
    
    # 筛选顶级章节（level=1）或包含"第"和"章"的条目
    chapter_entries = []
    for level, title, page in toc:
        # 识别章节标题的模式
        is_chapter = (
            level == 1 or  # 顶级书签
            re.search(r'第[一二三四五六七八九十\d]+章', title) or
            re.search(r'第[一二三四五六七八九十\d]+讲', title) or
            re.search(r'Chapter\s*\d+', title, re.IGNORECASE) or
            re.search(r'^\d+[\.\s]', title)  # 以数字开头
        )
        if is_chapter:
            chapter_entries.append((title, page))
    
    if not chapter_entries:
        # 如果没有找到章节，使用所有顶级书签
        chapter_entries = [(title, page) for level, title, page in toc if level == 1]
    
    if not chapter_entries:
        # 如果还是没有，使用所有书签
        chapter_entries = [(title, page) for level, title, page in toc]
    
    # 计算每个章节的页面范围
    for i, (title, start_page) in enumerate(chapter_entries):
        if i + 1 < len(chapter_entries):
            end_page = chapter_entries[i + 1][1] - 1
        else:
            end_page = -1  # 表示到文档结尾
        chapters.append((title, start_page, end_page))
    
    return chapters


def split_pdf_by_chapters(
    input_path: str,
    output_dir: str,
    include_all_bookmarks: bool = False
) -> int:
    """
    按章节切分PDF文件
    
    参数:
        input_path: 输入PDF文件路径
        output_dir: 输出目录路径
        include_all_bookmarks: 是否包含所有书签（而不仅是章节）
    
    返回: 成功切分的章节数
    """
    print(f"\n{'='*60}")
    print(f"📖 PDF章节切分工具")
    print(f"{'='*60}")
    print(f"📂 输入文件: {input_path}")
    print(f"📁 输出目录: {output_dir}")
    print(f"{'='*60}\n")
    
    # 检查输入文件
    if not os.path.exists(input_path):
        print(f"❌ 错误：输入文件不存在: {input_path}")
        return 0
    
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        # 打开PDF文档
        doc = fitz.open(input_path)
        total_pages = len(doc)
        print(f"📄 文档总页数: {total_pages}")
        
        # 获取书签
        toc = get_chapter_bookmarks(doc)
        
        if not toc:
            # 没有书签，按固定页数切分
            print("📝 将按每50页进行切分...")
            chapters = []
            pages_per_chapter = 50
            for i in range(0, total_pages, pages_per_chapter):
                end = min(i + pages_per_chapter, total_pages)
                chapters.append((f"部分_{i//pages_per_chapter + 1}", i + 1, end))
        else:
            # 打印书签结构
            print("\n📋 书签结构预览（前20个）:")
            for i, (level, title, page) in enumerate(toc[:20]):
                indent = "  " * (level - 1)
                print(f"  {indent}[{level}] {title} (第{page}页)")
            if len(toc) > 20:
                print(f"  ... 还有 {len(toc) - 20} 个书签")
            
            # 识别章节
            chapters = find_chapters(toc)
        
        print(f"\n🔍 识别到 {len(chapters)} 个章节待切分")

        # 切分并保存每个章节
        success_count = 0
        for i, (title, start_page, end_page) in enumerate(chapters, 1):
            # 处理结束页
            if end_page == -1:
                end_page = total_pages

            # 生成文件名
            clean_title = sanitize_filename(title)
            output_filename = f"{i:02d}_{clean_title}.pdf"
            output_path = os.path.join(output_dir, output_filename)

            try:
                # 创建新PDF（页面索引从0开始）
                new_doc = fitz.open()
                new_doc.insert_pdf(doc, from_page=start_page-1, to_page=end_page-1)

                # 保存
                new_doc.save(output_path)
                new_doc.close()

                page_count = end_page - start_page + 1
                print(f"  ✅ [{i}/{len(chapters)}] {output_filename}")
                print(f"      页面范围: {start_page}-{end_page} ({page_count}页)")
                success_count += 1

            except Exception as e:
                print(f"  ❌ [{i}/{len(chapters)}] 切分失败: {title}")
                print(f"      错误: {str(e)}")

        doc.close()

        # 打印统计信息
        print(f"\n{'='*60}")
        print(f"📊 切分完成统计")
        print(f"{'='*60}")
        print(f"  ✅ 成功: {success_count}/{len(chapters)} 个章节")
        print(f"  📁 输出目录: {output_dir}")
        print(f"{'='*60}\n")

        return success_count

    except Exception as e:
        print(f"❌ 处理PDF时发生错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return 0


def main():
    """主函数"""
    # 默认配置
    INPUT_PDF = "/Users/spike/Projects/SparrowRecSys/Slides/book_1/深度学习推荐系统实战.pdf"
    OUTPUT_DIR = "/Users/spike/Projects/SparrowRecSys/Slides/book_1/chapters"

    # 支持命令行参数
    if len(sys.argv) >= 2:
        INPUT_PDF = sys.argv[1]
    if len(sys.argv) >= 3:
        OUTPUT_DIR = sys.argv[2]

    # 执行切分
    result = split_pdf_by_chapters(INPUT_PDF, OUTPUT_DIR)

    if result > 0:
        print("🎉 处理完成！")
        sys.exit(0)
    else:
        print("😞 处理失败或无章节可切分")
        sys.exit(1)


if __name__ == "__main__":
    main()

